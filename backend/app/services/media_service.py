"""Media upload orchestration and API presentation helpers."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import database
from app.core.config import get_settings
from app.models import (
    CopyrightDeclaration,
    CreatorProfile,
    FileKind,
    MediaAsset,
    MediaFile,
    MediaStatus,
    MediaType,
    PriceListing,
    ScanStatus,
)
from app.services import media_processing as mp
from app.services.scanner import scan_file
from app.services.storage import get_storage

log = logging.getLogger("media")

DECLARATION_VERSION = "2026.1"
DECLARATION_TEXT = (
    "I declare that I am the author of this media or am authorized by its copyright owner to license it; "
    "that it does not infringe anyone's copyright, trademark, privacy or publicity rights; that I hold any "
    "model and property releases required for the licenses I offer; and that I have disclosed every existing "
    "license, including any exclusive license, that affects this media."
)


def build_search_text(asset: MediaAsset) -> str:
    parts = [asset.title, asset.description, asset.category.replace("_", " "), " ".join(asset.keywords or [])]
    parts += [asset.location_city or "", asset.location_region or "", asset.resolution_label or ""]
    return " ".join(p for p in parts if p).lower()


async def save_upload_to_temp(upload: UploadFile, workdir: Path) -> tuple[Path, mp.DetectedType, int]:
    """Stream the upload to disk with size enforcement; detect type from magic bytes."""
    settings = get_settings()
    head = await upload.read(64)
    detected = mp.detect_type(head)
    limit_mb = settings.max_video_upload_mb if detected.media_type is MediaType.video else settings.max_image_upload_mb
    limit = limit_mb * 1024 * 1024
    dest = workdir / f"upload.{detected.file_format}"
    size = len(head)
    with dest.open("wb") as fh:
        fh.write(head)
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise mp.MediaValidationError(f"File exceeds the {limit_mb} MB limit.")
            fh.write(chunk)
    return dest, detected, size


def incoming_key(ext: str) -> str:
    """Private staging key for an uploaded file awaiting processing."""
    return f"incoming/{uuid.uuid4().hex}/upload.{ext or 'bin'}"


def stage_file(path: Path, ext: str, content_type: str) -> str:
    key = incoming_key(ext)
    get_storage().put_file(key, path, content_type, public=False)
    return key


def process_asset_job(asset_id: uuid.UUID, staged_key: str) -> None:
    """Queue entry point: fetch the staged upload from storage, then process it."""
    workdir = mp.new_workdir()
    storage = get_storage()
    ext = staged_key.rsplit(".", 1)[-1]
    path = Path(workdir.name) / f"upload.{ext}"
    try:
        storage.download_to(staged_key, path)
    except Exception:  # noqa: BLE001 - staged object missing or unreadable
        log.exception("staged upload %s unavailable", staged_key)
        workdir.cleanup()
        _mark_failed(asset_id, "Upload could not be read. Please upload again.")
        return
    process_asset(asset_id, path, workdir)
    storage.delete(staged_key)


def _mark_failed(asset_id: uuid.UUID, message: str) -> None:
    db = database.SessionLocal()
    try:
        asset = db.get(MediaAsset, asset_id)
        if asset:
            asset.status, asset.processing_error = MediaStatus.failed, message
            db.commit()
    finally:
        db.close()


def process_asset(asset_id: uuid.UUID, original_path: Path, workdir_handle=None) -> None:
    """Background job: scan, extract metadata, store original + previews."""
    db = database.SessionLocal()
    storage = get_storage()
    try:
        asset = db.get(MediaAsset, asset_id)
        if not asset:
            return
        creator = db.get(CreatorProfile, asset.creator_id)
        watermark = f"{get_settings().brand_name} · {creator.display_name if creator else ''}".strip(" ·")
        try:
            asset.scan_status = scan_file(original_path)
            if asset.scan_status is ScanStatus.infected:
                raise mp.MediaValidationError("The file failed the malware scan.")
            asset.checksum_sha256 = mp.sha256_file(original_path)
            if asset.media_type is MediaType.photo:
                result = mp.process_image(original_path, watermark)
            else:
                result = mp.process_video(original_path, watermark, original_path.parent)

            key = mp.storage_key(asset.id, FileKind.original, asset.file_format or "bin")
            content_type = (mp.IMAGE_FORMATS | mp.VIDEO_FORMATS).get(asset.file_format or "", "application/octet-stream")
            storage.put_file(key, original_path, content_type, public=False)
            asset.files.append(MediaFile(
                kind=FileKind.original, is_public=False, storage_key=key, content_type=content_type,
                width=result.width, height=result.height, size_bytes=asset.file_size_bytes,
            ))
            for r in result.renditions:
                ext = "mp4" if r.content_type == "video/mp4" else "jpg"
                rkey = mp.storage_key(asset.id, r.kind, ext)
                if r.data is not None:
                    storage.put_bytes(rkey, r.data, r.content_type, public=True)
                    size = len(r.data)
                else:
                    storage.put_file(rkey, r.path, r.content_type, public=True)
                    size = r.path.stat().st_size
                asset.files.append(MediaFile(
                    kind=r.kind, is_public=True, storage_key=rkey, content_type=r.content_type,
                    width=r.width, height=r.height, size_bytes=size,
                ))
            asset.width, asset.height = result.width, result.height
            asset.duration_seconds, asset.frame_rate = result.duration_seconds, result.frame_rate
            asset.perceptual_hash = result.perceptual_hash
            asset.orientation = mp.orientation_of(result.width, result.height)
            asset.resolution_label = mp.resolution_label(result.width, result.height)
            asset.search_text = build_search_text(asset)
            asset.status = MediaStatus.pending_review
            asset.processing_error = None
        except mp.MediaValidationError as exc:
            asset.status = MediaStatus.failed
            asset.processing_error = str(exc)
        except Exception:  # noqa: BLE001 - record and surface any pipeline failure
            log.exception("media processing failed for %s", asset_id)
            asset.status = MediaStatus.failed
            asset.processing_error = "Processing failed. Please try again or contact support."
        db.commit()
    finally:
        db.close()
        if workdir_handle is not None:
            workdir_handle.cleanup()


# --- Presentation ------------------------------------------------------------------

def public_url(file: MediaFile | None) -> str | None:
    if not file or not file.is_public:
        return None
    return get_storage().public_url(file.storage_key)


def creator_summary(creator: CreatorProfile) -> dict:
    return {
        "id": creator.id,
        "handle": creator.handle,
        "display_name": creator.display_name,
        "avatar_url": creator.avatar_url,
        "verification_status": creator.verification_status.value,
    }


def to_card(asset: MediaAsset, creator: CreatorProfile, prices: list[PriceListing] | None = None) -> dict:
    preview = asset.file(FileKind.preview)
    thumb = asset.file(FileKind.thumbnail)
    paid = [p.price_cents for p in (prices or []) if p.is_active and p.price_cents > 0]
    return {
        "id": asset.id,
        "title": asset.title,
        "media_type": asset.media_type.value,
        "category": asset.category,
        "orientation": asset.orientation.value if asset.orientation else None,
        "width": asset.width,
        "height": asset.height,
        "duration_seconds": asset.duration_seconds,
        "resolution_label": asset.resolution_label,
        "is_free": asset.is_free,
        "thumbnail_url": public_url(thumb),
        "preview_url": public_url(preview),
        "creator": creator_summary(creator),
        "starting_price_cents": min(paid) if paid else None,
        "currency": prices[0].currency if prices else "USD",
    }


def prices_for(db: Session, asset_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PriceListing]]:
    out: dict[uuid.UUID, list[PriceListing]] = {}
    if not asset_ids:
        return out
    for p in db.scalars(select(PriceListing).where(PriceListing.asset_id.in_(asset_ids), PriceListing.is_active)):
        out.setdefault(p.asset_id, []).append(p)
    return out


def to_detail(asset: MediaAsset, creator: CreatorProfile, prices: list[PriceListing], rejection_reason=None) -> dict:
    card = to_card(asset, creator, prices)
    files = [
        {"kind": f.kind.value, "url": public_url(f), "content_type": f.content_type, "width": f.width, "height": f.height}
        for f in asset.files
        if f.is_public
    ]
    return card | {
        "description": asset.description,
        "keywords": asset.keywords or [],
        "status": asset.status.value,
        "file_format": asset.file_format,
        "file_size_bytes": asset.file_size_bytes,
        "frame_rate": asset.frame_rate,
        "location_city": asset.location_city,
        "location_region": asset.location_region,
        "location_country": asset.location_country,
        "captured_at": asset.captured_at,
        "is_editorial_only": asset.is_editorial_only,
        "is_ai_generated": asset.is_ai_generated,
        "is_materially_altered": asset.is_materially_altered,
        "has_model_release": asset.has_model_release,
        "has_property_release": asset.has_property_release,
        "view_count": asset.view_count,
        "download_count": asset.download_count,
        "published_at": asset.published_at,
        "created_at": asset.created_at,
        "prices": [
            {
                "id": p.id,
                "license_code": p.license_type.code,
                "license_name": p.license_type.name,
                "size_tier": p.size_tier,
                "price_cents": p.price_cents,
                "currency": p.currency,
                "subscription_credit_eligible": p.subscription_credit_eligible,
            }
            for p in prices
            if p.is_active and not p.license_type.is_free
        ],
        "free_license_codes": [p.license_type.code for p in prices if p.is_active and p.license_type.is_free],
        "files": files,
        "processing_error": asset.processing_error,
        "rejection_reason": rejection_reason,
    }


def new_declaration(asset: MediaAsset, user_id, rights_owner_name: str, is_original_author: bool,
                    existing_licenses: str, has_prior_exclusive: bool, ip: str | None, ua: str | None):
    return CopyrightDeclaration(
        asset_id=asset.id,
        declarant_user_id=user_id,
        rights_owner_name=rights_owner_name,
        is_original_author=is_original_author,
        holds_necessary_rights=True,
        existing_licenses_disclosure=existing_licenses,
        has_prior_exclusive_grant=has_prior_exclusive,
        declaration_version=DECLARATION_VERSION,
        declaration_text=DECLARATION_TEXT,
        ip_address=ip,
        user_agent=(ua or "")[:400],
    )

"""Private client proofing galleries.

Galleries are separate from the public stock catalog. Originals go to the
private bucket; watermarked "PROOF" previews go to the public bucket under
random, unguessable paths. Clients open a gallery with its secret link (plus
an optional password, which yields a short-lived access key). They can mark
favorites and selections, comment, request revisions, approve the selection
and, if allowed, download originals through signed expiring links.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import database
from app.core.config import get_settings
from app.core.security import sign_download, verify_download
from app.models import ClientGallery, GalleryItem, GalleryItemStatus, GalleryStatus, MediaType, ScanStatus
from app.services import media_processing as mp
from app.services.scanner import scan_file
from app.services.storage import get_storage

log = logging.getLogger("galleries")

ACCESS_SECONDS = 12 * 3600


def new_token() -> str:
    return secrets.token_urlsafe(24)


def item_key(gallery_id, item_id, name: str) -> str:
    return f"galleries/{gallery_id}/{item_id}/{uuid.uuid4().hex}/{name}"


def process_item(item_id: uuid.UUID, path: Path, workdir_handle=None) -> None:
    db = database.SessionLocal()
    storage = get_storage()
    try:
        item = db.get(GalleryItem, item_id)
        if not item:
            return
        try:
            if scan_file(path) is ScanStatus.infected:
                raise mp.MediaValidationError("The file failed the malware scan.")
            text = f"PROOF · {get_settings().brand_name}"
            if item.media_type == MediaType.photo.value:
                result = mp.process_image(path, text)
            else:
                result = mp.process_video(path, text, path.parent)
            ext = path.suffix.lstrip(".") or "bin"
            item.original_key = item_key(item.gallery_id, item.id, f"original.{ext}")
            storage.put_file(item.original_key, path, item.original_content_type or "application/octet-stream",
                             public=False)
            for r in result.renditions:
                if r.kind.value == "thumbnail":
                    item.thumbnail_key = item_key(item.gallery_id, item.id, "thumb.jpg")
                    storage.put_bytes(item.thumbnail_key, r.data, r.content_type, public=True)
                elif r.kind.value == "preview":
                    name = "preview.mp4" if r.content_type == "video/mp4" else "preview.jpg"
                    item.preview_key = item_key(item.gallery_id, item.id, name)
                    if r.data is not None:
                        storage.put_bytes(item.preview_key, r.data, r.content_type, public=True)
                    else:
                        storage.put_file(item.preview_key, r.path, r.content_type, public=True)
            item.width, item.height = result.width, result.height
            item.status = GalleryItemStatus.ready
        except mp.MediaValidationError as exc:
            item.status, item.processing_error = GalleryItemStatus.failed, str(exc)
        except Exception:  # noqa: BLE001
            log.exception("gallery item %s failed", item_id)
            item.status, item.processing_error = GalleryItemStatus.failed, "Processing failed."
        db.commit()
    finally:
        db.close()
        if workdir_handle is not None:
            workdir_handle.cleanup()


def item_view(item: GalleryItem, include_flags: bool = True) -> dict:
    storage = get_storage()
    return {
        "id": item.id, "filename": item.filename, "media_type": item.media_type, "status": item.status.value,
        "preview_url": storage.public_url(item.preview_key) if item.preview_key else None,
        "thumbnail_url": storage.public_url(item.thumbnail_key) if item.thumbnail_key else None,
        "width": item.width, "height": item.height, "is_favorite": item.is_favorite,
        "is_selected": item.is_selected, "processing_error": item.processing_error,
    }


def expired(gallery: ClientGallery) -> bool:
    exp = gallery.expires_at
    if exp is None:
        return False
    exp = exp.replace(tzinfo=UTC) if exp.tzinfo is None else exp
    return exp < datetime.now(UTC)


def access_key(gallery: ClientGallery) -> str:
    return sign_download(gallery.id, "gallery", int(time.time()) + ACCESS_SECONDS)


def open_gallery(db: Session, token: str, request: Request) -> ClientGallery:
    """Resolve a client link; enforce status, expiry and password."""
    gallery = db.scalar(select(ClientGallery).where(ClientGallery.access_token == token))
    if not gallery or gallery.status in (GalleryStatus.draft, GalleryStatus.archived):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gallery not found")
    if expired(gallery):
        raise HTTPException(status.HTTP_410_GONE, "This gallery link has expired")
    if gallery.password_hash:
        parsed = verify_download(request.headers.get("x-gallery-key", ""))
        if not parsed or parsed != (gallery.id, "gallery"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "password_required")
    return gallery

"""Direct upload sessions and their completion endpoints."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.creators import my_profile
from app.core.database import get_db
from app.core.deps import current_user, verified_user
from app.core.jobs import enqueue
from app.core.rate_limit import client_ip, limiter
from app.models import (
    ClientGallery,
    Deliverable,
    GalleryItem,
    MediaAsset,
    MediaStatus,
    MilestoneStatus,
    RevenueModel,
    UploadPurpose,
    UploadSession,
    UploadStatus,
    User,
)
from app.models.media import MEDIA_CATEGORIES
from app.schemas.media import MediaDetail
from app.services import audit
from app.services import gallery_service as gs
from app.services import media_processing as mp
from app.services import media_service as ms
from app.services import production_service as svc
from app.services import upload_service as us
from app.services.storage import LocalStorage, get_storage

router = APIRouter(tags=["uploads"])


class UploadInit(BaseModel):
    purpose: UploadPurpose
    target_id: uuid.UUID | None = None
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(default="application/octet-stream", max_length=100)


@router.post("/uploads", status_code=201)
def init_upload(body: UploadInit, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    limiter.check(f"upload-init:{user.id}", 300, 3600)
    if body.purpose is UploadPurpose.media:
        my_profile(db, user)
    elif body.purpose is UploadPurpose.deliverable:
        m, _, _ = svc.load_milestone(db, body.target_id, user, "creator")
        if m.status not in (MilestoneStatus.funded, MilestoneStatus.revision_requested):
            raise HTTPException(status.HTTP_409_CONFLICT, "Deliver files once the milestone is funded")
    elif body.purpose is UploadPurpose.gallery_item:
        g = db.get(ClientGallery, body.target_id) if body.target_id else None
        if not g or g.creator_id != my_profile(db, user).id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Gallery not found")
    session, url = us.create_session(db, user, body.purpose, body.target_id, body.filename, body.size_bytes,
                                     body.content_type)
    db.commit()
    return {"id": session.id, "upload_url": url, "method": "PUT", "headers": {"Content-Type": session.content_type},
            "expires_at": session.expires_at, "max_size": session.max_size}


@router.put("/uploads/{upload_id}/blob", status_code=204)
async def put_blob(upload_id: uuid.UUID, request: Request, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Upload target when local storage is used (S3 deployments upload straight to the bucket)."""
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    session = db.get(UploadSession, upload_id)
    if not session or session.user_id != user.id or session.status is not UploadStatus.pending:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    path = storage.write_stream_path(session.storage_key)
    size = 0
    with path.open("wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            if size > session.max_size:
                fh.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
            fh.write(chunk)


class MediaComplete(BaseModel):
    upload_id: uuid.UUID
    title: str = Field(min_length=3, max_length=200)
    category: str
    description: str = Field(default="", max_length=5000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    location_city: str | None = Field(default=None, max_length=120)
    location_region: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(default=None, min_length=2, max_length=2)
    is_editorial_only: bool = False
    is_ai_generated: bool = False
    is_materially_altered: bool = False
    has_model_release: bool = False
    has_property_release: bool = False
    distribution: str = Field(default="nonexclusive", pattern="^(nonexclusive|free)$")
    rights_owner_name: str = Field(min_length=2, max_length=200)
    is_original_author: bool
    existing_licenses_disclosure: str = Field(default="", max_length=5000)
    has_prior_exclusive_grant: bool = False
    accept_declaration: bool


@router.post("/media/from-upload", response_model=MediaDetail, status_code=202)
def media_from_upload(body: MediaComplete, request: Request, background: BackgroundTasks,
                      user: User = Depends(verified_user), db: Session = Depends(get_db)):
    from app.api.v1.media import _active_agreement

    if not body.accept_declaration:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You must accept the copyright declaration")
    if body.category not in MEDIA_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category")
    if body.has_prior_exclusive_grant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Media already under an exclusive license elsewhere cannot be listed. Contact support.")
    creator = my_profile(db, user)
    agreement = _active_agreement(db, creator, RevenueModel(body.distribution))
    if not agreement:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Accept the {body.distribution} contributor agreement first")
    session = us.consume(db, body.upload_id, user, UploadPurpose.media)
    try:
        detected = us.detect(session)
    except mp.MediaValidationError as exc:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    asset = MediaAsset(
        creator_id=creator.id, uploaded_by=user.id, contributor_agreement_id=agreement.id,
        media_type=detected.media_type, status=MediaStatus.processing, title=body.title.strip(),
        description=body.description.strip(), category=body.category,
        keywords=[k.strip().lower() for k in body.keywords if k.strip()][:50], file_format=detected.file_format,
        file_size_bytes=session.declared_size, location_city=body.location_city, location_region=body.location_region,
        location_country=body.location_country.upper() if body.location_country else None,
        is_editorial_only=body.is_editorial_only, is_ai_generated=body.is_ai_generated,
        is_materially_altered=body.is_materially_altered, has_model_release=body.has_model_release,
        has_property_release=body.has_property_release,
    )
    asset.search_text = ms.build_search_text(asset)
    db.add(asset)
    db.flush()
    db.add(ms.new_declaration(asset, user.id, body.rights_owner_name, body.is_original_author,
                              body.existing_licenses_disclosure, False, client_ip(request),
                              request.headers.get("user-agent")))
    audit.record(db, "media.uploaded", user.id, "media_asset", asset.id, client_ip(request),
                 media_type=detected.media_type.value, size=session.declared_size, direct=True)
    db.commit()
    enqueue(ms.process_asset_job, asset.id, session.storage_key, background=background)
    return ms.to_detail(asset, creator, [])


class DeliverableComplete(BaseModel):
    upload_id: uuid.UUID
    note: str = Field(default="", max_length=2000)


@router.post("/milestones/{milestone_id}/deliverables/from-upload", status_code=201)
def deliverable_from_upload(milestone_id: uuid.UUID, body: DeliverableComplete, background: BackgroundTasks,
                            user: User = Depends(verified_user), db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "creator")
    if m.status not in (MilestoneStatus.funded, MilestoneStatus.revision_requested):
        raise HTTPException(status.HTTP_409_CONFLICT, "Deliver files once the milestone is funded")
    session = us.consume(db, body.upload_id, user, UploadPurpose.deliverable, target_id=m.id)
    final_key = f"deliverables/{project.id}/{m.id}/{uuid.uuid4().hex}/{session.filename}"
    storage = get_storage()
    storage.copy(session.storage_key, final_key, public_dest=False, content_type=session.content_type)
    storage.delete(session.storage_key)
    d = Deliverable(milestone_id=m.id, uploaded_by=user.id, filename=session.filename,
                    content_type=session.content_type, size_bytes=session.declared_size, storage_key=final_key,
                    checksum_sha256=None, scan_status="pending", note=body.note)
    db.add(d)
    audit.record(db, "production.deliverable_uploaded", user.id, "milestone", m.id, filename=d.filename,
                 size=d.size_bytes, direct=True)
    db.commit()
    enqueue(us.scan_deliverable_job, d.id, background=background)
    return {"id": d.id, "filename": d.filename, "size_bytes": d.size_bytes}


class GalleryItemComplete(BaseModel):
    upload_id: uuid.UUID


@router.post("/galleries/{gallery_id}/items/from-upload", status_code=202)
def gallery_item_from_upload(gallery_id: uuid.UUID, body: GalleryItemComplete, background: BackgroundTasks,
                             user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.get(ClientGallery, gallery_id)
    if not g or g.creator_id != my_profile(db, user).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gallery not found")
    session = us.consume(db, body.upload_id, user, UploadPurpose.gallery_item, target_id=g.id)
    try:
        detected = us.detect(session)
    except mp.MediaValidationError as exc:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    position = db.scalar(select(func.coalesce(func.max(GalleryItem.position), -1)).where(
        GalleryItem.gallery_id == g.id)) + 1
    item = GalleryItem(gallery_id=g.id, position=position, filename=session.filename,
                       media_type=detected.media_type.value, original_content_type=detected.content_type,
                       size_bytes=session.declared_size)
    db.add(item)
    db.commit()
    enqueue(gs.process_item_job, item.id, session.storage_key, background=background)
    return gs.item_view(item)


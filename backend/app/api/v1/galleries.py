"""Client galleries: creator management and the client-facing proofing view."""

import time
import uuid
from datetime import UTC, datetime
from datetime import time as dtime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import current_user, verified_user
from app.core.rate_limit import client_ip, limiter
from app.core.security import hash_password, sign_download, verify_download, verify_password
from app.models import (
    ClientGallery,
    CreatorProfile,
    GalleryComment,
    GalleryItem,
    GalleryItemStatus,
    GalleryStatus,
    Project,
    User,
)
from app.schemas.common import Message
from app.schemas.production import GalleryCommentIn, GalleryFlagsIn, GalleryIn, GalleryUnlockIn
from app.services import audit, email
from app.services import gallery_service as gs
from app.services import media_processing as mp
from app.services import media_service as ms
from app.services.notify import notify
from app.services.storage import get_storage

router = APIRouter(tags=["galleries"])

MAX_ITEMS = 2000


def _creator(db: Session, user: User) -> CreatorProfile:
    c = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user.id))
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create your storefront first")
    return c


def _own_gallery(db: Session, gallery_id: uuid.UUID, user: User) -> ClientGallery:
    g = db.get(ClientGallery, gallery_id)
    if not g or g.creator_id != _creator(db, user).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gallery not found")
    return g


def _items(db: Session, g: ClientGallery) -> list[GalleryItem]:
    return db.scalars(select(GalleryItem).where(GalleryItem.gallery_id == g.id)
                      .order_by(GalleryItem.position, GalleryItem.created_at)).all()


def _comments(db: Session, g: ClientGallery) -> list[dict]:
    return [{"id": c.id, "item_id": c.item_id, "author": c.author, "body": c.body,
             "is_revision_request": c.is_revision_request, "created_at": c.created_at}
            for c in db.scalars(select(GalleryComment).where(GalleryComment.gallery_id == g.id)
                                .order_by(GalleryComment.created_at))]


def gallery_out(db: Session, g: ClientGallery, owner: bool) -> dict:
    items = _items(db, g)
    out = {"id": g.id if owner else None, "title": g.title, "message": g.message, "client_name": g.client_name,
           "status": g.status.value, "allow_downloads": g.allow_downloads, "selection_limit": g.selection_limit,
           "client_approved_at": g.client_approved_at, "expires_at": g.expires_at,
           "items": [gs.item_view(i) for i in items if owner or i.status is GalleryItemStatus.ready],
           "comments": _comments(db, g), "selected_count": sum(1 for i in items if i.is_selected),
           "creator_name": db.get(CreatorProfile, g.creator_id).display_name}
    if owner:
        out |= {"client_email": g.client_email, "has_password": bool(g.password_hash), "project_id": g.project_id,
                "share_url": f"{get_settings().public_web_url}/g/{g.access_token}", "last_viewed_at": g.last_viewed_at,
                "created_at": g.created_at}
    return out


def _apply(g: ClientGallery, body: GalleryIn) -> None:
    g.title, g.message, g.client_name = body.title, body.message, body.client_name
    g.client_email = str(body.client_email) if body.client_email else None
    g.allow_downloads, g.selection_limit = body.allow_downloads, body.selection_limit
    g.expires_at = datetime.combine(body.expires_at, dtime(23, 59, 59), UTC) if body.expires_at else None
    if body.password:
        g.password_hash = hash_password(body.password)
    elif body.clear_password:
        g.password_hash = None


# --- Creator side ----------------------------------------------------------------------------

@router.get("/galleries")
def list_galleries(user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _creator(db, user)
    rows = db.scalars(select(ClientGallery).where(ClientGallery.creator_id == c.id)
                      .order_by(ClientGallery.created_at.desc()))
    out = []
    for g in rows:
        count = db.scalar(select(func.count(GalleryItem.id)).where(GalleryItem.gallery_id == g.id))
        out.append({"id": g.id, "title": g.title, "client_name": g.client_name, "status": g.status.value,
                    "item_count": count, "created_at": g.created_at, "client_approved_at": g.client_approved_at})
    return out


@router.post("/galleries", status_code=201)
def create_gallery(body: GalleryIn, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    c = _creator(db, user)
    if body.project_id:
        project = db.get(Project, body.project_id)
        if not project or project.creator_id != c.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    g = ClientGallery(creator_id=c.id, project_id=body.project_id, title=body.title, access_token=gs.new_token())
    _apply(g, body)
    db.add(g)
    db.commit()
    return gallery_out(db, g, owner=True)


@router.get("/galleries/{gallery_id}")
def get_gallery(gallery_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return gallery_out(db, _own_gallery(db, gallery_id, user), owner=True)


@router.put("/galleries/{gallery_id}")
def update_gallery(gallery_id: uuid.UUID, body: GalleryIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    g = _own_gallery(db, gallery_id, user)
    _apply(g, body)
    db.commit()
    return gallery_out(db, g, owner=True)


@router.post("/galleries/{gallery_id}/items", status_code=202)
async def add_item(gallery_id: uuid.UUID, background: BackgroundTasks, file: UploadFile = File(...),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _own_gallery(db, gallery_id, user)
    if db.scalar(select(func.count(GalleryItem.id)).where(GalleryItem.gallery_id == g.id)) >= MAX_ITEMS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gallery item limit reached")
    limiter.check(f"gallery-upload:{user.id}", 1000, 3600)
    workdir = mp.new_workdir()
    try:
        path, detected, size = await ms.save_upload_to_temp(file, mp.Path(workdir.name))
    except mp.MediaValidationError as exc:
        workdir.cleanup()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    position = db.scalar(select(func.coalesce(func.max(GalleryItem.position), -1)).where(
        GalleryItem.gallery_id == g.id)) + 1
    item = GalleryItem(gallery_id=g.id, position=position, filename=(file.filename or "file")[:255],
                       media_type=detected.media_type.value, original_content_type=detected.content_type,
                       size_bytes=size)
    db.add(item)
    db.commit()
    background.add_task(gs.process_item, item.id, path, workdir)
    return gs.item_view(item)


@router.delete("/galleries/{gallery_id}/items/{item_id}", response_model=Message)
def delete_item(gallery_id: uuid.UUID, item_id: uuid.UUID, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    g = _own_gallery(db, gallery_id, user)
    item = db.get(GalleryItem, item_id)
    if not item or item.gallery_id != g.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    db.delete(item)
    db.commit()
    return Message(detail="Removed")


@router.post("/galleries/{gallery_id}/share", response_model=Message)
def share_gallery(gallery_id: uuid.UUID, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    g = _own_gallery(db, gallery_id, user)
    if not db.scalar(select(GalleryItem.id).where(GalleryItem.gallery_id == g.id,
                                                  GalleryItem.status == GalleryItemStatus.ready)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add at least one processed item first")
    if g.status is GalleryStatus.draft:
        g.status = GalleryStatus.shared
    link = f"{get_settings().public_web_url}/g/{g.access_token}"
    if g.client_email:
        creator = db.get(CreatorProfile, g.creator_id)
        email.send(g.client_email, f"{creator.display_name} shared “{g.title}” with you",
                   f"Hi {g.client_name or 'there'},\n\n{g.message}\n\nView and select your favorites:\n{link}\n"
                   + ("\nThe password was sent to you separately by the creator." if g.password_hash else ""))
    audit.record(db, "gallery.shared", user.id, "client_gallery", g.id)
    db.commit()
    return Message(detail=link)


@router.post("/galleries/{gallery_id}/archive", response_model=Message)
def archive_gallery(gallery_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = _own_gallery(db, gallery_id, user)
    g.status = GalleryStatus.archived
    db.commit()
    return Message(detail="Archived")


@router.post("/galleries/{gallery_id}/comments", status_code=201)
def creator_comment(gallery_id: uuid.UUID, body: GalleryCommentIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    g = _own_gallery(db, gallery_id, user)
    db.add(GalleryComment(gallery_id=g.id, item_id=body.item_id, author="creator", body=body.body))
    db.commit()
    return {"ok": True}


# --- Client side (secret link, optional password) ------------------------------------------------

@router.get("/galleries/public/{token}")
def public_gallery(token: str, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"gallery-view:{client_ip(request)}", 300)
    g = gs.open_gallery(db, token, request)
    g.last_viewed_at = datetime.now(UTC)
    db.commit()
    return gallery_out(db, g, owner=False)


@router.post("/galleries/public/{token}/unlock")
def unlock_gallery(token: str, body: GalleryUnlockIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"gallery-unlock:{client_ip(request)}:{token}", 10)
    g = db.scalar(select(ClientGallery).where(ClientGallery.access_token == token))
    if not g or g.status in (GalleryStatus.draft, GalleryStatus.archived) or not g.password_hash:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gallery not found")
    if gs.expired(g):
        raise HTTPException(status.HTTP_410_GONE, "This gallery link has expired")
    if not verify_password(body.password, g.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password")
    return {"key": gs.access_key(g), "expires_in_seconds": gs.ACCESS_SECONDS}


def _client_item(db: Session, g: ClientGallery, item_id: uuid.UUID) -> GalleryItem:
    item = db.get(GalleryItem, item_id)
    if not item or item.gallery_id != g.id or item.status is not GalleryItemStatus.ready:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


@router.patch("/galleries/public/{token}/items/{item_id}")
def set_flags(token: str, item_id: uuid.UUID, body: GalleryFlagsIn, request: Request, db: Session = Depends(get_db)):
    g = gs.open_gallery(db, token, request)
    if g.status is GalleryStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "The selection was already approved")
    item = _client_item(db, g, item_id)
    if body.is_favorite is not None:
        item.is_favorite = body.is_favorite
    if body.is_selected is not None:
        if body.is_selected and not item.is_selected and g.selection_limit:
            selected = db.scalar(select(func.count(GalleryItem.id)).where(GalleryItem.gallery_id == g.id,
                                                                          GalleryItem.is_selected))
            if selected >= g.selection_limit:
                raise HTTPException(status.HTTP_409_CONFLICT, f"You can select up to {g.selection_limit} items")
        item.is_selected = body.is_selected
    db.commit()
    return gs.item_view(item)


@router.post("/galleries/public/{token}/comments", status_code=201)
def client_comment(token: str, body: GalleryCommentIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"gallery-comment:{client_ip(request)}", 60, 3600)
    g = gs.open_gallery(db, token, request)
    if body.item_id:
        _client_item(db, g, body.item_id)
    db.add(GalleryComment(gallery_id=g.id, item_id=body.item_id, author="client", body=body.body,
                          is_revision_request=body.is_revision_request))
    creator = db.get(CreatorProfile, g.creator_id)
    notify(db, creator.user_id, "gallery_revision" if body.is_revision_request else "gallery_comment",
           f"{'Revision request' if body.is_revision_request else 'Comment'} on {g.title}", body.body[:200],
           f"/dashboard/galleries/{g.id}", send_email=body.is_revision_request)
    db.commit()
    return {"ok": True}


@router.post("/galleries/public/{token}/approve", response_model=Message)
def approve_selection(token: str, request: Request, db: Session = Depends(get_db)):
    g = gs.open_gallery(db, token, request)
    selected = db.scalar(select(func.count(GalleryItem.id)).where(GalleryItem.gallery_id == g.id,
                                                                  GalleryItem.is_selected))
    if not selected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one item first")
    g.status, g.client_approved_at = GalleryStatus.approved, datetime.now(UTC)
    creator = db.get(CreatorProfile, g.creator_id)
    notify(db, creator.user_id, "gallery_approved", f"{g.client_name or 'Your client'} approved {selected} selections",
           g.title, f"/dashboard/galleries/{g.id}", send_email=True)
    db.commit()
    return Message(detail="Selection approved")


@router.post("/galleries/public/{token}/items/{item_id}/download")
def client_download(token: str, item_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    g = gs.open_gallery(db, token, request)
    if not g.allow_downloads:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Downloads are not enabled for this gallery")
    item = _client_item(db, g, item_id)
    expires = int(time.time()) + 900
    return {"url": f"{get_settings().api_prefix}/galleries/download/{sign_download(item.id, 'gallery_item', expires)}"}


@router.get("/galleries/download/{token}")
def gallery_download(token: str, db: Session = Depends(get_db)):
    parsed = verify_download(token)
    if not parsed or parsed[1] != "gallery_item":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Link is invalid or has expired")
    item = db.get(GalleryItem, parsed[0])
    g = db.get(ClientGallery, item.gallery_id) if item else None
    if not item or not item.original_key or not g or not g.allow_downloads or gs.expired(g):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    storage = get_storage()
    presigned = storage.private_download_url(item.original_key, item.filename, 300)
    if presigned:
        return RedirectResponse(presigned, status_code=302)
    return StreamingResponse(storage.open_private(item.original_key),
                             media_type=item.original_content_type or "application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{item.filename}"',
                                      "Cache-Control": "private, no-store"})


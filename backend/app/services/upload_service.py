"""Upload sessions: issue direct-upload targets and validate completed uploads."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import database
from app.core.config import get_settings
from app.models import Deliverable, ScanStatus, UploadPurpose, UploadSession, UploadStatus, User
from app.services import media_processing as mp
from app.services.notify import notify
from app.services.scanner import scan_file
from app.services.storage import get_storage

log = logging.getLogger("uploads")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str | None) -> str:
    return SAFE_NAME.sub("_", Path(name or "file").name)[:200] or "file"


def limit_for(purpose: UploadPurpose, content_type: str) -> int:
    s = get_settings()
    if purpose is UploadPurpose.deliverable:
        return s.max_deliverable_mb * 1024 * 1024
    mb = s.max_video_upload_mb if content_type.startswith("video/") else s.max_image_upload_mb
    return mb * 1024 * 1024


def create_session(db: Session, user: User, purpose: UploadPurpose, target_id, filename: str, size: int,
                   content_type: str) -> tuple[UploadSession, str]:
    limit = limit_for(purpose, content_type)
    if size <= 0 or size > limit:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File must be between 1 byte and {limit // (1024 * 1024)} MB")
    name = safe_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
    session = UploadSession(
        user_id=user.id, purpose=purpose, target_id=target_id, filename=name, content_type=content_type[:100],
        declared_size=size, max_size=limit, storage_key=f"incoming/{uuid.uuid4().hex}/upload.{ext}",
        expires_at=datetime.now(UTC) + timedelta(minutes=get_settings().upload_session_minutes),
    )
    db.add(session)
    db.flush()
    url = get_storage().presigned_upload_url(session.storage_key, session.content_type,
                                              get_settings().upload_session_minutes * 60)
    return session, url or f"{get_settings().api_prefix}/uploads/{session.id}/blob"


def consume(db: Session, upload_id: uuid.UUID, user: User, purpose: UploadPurpose, target_id=None) -> UploadSession:
    """Validate a finished upload and mark it used. Returns the session."""
    session = db.get(UploadSession, upload_id)
    if (not session or session.user_id != user.id or session.purpose is not purpose
            or (target_id is not None and session.target_id != target_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if session.status is not UploadStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload was already used")
    expires = session.expires_at.replace(tzinfo=UTC) if session.expires_at.tzinfo is None else session.expires_at
    if expires < datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "Upload session expired; please upload again")
    size = get_storage().size(session.storage_key)
    if size is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file has not been uploaded yet")
    if size == 0 or size > session.max_size:
        get_storage().delete(session.storage_key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty or too large")
    session.declared_size = size
    session.status = UploadStatus.consumed
    return session


def detect(session: UploadSession) -> mp.DetectedType:
    head = get_storage().read_head(session.storage_key, 64)
    try:
        return mp.detect_type(head)
    except mp.MediaValidationError:
        get_storage().delete(session.storage_key)
        raise


def scan_deliverable_job(deliverable_id: uuid.UUID) -> None:
    """Malware-scan a directly uploaded deliverable; remove it if infected."""
    db = database.SessionLocal()
    storage = get_storage()
    workdir = mp.new_workdir()
    try:
        d = db.get(Deliverable, deliverable_id)
        if not d:
            return
        path = Path(workdir.name) / "file"
        storage.download_to(d.storage_key, path)
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
        d.checksum_sha256 = digest.hexdigest()
        result = scan_file(path)
        if result is ScanStatus.infected:
            storage.delete(d.storage_key)
            notify(db, d.uploaded_by, "deliverable_rejected", f"{d.filename} failed the malware scan and was removed")
            db.delete(d)
        else:
            d.scan_status = result.value
        db.commit()
    finally:
        db.close()
        workdir.cleanup()

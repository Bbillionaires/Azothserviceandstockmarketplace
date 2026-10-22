"""Free-media licensing, license certificates and protected downloads."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user
from app.core.rate_limit import client_ip, limiter
from app.core.security import verify_download
from app.models import DownloadEntitlement, FileKind, GrantStatus, LicenseType, MediaAsset, RightsGrant, User
from app.schemas.licensing import DownloadOut, FreeDownloadIn, LicenseTypeOut, RightsGrantOut
from app.services import audit
from app.services.licensing_service import download_link, grant_view, issue_free_license
from app.services.storage import get_storage

router = APIRouter(tags=["licensing"])


@router.get("/license-types", response_model=list[LicenseTypeOut])
def license_types(db: Session = Depends(get_db)):
    return db.scalars(select(LicenseType).where(LicenseType.is_active).order_by(LicenseType.sort_order)).all()


@router.post("/media/{asset_id}/free-license", response_model=DownloadOut)
def free_license(asset_id: uuid.UUID, body: FreeDownloadIn, request: Request,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Issue (or reuse) a free license and return a short-lived download link."""
    limiter.check(f"free-dl:{user.id}", 120, 3600)
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    grant, ent = issue_free_license(db, user, asset, body.license_code, body.licensee_name, client_ip(request))
    db.commit()
    url, seconds = download_link(ent)
    return DownloadOut(certificate_number=grant.certificate_number, download_url=url, expires_in_seconds=seconds)


@router.get("/licenses/mine", response_model=list[RightsGrantOut])
def my_licenses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    grants = db.scalars(select(RightsGrant).where(RightsGrant.licensee_user_id == user.id)
                        .order_by(RightsGrant.issued_at.desc()))
    return [grant_view(g) for g in grants]


@router.post("/licenses/{certificate_number}/download", response_model=DownloadOut)
def redownload(certificate_number: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    grant = db.scalar(select(RightsGrant).where(RightsGrant.certificate_number == certificate_number,
                                                RightsGrant.licensee_user_id == user.id))
    if not grant or grant.status is not GrantStatus.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "License not found")
    ent = db.scalar(select(DownloadEntitlement).where(DownloadEntitlement.rights_grant_id == grant.id))
    if not ent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No download entitlement")
    url, seconds = download_link(ent)
    return DownloadOut(certificate_number=grant.certificate_number, download_url=url, expires_in_seconds=seconds)


@router.get("/licenses/verify/{certificate_number}", response_model=RightsGrantOut)
def verify_certificate(certificate_number: str, request: Request, db: Session = Depends(get_db)):
    """Public verification: anyone holding a certificate number can confirm it."""
    limiter.check(f"verify:{client_ip(request)}", 60)
    grant = db.scalar(select(RightsGrant).where(RightsGrant.certificate_number == certificate_number))
    if not grant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    return grant_view(grant)


@router.get("/downloads/{token}")
def download(token: str, request: Request, db: Session = Depends(get_db)):
    """Deliver an original. Authorized by the signed, expiring token + entitlement."""
    parsed = verify_download(token)
    if not parsed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Download link is invalid or has expired")
    ent_id, rendition = parsed
    ent = db.get(DownloadEntitlement, ent_id)
    if not ent or rendition != "original":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Download not found")
    grant = db.get(RightsGrant, ent.rights_grant_id)
    now = datetime.now(UTC)
    expires = ent.expires_at.replace(tzinfo=ent.expires_at.tzinfo or UTC) if ent.expires_at else None
    if not grant or grant.status is not GrantStatus.active or (expires and expires < now):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This license no longer permits downloads")
    if ent.download_count >= ent.max_downloads:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Download limit reached. Contact support.")
    asset = db.get(MediaAsset, ent.asset_id)
    original = asset.file(FileKind.original) if asset else None
    if not original:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File unavailable")
    ent.download_count += 1
    ent.last_downloaded_at = now
    audit.record(db, "download.original", ent.user_id, "download_entitlement", ent.id, client_ip(request),
                 certificate=grant.certificate_number)
    db.commit()

    filename = f"{grant.certificate_number}.{asset.file_format or 'bin'}"
    storage = get_storage()
    presigned = storage.private_download_url(original.storage_key, filename, 300)
    if presigned:
        return RedirectResponse(presigned, status_code=302)
    return StreamingResponse(
        storage.open_private(original.storage_key),
        media_type=original.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Cache-Control": "private, no-store"},
    )

"""Media upload, detail, editing, creator pricing and the creator's library."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.creators import my_profile
from app.core.database import get_db
from app.core.deps import current_user, optional_user, verified_user
from app.core.rate_limit import client_ip, limiter
from app.models import (
    AgreementStatus,
    AgreementTemplate,
    ContributorAgreement,
    CreatorProfile,
    LicenseType,
    MediaAsset,
    MediaStatus,
    ModerationAction,
    ModerationDecision,
    PriceListing,
    RevenueModel,
    RoleCode,
    User,
)
from app.models.media import MEDIA_CATEGORIES
from app.schemas.common import Message, Page
from app.schemas.media import MediaCard, MediaDetail, MediaUpdate, PricingIn
from app.services import audit
from app.services import media_processing as mp
from app.services import media_service as ms

router = APIRouter(prefix="/media", tags=["media"])

PUBLIC_STATUSES = {MediaStatus.approved}


def _load(db: Session, asset_id: uuid.UUID) -> tuple[MediaAsset, CreatorProfile]:
    row = db.execute(
        select(MediaAsset, CreatorProfile).join(CreatorProfile, CreatorProfile.id == MediaAsset.creator_id)
        .where(MediaAsset.id == asset_id)
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    return row[0], row[1]


def _is_owner(user: User | None, creator: CreatorProfile) -> bool:
    return bool(user and creator.user_id == user.id)


def _is_staff(user: User | None) -> bool:
    return bool(user and user.has_role(RoleCode.admin, RoleCode.moderator))


def _active_agreement(db: Session, creator: CreatorProfile, model: RevenueModel) -> ContributorAgreement | None:
    return db.scalar(
        select(ContributorAgreement).join(AgreementTemplate)
        .where(ContributorAgreement.creator_id == creator.id,
               ContributorAgreement.status == AgreementStatus.active,
               AgreementTemplate.revenue_model == model)
        .order_by(ContributorAgreement.effective_at.desc())
    )


def _latest_decision_reason(db: Session, asset_id: uuid.UUID) -> str | None:
    d = db.scalar(select(ModerationDecision).where(ModerationDecision.subject_type == "media_asset",
                                                   ModerationDecision.subject_id == asset_id)
                  .order_by(ModerationDecision.created_at.desc()))
    return d.reason if d and d.action in (ModerationAction.reject, ModerationAction.request_changes,
                                          ModerationAction.disable) else None


@router.post("", response_model=MediaDetail, status_code=202)
async def upload_media(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=3, max_length=200),
    category: str = Form(...),
    description: str = Form("", max_length=5000),
    keywords: str = Form("", max_length=2000, description="Comma-separated"),
    location_city: str | None = Form(None, max_length=120),
    location_region: str | None = Form(None, max_length=120),
    location_country: str | None = Form(None, min_length=2, max_length=2),
    is_editorial_only: bool = Form(False),
    is_ai_generated: bool = Form(False),
    is_materially_altered: bool = Form(False),
    has_model_release: bool = Form(False),
    has_property_release: bool = Form(False),
    distribution: str = Form("nonexclusive", pattern="^(nonexclusive|free)$"),
    # Copyright declaration
    rights_owner_name: str = Form(..., min_length=2, max_length=200),
    is_original_author: bool = Form(...),
    existing_licenses_disclosure: str = Form("", max_length=5000),
    has_prior_exclusive_grant: bool = Form(False),
    accept_declaration: bool = Form(...),
    user: User = Depends(verified_user),
    db: Session = Depends(get_db),
):
    limiter.check(f"upload:{user.id}", 60, 3600)
    if not accept_declaration:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You must accept the copyright declaration")
    if category not in MEDIA_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category")
    if has_prior_exclusive_grant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Media already under an exclusive license elsewhere cannot be listed. Contact support.")
    creator = my_profile(db, user)
    agreement = _active_agreement(db, creator, RevenueModel(distribution))
    if not agreement:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Accept the {distribution} contributor agreement before uploading")

    workdir = mp.new_workdir()
    try:
        path, detected, size = await ms.save_upload_to_temp(file, mp.Path(workdir.name))
    except mp.MediaValidationError as exc:
        workdir.cleanup()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    kw = [k.strip().lower() for k in keywords.split(",") if k.strip()][:50]
    asset = MediaAsset(
        creator_id=creator.id, uploaded_by=user.id, contributor_agreement_id=agreement.id,
        media_type=detected.media_type, status=MediaStatus.processing, title=title.strip(),
        description=description.strip(), category=category, keywords=kw, file_format=detected.file_format,
        file_size_bytes=size, location_city=location_city, location_region=location_region,
        location_country=location_country.upper() if location_country else None,
        is_editorial_only=is_editorial_only, is_ai_generated=is_ai_generated,
        is_materially_altered=is_materially_altered, has_model_release=has_model_release,
        has_property_release=has_property_release,
    )
    asset.search_text = ms.build_search_text(asset)
    db.add(asset)
    db.flush()
    db.add(ms.new_declaration(asset, user.id, rights_owner_name, is_original_author, existing_licenses_disclosure,
                              has_prior_exclusive_grant, client_ip(request), request.headers.get("user-agent")))
    audit.record(db, "media.uploaded", user.id, "media_asset", asset.id, client_ip(request),
                 media_type=detected.media_type.value, size=size, agreement=agreement.id)
    db.commit()
    background.add_task(ms.process_asset, asset.id, path, workdir)
    return ms.to_detail(asset, creator, [])


@router.get("/mine", response_model=Page[MediaDetail])
def my_media(
    status_filter: MediaStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    creator = my_profile(db, user)
    stmt = select(MediaAsset).where(MediaAsset.creator_id == creator.id)
    if status_filter:
        stmt = stmt.where(MediaAsset.status == status_filter)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    assets = db.scalars(stmt.order_by(MediaAsset.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    prices = ms.prices_for(db, [a.id for a in assets])
    items = [ms.to_detail(a, creator, prices.get(a.id, []), _latest_decision_reason(db, a.id)) for a in assets]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/featured", response_model=list[MediaCard])
def featured(media_type: str | None = Query(None, pattern="^(photo|video)$"), free: bool | None = None,
             limit: int = Query(12, ge=1, le=48), db: Session = Depends(get_db)):
    stmt = (select(MediaAsset, CreatorProfile).join(CreatorProfile, CreatorProfile.id == MediaAsset.creator_id)
            .where(MediaAsset.status == MediaStatus.approved))
    if media_type:
        stmt = stmt.where(MediaAsset.media_type == media_type)
    if free is not None:
        stmt = stmt.where(MediaAsset.is_free.is_(free))
    rows = db.execute(stmt.order_by(MediaAsset.is_featured.desc(),
                                    (MediaAsset.download_count * 5 + MediaAsset.view_count).desc(),
                                    MediaAsset.published_at.desc()).limit(limit)).all()
    prices = ms.prices_for(db, [a.id for a, _ in rows])
    return [ms.to_card(a, c, prices.get(a.id, [])) for a, c in rows]


@router.get("/{asset_id}", response_model=MediaDetail)
def media_detail(asset_id: uuid.UUID, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    asset, creator = _load(db, asset_id)
    owner = _is_owner(user, creator)
    if asset.status not in PUBLIC_STATUSES and not (owner or _is_staff(user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    if asset.status is MediaStatus.approved and not owner:
        asset.view_count += 1
        db.commit()
    prices = ms.prices_for(db, [asset.id]).get(asset.id, [])
    reason = _latest_decision_reason(db, asset.id) if owner or _is_staff(user) else None
    return ms.to_detail(asset, creator, prices, reason)


@router.patch("/{asset_id}", response_model=MediaDetail)
def update_media(asset_id: uuid.UUID, body: MediaUpdate, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    asset, creator = _load(db, asset_id)
    if not _is_owner(user, creator):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in MEDIA_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category")
    if "keywords" in data and data["keywords"] is not None:
        data["keywords"] = [k.strip().lower() for k in data["keywords"] if k.strip()]
    for key, value in data.items():
        setattr(asset, key, value)
    asset.search_text = ms.build_search_text(asset)
    # Edits after a change request go back into the review queue.
    if asset.status is MediaStatus.changes_requested:
        asset.status = MediaStatus.pending_review
    db.commit()
    return ms.to_detail(asset, creator, ms.prices_for(db, [asset.id]).get(asset.id, []))


@router.put("/{asset_id}/pricing", response_model=MediaDetail)
def set_pricing(asset_id: uuid.UUID, body: PricingIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Creator-controlled pricing. Replaces the asset's active price list.

    Creators set every price themselves; the platform never changes a price
    without the creator's action.
    """
    asset, creator = _load(db, asset_id)
    if not _is_owner(user, creator):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    types = {lt.code: lt for lt in db.scalars(select(LicenseType).where(LicenseType.is_active))}

    wanted: list[tuple[LicenseType, str, int, str, bool]] = []
    if body.free_license_code:
        lt = types.get(body.free_license_code)
        if not lt or not lt.is_free:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown free license")
        if not _active_agreement(db, creator, RevenueModel.free):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Accept the free distribution authorization first")
        wanted.append((lt, "original", 0, "USD", False))
    if body.prices:
        agreement = db.get(ContributorAgreement, asset.contributor_agreement_id) if asset.contributor_agreement_id else None
        if not agreement or agreement.template.revenue_model is not RevenueModel.nonexclusive:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "This media was submitted for free distribution only. Upload it under the "
                                "nonexclusive licensing agreement to sell paid licenses.")
    for p in body.prices:
        lt = types.get(p.license_code)
        if not lt or lt.is_free:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown paid license: {p.license_code}")
        if lt.is_exclusive or lt.code == "negotiated":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Exclusive and negotiated licenses are arranged per deal")
        if p.price_cents < 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Paid licenses must cost at least 1.00")
        wanted.append((lt, p.size_tier, p.price_cents, p.currency.upper(), p.subscription_credit_eligible))
    if asset.is_editorial_only and any(lt.allows_commercial_use for lt, *_ in wanted):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Editorial-only media cannot carry commercial licenses")

    existing = {(p.license_type_id, p.size_tier): p for p in db.scalars(
        select(PriceListing).where(PriceListing.asset_id == asset.id))}
    keep = set()
    for lt, tier, cents, cur, credit in wanted:
        row = existing.get((lt.id, tier))
        if row is None:
            row = PriceListing(asset_id=asset.id, license_type_id=lt.id, size_tier=tier)
            db.add(row)
        row.price_cents, row.currency, row.subscription_credit_eligible, row.is_active = cents, cur, credit, True
        keep.add((lt.id, tier))
    for key, row in existing.items():
        if key not in keep:
            row.is_active = False
    asset.is_free = bool(body.free_license_code)
    audit.record(db, "media.pricing_updated", user.id, "media_asset", asset.id,
                 prices=[{"license": lt.code, "tier": t, "cents": c} for lt, t, c, _, _ in wanted])
    db.commit()
    return ms.to_detail(asset, creator, ms.prices_for(db, [asset.id]).get(asset.id, []))


@router.post("/{asset_id}/withdraw", response_model=Message)
def withdraw(asset_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Remove media from sale going forward. Licenses already issued survive."""
    asset, creator = _load(db, asset_id)
    if not _is_owner(user, creator):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    asset.status = MediaStatus.withdrawn
    audit.record(db, "media.withdrawn", user.id, "media_asset", asset.id)
    db.commit()
    return Message(detail="Media withdrawn. Licenses already granted remain valid.")


@router.post("/{asset_id}/resubmit", response_model=Message)
def resubmit(asset_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset, creator = _load(db, asset_id)
    if not _is_owner(user, creator):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    if asset.status not in (MediaStatus.withdrawn, MediaStatus.changes_requested):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only withdrawn or returned media can be resubmitted")
    asset.status = MediaStatus.pending_review
    db.commit()
    return Message(detail="Submitted for review")


def publish(asset: MediaAsset) -> None:
    asset.status = MediaStatus.approved
    asset.published_at = asset.published_at or datetime.now(UTC)


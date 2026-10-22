"""Administrator control center (Phase 1 scope).

Moderation queue, user/role management, copyright complaints, appeals,
versioned commission rules, agreement legal-review status, audit log.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.auth import grant_role
from app.api.v1.media import publish
from app.core.database import get_db
from app.core.deps import require_roles
from app.models import (
    AgreementTemplate,
    AppealStatus,
    AuditLog,
    ComplaintStatus,
    ContentAppeal,
    CopyrightComplaint,
    CopyrightDeclaration,
    CreatorProfile,
    FileKind,
    LegalReviewStatus,
    MediaAsset,
    MediaStatus,
    ModerationAction,
    ModerationDecision,
    RevenueModel,
    RevenueShareRule,
    RightsGrant,
    Role,
    RoleCode,
    User,
    UserRole,
    UserStatus,
    VerificationStatus,
)
from app.schemas.admin import (
    AdminUserOut,
    AppealResolveIn,
    ComplaintStatusIn,
    DecisionIn,
    LegalReviewIn,
    QueueItem,
    RevenueRuleIn,
    RevenueRuleOut,
    RoleChangeIn,
    RoyaltyPreviewIn,
    StatusChangeIn,
)
from app.schemas.common import Message, Page
from app.services import audit
from app.services import media_service as ms
from app.services import royalty_engine as re_
from app.services.media_processing import hamming

router = APIRouter(prefix="/admin", tags=["admin"])

staff = require_roles(RoleCode.moderator)
finance = require_roles(RoleCode.finance_admin)
admin_only = require_roles()


# --- Moderation -----------------------------------------------------------------

def automated_signals(db: Session, asset: MediaAsset) -> dict:
    """Advisory duplicate signals. Never conclusive proof of infringement."""
    signals: dict = {}
    if asset.checksum_sha256:
        dupes = db.scalars(select(MediaAsset.id).where(MediaAsset.checksum_sha256 == asset.checksum_sha256,
                                                       MediaAsset.id != asset.id)).all()
        if dupes:
            signals["exact_duplicates"] = [str(d) for d in dupes]
    if asset.perceptual_hash and asset.media_type.value == "photo":
        near = []
        for other_id, other_hash in db.execute(
            select(MediaAsset.id, MediaAsset.perceptual_hash)
            .where(MediaAsset.perceptual_hash.is_not(None), MediaAsset.id != asset.id).limit(5000)
        ):
            if hamming(asset.perceptual_hash, other_hash) <= 4:
                near.append(str(other_id))
        if near:
            signals["near_duplicates"] = near[:20]
    if asset.scan_status.value != "clean":
        signals["malware_scan"] = asset.scan_status.value
    if asset.is_ai_generated or asset.is_materially_altered:
        signals["ai_disclosure"] = "creator disclosed AI generation or material alteration"
    if not asset.has_model_release and not asset.is_editorial_only:
        signals["release_check"] = "no model release declared; confirm no identifiable people for commercial use"
    return signals


@router.get("/moderation/queue", response_model=Page[QueueItem])
def moderation_queue(
    status_filter: MediaStatus = Query(MediaStatus.pending_review, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(staff),
    db: Session = Depends(get_db),
):
    stmt = (select(MediaAsset, CreatorProfile).join(CreatorProfile, CreatorProfile.id == MediaAsset.creator_id)
            .where(MediaAsset.status == status_filter))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(MediaAsset.created_at).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for asset, creator in rows:
        decl = db.scalar(select(CopyrightDeclaration).where(CopyrightDeclaration.asset_id == asset.id))
        items.append(QueueItem(
            id=asset.id, title=asset.title, media_type=asset.media_type.value, category=asset.category,
            status=asset.status.value, thumbnail_url=ms.public_url(asset.file(FileKind.thumbnail)),
            preview_url=ms.public_url(asset.file(FileKind.preview)), creator_handle=creator.handle,
            created_at=asset.created_at, scan_status=asset.scan_status.value,
            automated_signals=automated_signals(db, asset),
            declaration=None if not decl else {
                "rights_owner_name": decl.rights_owner_name,
                "is_original_author": decl.is_original_author,
                "existing_licenses_disclosure": decl.existing_licenses_disclosure,
                "declaration_version": decl.declaration_version,
                "accepted_at": decl.accepted_at.isoformat(),
            },
        ))
    return Page[QueueItem](items=items, total=total, page=page, page_size=page_size)


TRANSITIONS = {
    ModerationAction.approve: {MediaStatus.pending_review, MediaStatus.changes_requested, MediaStatus.rejected},
    ModerationAction.reject: {MediaStatus.pending_review, MediaStatus.changes_requested},
    ModerationAction.request_changes: {MediaStatus.pending_review},
    ModerationAction.disable: {MediaStatus.approved},
    ModerationAction.restore: {MediaStatus.disabled},
}


@router.post("/media/{asset_id}/decision", response_model=Message)
def decide(asset_id: uuid.UUID, body: DecisionIn, moderator: User = Depends(staff), db: Session = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    if asset.status not in TRANSITIONS[body.action]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot {body.action.value} media that is {asset.status.value}")
    if body.action is not ModerationAction.approve and not body.reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A reason is required so the creator can respond")
    if body.action is ModerationAction.approve and asset.scan_status.value == "infected":
        raise HTTPException(status.HTTP_409_CONFLICT, "Infected files cannot be approved")

    if body.action in (ModerationAction.approve, ModerationAction.restore):
        publish(asset)
    elif body.action is ModerationAction.reject:
        asset.status = MediaStatus.rejected
    elif body.action is ModerationAction.request_changes:
        asset.status = MediaStatus.changes_requested
    elif body.action is ModerationAction.disable:
        asset.status = MediaStatus.disabled

    decision = ModerationDecision(subject_type="media_asset", subject_id=asset.id, action=body.action,
                                  reason=body.reason.strip(), automated_signals=automated_signals(db, asset),
                                  moderator_id=moderator.id)
    db.add(decision)
    db.flush()
    audit.record(db, f"moderation.{body.action.value}", moderator.id, "media_asset", asset.id,
                 decision_id=decision.id, reason=body.reason)
    db.commit()
    return Message(detail=f"Media {asset.status.value}")


@router.get("/appeals")
def list_appeals(status_filter: AppealStatus = Query(AppealStatus.open, alias="status"),
                 _: User = Depends(staff), db: Session = Depends(get_db)):
    rows = db.execute(select(ContentAppeal, ModerationDecision)
                      .join(ModerationDecision, ModerationDecision.id == ContentAppeal.decision_id)
                      .where(ContentAppeal.status == status_filter).order_by(ContentAppeal.created_at)).all()
    return [{"id": a.id, "decision_id": d.id, "asset_id": d.subject_id, "action": d.action.value,
             "reason": d.reason, "statement": a.statement, "status": a.status.value, "created_at": a.created_at}
            for a, d in rows]


@router.post("/appeals/{appeal_id}/resolve", response_model=Message)
def resolve_appeal(appeal_id: uuid.UUID, body: AppealResolveIn, moderator: User = Depends(staff),
                   db: Session = Depends(get_db)):
    appeal = db.get(ContentAppeal, appeal_id)
    if not appeal or appeal.status is not AppealStatus.open:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Open appeal not found")
    decision = db.get(ModerationDecision, appeal.decision_id)
    if decision.moderator_id == moderator.id and not moderator.has_role(RoleCode.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Appeals must be reviewed by a different moderator")
    appeal.status = AppealStatus.overturned if body.overturn else AppealStatus.upheld
    appeal.resolved_by, appeal.resolution_note = moderator.id, body.note
    if body.overturn:
        asset = db.get(MediaAsset, decision.subject_id)
        if asset and asset.status in (MediaStatus.rejected, MediaStatus.disabled, MediaStatus.changes_requested):
            publish(asset)
            db.add(ModerationDecision(subject_type="media_asset", subject_id=asset.id,
                                      action=ModerationAction.restore if decision.action is ModerationAction.disable
                                      else ModerationAction.approve,
                                      reason=f"Appeal overturned: {body.note}", moderator_id=moderator.id))
    audit.record(db, "moderation.appeal_resolved", moderator.id, "content_appeal", appeal.id, overturned=body.overturn)
    db.commit()
    return Message(detail=f"Appeal {appeal.status.value}")


# --- Copyright complaints ----------------------------------------------------------

@router.get("/complaints")
def list_complaints(status_filter: ComplaintStatus | None = Query(None, alias="status"),
                    _: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(CopyrightComplaint).order_by(CopyrightComplaint.created_at)
    if status_filter:
        stmt = stmt.where(CopyrightComplaint.status == status_filter)
    return [{"id": c.id, "asset_id": c.asset_id, "complainant_name": c.complainant_name,
             "complainant_email": c.complainant_email, "work": c.copyrighted_work_description,
             "status": c.status.value, "counter_notice": c.counter_notice, "created_at": c.created_at}
            for c in db.scalars(stmt)]


COMPLAINT_TRANSITIONS = {
    ComplaintStatus.under_review: {ComplaintStatus.received},
    ComplaintStatus.content_disabled: {ComplaintStatus.received, ComplaintStatus.under_review},
    ComplaintStatus.rejected: {ComplaintStatus.received, ComplaintStatus.under_review},
    ComplaintStatus.restored: {ComplaintStatus.counter_notice_received, ComplaintStatus.content_disabled},
    ComplaintStatus.closed: set(ComplaintStatus),
}


@router.post("/complaints/{complaint_id}/status", response_model=Message)
def complaint_status(complaint_id: uuid.UUID, body: ComplaintStatusIn, moderator: User = Depends(staff),
                     db: Session = Depends(get_db)):
    complaint = db.get(CopyrightComplaint, complaint_id)
    if not complaint:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    try:
        new = ComplaintStatus(body.status)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status") from None
    if complaint.status not in COMPLAINT_TRANSITIONS.get(new, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot move from {complaint.status.value} to {new.value}")
    asset = db.get(MediaAsset, complaint.asset_id)
    if new is ComplaintStatus.content_disabled and asset and asset.status is MediaStatus.approved:
        asset.status = MediaStatus.disabled
        db.add(ModerationDecision(subject_type="media_asset", subject_id=asset.id, action=ModerationAction.disable,
                                  reason=f"Copyright notice {complaint.id}: {body.note}", moderator_id=moderator.id))
    if new is ComplaintStatus.restored and asset and asset.status is MediaStatus.disabled:
        publish(asset)
        db.add(ModerationDecision(subject_type="media_asset", subject_id=asset.id, action=ModerationAction.restore,
                                  reason=f"Restored after counter-notice {complaint.id}: {body.note}",
                                  moderator_id=moderator.id))
    complaint.status, complaint.handled_by, complaint.resolution_note = new, moderator.id, body.note
    audit.record(db, "copyright.complaint_status", moderator.id, "copyright_complaint", complaint.id, status=new.value)
    db.commit()
    return Message(detail=f"Complaint {new.value}")


# --- Users ------------------------------------------------------------------------------

def _admin_user(u: User) -> AdminUserOut:
    return AdminUserOut(id=u.id, email=u.email, display_name=u.display_name, status=u.status.value,
                        roles=sorted(u.role_codes), email_verified=u.email_verified_at is not None,
                        created_at=u.created_at)


@router.get("/users", response_model=Page[AdminUserOut])
def list_users(q: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               _: User = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.email.like(like), func.lower(User.display_name).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    users = db.scalars(stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page[AdminUserOut](items=[_admin_user(u) for u in users], total=total, page=page, page_size=page_size)


@router.post("/users/{user_id}/roles", response_model=AdminUserOut)
def change_role(user_id: uuid.UUID, body: RoleChangeIn, actor: User = Depends(admin_only),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    try:
        code = RoleCode(body.role)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role") from None
    if user.id == actor.id and code is RoleCode.admin and not body.grant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot remove your own admin role")
    if body.grant:
        grant_role(db, user, code, granted_by=actor.id)
    else:
        role = db.scalar(select(Role).where(Role.code == code.value))
        link = db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id))
        if link:
            user.roles.remove(link)
    user.token_version += 1  # force fresh sessions with the new permissions
    audit.record(db, "admin.role_changed", actor.id, "user", user.id, role=code.value, grant=body.grant)
    db.commit()
    db.refresh(user)
    return _admin_user(user)


@router.post("/users/{user_id}/status", response_model=AdminUserOut)
def change_status(user_id: uuid.UUID, body: StatusChangeIn, actor: User = Depends(admin_only),
                  db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own status")
    try:
        user.status = UserStatus(body.status)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status") from None
    user.token_version += 1
    audit.record(db, "admin.user_status", actor.id, "user", user.id, status=body.status, reason=body.reason)
    db.commit()
    return _admin_user(user)


@router.post("/creators/{handle}/verification", response_model=Message)
def verify_creator(handle: str, body: StatusChangeIn, actor: User = Depends(staff), db: Session = Depends(get_db)):
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == handle))
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    try:
        profile.verification_status = VerificationStatus(body.status)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status") from None
    audit.record(db, "admin.creator_verification", actor.id, "creator_profile", profile.id, status=body.status)
    db.commit()
    return Message(detail=f"Creator {profile.verification_status.value}")


@router.post("/creators/{handle}/feature", response_model=Message)
def feature_creator(handle: str, featured: bool = True, actor: User = Depends(admin_only),
                    db: Session = Depends(get_db)):
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == handle))
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    profile.is_featured = featured
    audit.record(db, "admin.creator_featured", actor.id, "creator_profile", profile.id, featured=featured)
    db.commit()
    return Message(detail="Updated")


@router.post("/media/{asset_id}/feature", response_model=Message)
def feature_media(asset_id: uuid.UUID, featured: bool = True, actor: User = Depends(admin_only),
                  db: Session = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    asset.is_featured = featured
    audit.record(db, "admin.media_featured", actor.id, "media_asset", asset.id, featured=featured)
    db.commit()
    return Message(detail="Updated")


# --- Commission rules (versioned, append-only) ------------------------------------------

def _rule_out(r: RevenueShareRule) -> RevenueRuleOut:
    return RevenueRuleOut(id=r.id, code=r.code, version=r.version, revenue_model=r.revenue_model.value,
                          creator_bps=r.creator_bps, initial_exclusive_creator_bps=r.initial_exclusive_creator_bps,
                          affiliate_bps_of_platform=r.affiliate_bps_of_platform,
                          net_revenue_deductions=r.net_revenue_deductions, notes=r.notes,
                          effective_from=r.effective_from)


@router.get("/revenue-rules", response_model=list[RevenueRuleOut])
def list_rules(_: User = Depends(finance), db: Session = Depends(get_db)):
    return [_rule_out(r) for r in db.scalars(select(RevenueShareRule)
                                             .order_by(RevenueShareRule.code, RevenueShareRule.version.desc()))]


@router.post("/revenue-rules", response_model=RevenueRuleOut, status_code=201)
def new_rule_version(body: RevenueRuleIn, actor: User = Depends(finance), db: Session = Depends(get_db)):
    """Create a new version. Existing versions (and every agreement signed
    against them) are never modified; new terms apply only to agreements
    accepted after a template is re-issued against the new version."""
    try:
        model = RevenueModel(body.revenue_model)
        re_.ShareRule(code=body.code, version=0, model=re_.Model(model.value), creator_bps=body.creator_bps,
                      initial_exclusive_creator_bps=body.initial_exclusive_creator_bps,
                      affiliate_bps_of_platform=body.affiliate_bps_of_platform,
                      net_revenue_deductions=tuple(body.net_revenue_deductions))
    except (ValueError, re_.RoyaltyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    current = db.scalar(select(func.max(RevenueShareRule.version)).where(RevenueShareRule.code == body.code)) or 0
    rule = RevenueShareRule(code=body.code, version=current + 1, revenue_model=model, creator_bps=body.creator_bps,
                            initial_exclusive_creator_bps=body.initial_exclusive_creator_bps,
                            affiliate_bps_of_platform=body.affiliate_bps_of_platform,
                            net_revenue_deductions=body.net_revenue_deductions, notes=body.notes,
                            created_by=actor.id)
    db.add(rule)
    db.flush()
    audit.record(db, "finance.revenue_rule_version", actor.id, "revenue_share_rule", rule.id,
                 code=rule.code, version=rule.version, creator_bps=rule.creator_bps)
    db.commit()
    return _rule_out(rule)


@router.post("/royalty-preview")
def royalty_preview(body: RoyaltyPreviewIn, _: User = Depends(finance), db: Session = Depends(get_db)):
    """Dry-run the royalty engine against a stored rule version."""
    r = db.get(RevenueShareRule, body.rule_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    try:
        rule = re_.ShareRule(r.code, r.version, re_.Model(r.revenue_model.value), r.creator_bps,
                             r.initial_exclusive_creator_bps, r.affiliate_bps_of_platform,
                             tuple(r.net_revenue_deductions))
        collabs = tuple(re_.Collaborator(f"collaborator_{i + 1}", bps) for i, bps in enumerate(body.collaborators_bps))
        result = re_.calculate(re_.RoyaltyInput(
            gross_cents=body.gross_cents, rule=rule, creator_party_id="creator", deductions=body.deductions,
            is_initial_exclusive_transaction=body.is_initial_exclusive_transaction,
            affiliate_party_id="affiliate" if body.with_affiliate else None, collaborators=collabs,
        ))
    except re_.RoyaltyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"net_cents": result.net_cents, "creator_pool_cents": result.creator_pool_cents,
            "platform_share_cents": result.platform_share_cents, "affiliate_cents": result.affiliate_cents,
            "platform_net_cents": result.platform_net_cents,
            "allocations": [a.__dict__ for a in result.allocations], "explanation": result.explain()}


@router.post("/agreement-templates/{template_id}/legal-review", response_model=Message)
def legal_review(template_id: uuid.UUID, body: LegalReviewIn, actor: User = Depends(admin_only),
                 db: Session = Depends(get_db)):
    """Record counsel's review outcome. The text itself can't be edited here:
    changed terms require a new template version."""
    t = db.get(AgreementTemplate, template_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    try:
        t.legal_review_status = LegalReviewStatus(body.status)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status") from None
    t.legal_reviewed_by, t.legal_reviewed_at = body.reviewer_name, datetime.now(UTC)
    audit.record(db, "legal.template_review", actor.id, "agreement_template", t.id,
                 status=body.status, reviewer=body.reviewer_name)
    db.commit()
    return Message(detail=f"Template {t.code} v{t.version} marked {body.status}")


# --- Audit log & stats ---------------------------------------------------------------------

@router.get("/audit-logs")
def audit_logs(action: str | None = None, subject_id: str | None = None, page: int = Query(1, ge=1),
               page_size: int = Query(50, ge=1, le=200), _: User = Depends(admin_only),
               db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if subject_id:
        stmt = stmt.where(AuditLog.subject_id == subject_id)
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return [{"id": r.id, "actor_user_id": r.actor_user_id, "action": r.action, "subject_type": r.subject_type,
             "subject_id": r.subject_id, "details": r.details, "ip_address": r.ip_address,
             "created_at": r.created_at} for r in rows]


@router.get("/stats")
def stats(_: User = Depends(staff), db: Session = Depends(get_db)):
    by_status = dict(db.execute(select(MediaAsset.status, func.count()).group_by(MediaAsset.status)).all())
    return {
        "users": db.scalar(select(func.count(User.id))),
        "creators": db.scalar(select(func.count(CreatorProfile.id))),
        "media_by_status": {k.value: v for k, v in by_status.items()},
        "licenses_issued": db.scalar(select(func.count(RightsGrant.id))),
        "open_complaints": db.scalar(select(func.count(CopyrightComplaint.id)).where(
            CopyrightComplaint.status.in_([ComplaintStatus.received, ComplaintStatus.under_review,
                                           ComplaintStatus.counter_notice_received]))),
        "open_appeals": db.scalar(select(func.count(ContentAppeal.id)).where(ContentAppeal.status == AppealStatus.open)),
    }

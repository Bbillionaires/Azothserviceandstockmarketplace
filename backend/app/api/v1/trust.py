"""Public trust & safety intake: copyright complaints, counter-notices, appeals."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user, optional_user
from app.core.rate_limit import client_ip, limiter
from app.models import (
    ComplaintStatus,
    ContentAppeal,
    CopyrightComplaint,
    CreatorProfile,
    MediaAsset,
    ModerationDecision,
    User,
)
from app.schemas.admin import AppealIn, ComplaintIn, CounterNoticeIn
from app.schemas.common import Message
from app.services import audit
from app.services.captcha import require_captcha

router = APIRouter(tags=["trust"])


@router.post("/copyright-complaints", response_model=Message, status_code=201)
def file_complaint(body: ComplaintIn, request: Request, user: User | None = Depends(optional_user),
                   db: Session = Depends(get_db)):
    limiter.check(f"complaint:{client_ip(request)}", 10, 3600)
    require_captcha(body.captcha_token, client_ip(request))
    if not (body.good_faith_statement and body.accuracy_statement):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A valid notice requires the good-faith and accuracy statements")
    if not db.get(MediaAsset, body.asset_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    complaint = CopyrightComplaint(complainant_user_id=user.id if user else None,
                                   **body.model_dump(exclude={"captcha_token"}))
    db.add(complaint)
    db.flush()
    audit.record(db, "copyright.complaint_received", user.id if user else None, "copyright_complaint",
                 complaint.id, client_ip(request), asset_id=body.asset_id)
    db.commit()
    # Content stays up until a moderator reviews the notice for completeness.
    return Message(detail=f"Notice received. Reference {complaint.id}")


@router.post("/copyright-complaints/{complaint_id}/counter-notice", response_model=Message)
def counter_notice(complaint_id: uuid.UUID, body: CounterNoticeIn, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    complaint = db.get(CopyrightComplaint, complaint_id)
    if not complaint:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    asset = db.get(MediaAsset, complaint.asset_id)
    creator = db.get(CreatorProfile, asset.creator_id) if asset else None
    if not creator or creator.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    if complaint.status is not ComplaintStatus.content_disabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A counter-notice applies only to disabled content")
    if not body.consent_to_jurisdiction:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consent to jurisdiction is required")
    complaint.counter_notice = body.model_dump() | {"submitted_at": datetime.now(UTC).isoformat()}
    complaint.status = ComplaintStatus.counter_notice_received
    audit.record(db, "copyright.counter_notice", user.id, "copyright_complaint", complaint.id, client_ip(request))
    db.commit()
    return Message(detail="Counter-notice received")


@router.post("/appeals", response_model=Message, status_code=201)
def appeal(body: AppealIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    decision = db.get(ModerationDecision, body.decision_id)
    if not decision or decision.subject_type != "media_asset":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    asset = db.get(MediaAsset, decision.subject_id)
    creator = db.get(CreatorProfile, asset.creator_id) if asset else None
    if not creator or creator.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    if db.scalar(select(ContentAppeal.id).where(ContentAppeal.decision_id == decision.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This decision has already been appealed")
    db.add(ContentAppeal(decision_id=decision.id, appellant_id=user.id, statement=body.statement))
    audit.record(db, "moderation.appeal_filed", user.id, "moderation_decision", decision.id)
    db.commit()
    return Message(detail="Appeal submitted")


@router.get("/media/{asset_id}/decisions")
def decisions_for_my_media(asset_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    creator = db.get(CreatorProfile, asset.creator_id) if asset else None
    if not creator or creator.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    rows = db.scalars(select(ModerationDecision).where(ModerationDecision.subject_type == "media_asset",
                                                       ModerationDecision.subject_id == asset.id)
                      .order_by(ModerationDecision.created_at.desc()))
    return [{"id": d.id, "action": d.action.value, "reason": d.reason, "created_at": d.created_at} for d in rows]


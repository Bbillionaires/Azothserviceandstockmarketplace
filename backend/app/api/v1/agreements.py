"""Contributor agreements: list available versions, accept, view my agreements."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.creators import my_profile
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import current_user
from app.core.rate_limit import client_ip
from app.models import (
    AgreementStatus,
    AgreementTemplate,
    ContributorAgreement,
    LegalReviewStatus,
    RevenueModel,
    SignatureMethod,
    User,
)
from app.schemas.licensing import AgreementAcceptIn, AgreementTemplateOut, ContributorAgreementOut
from app.services import audit

router = APIRouter(prefix="/agreements", tags=["agreements"])


def can_sign(t: AgreementTemplate) -> bool:
    """Whether creators may accept this template version right now.

    * Production: only versions counsel has approved.
    * Development/staging: drafts are allowed so the workflow can be tested.
    * Exclusive (Model B) needs a separately executed e-signature agreement
      and the exclusive-licensing feature flag; never by click-through.
    """
    settings = get_settings()
    if t.legal_review_status is LegalReviewStatus.retired:
        return False
    if t.revenue_model is RevenueModel.exclusive:
        return False
    if settings.is_production:
        return t.legal_review_status is LegalReviewStatus.approved
    return True


def latest_templates(db: Session) -> list[AgreementTemplate]:
    latest: dict[str, AgreementTemplate] = {}
    for t in db.scalars(select(AgreementTemplate).order_by(AgreementTemplate.code, AgreementTemplate.version)):
        if t.legal_review_status is not LegalReviewStatus.retired:
            latest[t.code] = t
    return list(latest.values())


def template_out(t: AgreementTemplate) -> AgreementTemplateOut:
    rule = t.revenue_share_rule
    return AgreementTemplateOut(
        id=t.id, code=t.code, version=t.version, title=t.title, revenue_model=t.revenue_model.value,
        body_markdown=t.body_markdown, body_sha256=t.body_sha256, territory=t.territory,
        permitted_uses=t.permitted_uses, sublicensing_allowed=t.sublicensing_allowed, duration=t.duration,
        withdrawal_terms=t.withdrawal_terms, legal_review_status=t.legal_review_status.value,
        creator_share_percent=rule.creator_bps / 100,
        initial_exclusive_share_percent=(rule.initial_exclusive_creator_bps / 100
                                         if rule.initial_exclusive_creator_bps is not None else None),
        available_to_sign=can_sign(t),
    )


def agreement_out(a: ContributorAgreement) -> ContributorAgreementOut:
    t = a.template
    return ContributorAgreementOut(
        id=a.id, template_code=t.code, template_version=t.version, title=t.title,
        revenue_model=t.revenue_model.value, signer_legal_name=a.signer_legal_name,
        rights_owner_name=a.rights_owner_name, territory=a.territory, permitted_uses=a.permitted_uses,
        sublicensing_allowed=a.sublicensing_allowed, duration=a.duration,
        signature_method=a.signature_method.value, effective_at=a.effective_at, status=a.status.value,
        legal_review_status=t.legal_review_status.value,
    )


@router.get("/templates", response_model=list[AgreementTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return [template_out(t) for t in latest_templates(db)]


@router.get("/mine", response_model=list[ContributorAgreementOut])
def my_agreements(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = my_profile(db, user)
    rows = db.scalars(select(ContributorAgreement).where(ContributorAgreement.creator_id == profile.id)
                      .order_by(ContributorAgreement.effective_at.desc()))
    return [agreement_out(a) for a in rows]


@router.post("/accept", response_model=ContributorAgreementOut, status_code=201)
def accept(body: AgreementAcceptIn, request: Request, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    if not body.i_agree:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You must agree to the terms")
    profile = my_profile(db, user)
    t = db.scalar(select(AgreementTemplate).where(AgreementTemplate.code == body.template_code,
                                                  AgreementTemplate.version == body.template_version))
    if not t or not can_sign(t):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This agreement is not available to sign")
    # The client must echo the hash of the exact text it displayed.
    if body.body_sha256 != t.body_sha256 or hashlib.sha256(t.body_markdown.encode()).hexdigest() != t.body_sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, "Agreement text changed; please review it again")

    for prior in db.scalars(select(ContributorAgreement).join(AgreementTemplate).where(
        ContributorAgreement.creator_id == profile.id, ContributorAgreement.status == AgreementStatus.active,
        AgreementTemplate.code == t.code,
    )):
        prior.status = AgreementStatus.superseded

    agreement = ContributorAgreement(
        template_id=t.id, creator_id=profile.id, signer_user_id=user.id,
        signer_legal_name=body.signer_legal_name.strip(), rights_owner_name=body.rights_owner_name.strip(),
        territory=t.territory, permitted_uses=t.permitted_uses, sublicensing_allowed=t.sublicensing_allowed,
        duration=t.duration, signature_method=SignatureMethod.clickwrap,
        signature_evidence={
            "ip": client_ip(request),
            "user_agent": request.headers.get("user-agent", "")[:400],
            "document_sha256": t.body_sha256,
            "template": f"{t.code}@v{t.version}",
            "legal_review_status_at_signing": t.legal_review_status.value,
            "environment": get_settings().environment,
        },
    )
    agreement.template = t
    db.add(agreement)
    db.flush()
    audit.record(db, "agreement.accepted", user.id, "contributor_agreement", agreement.id, client_ip(request),
                 template=f"{t.code}@v{t.version}")
    db.commit()
    return agreement_out(agreement)

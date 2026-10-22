"""Custom production: requests, proposals, projects, milestones and their money.

Milestone money flow (integer cents):

    Funding   Dr clearing (total − fee), Dr processing_fees (fee)
              Cr tax_payable (tax), Cr client_funds_held (amount)
    Release   Dr client_funds_held (amount)
              Cr creator_payable (amount × creator share), Cr platform_revenue (commission)
    Refund    Dr client_funds_held (amount), Dr tax_payable (tax)
              Cr clearing (amount + tax)

Funds stay in the payment provider's balance while held. This is a marketplace
payment workflow, not an escrow service. The commission comes from the
versioned ``services_commission`` rule, snapshotted on each project; the
platform pays processing fees out of its commission.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    CreatorProfile,
    DisputeStatus,
    Earning,
    EarningKind,
    EarningStatus,
    JournalKind,
    Milestone,
    MilestoneStatus,
    Order,
    OrderPurpose,
    OrderStatus,
    Project,
    ProjectDispute,
    ProjectRequest,
    ProjectStatus,
    Proposal,
    ProposalStatus,
    Refund,
    RefundReason,
    RequestInvitation,
    RequestStatus,
    RequestVisibility,
    RevenueShareRule,
    Review,
    ReviewDirection,
    RoleCode,
    ServicePackage,
    User,
)
from app.models.production import ConversationKind
from app.services import audit, ledger, messaging
from app.services import royalty_engine as engine
from app.services.notify import notify
from app.services.payment_service import share_rule
from app.services.payments import CheckoutItem, PaymentDetails, PaymentProvider

log = logging.getLogger("production")

HELD = (MilestoneStatus.funded, MilestoneStatus.submitted, MilestoneStatus.revision_requested,
        MilestoneStatus.disputed)
TERMINAL = (MilestoneStatus.approved, MilestoneStatus.refunded, MilestoneStatus.canceled)

# Which storefront categories fit each service category (for matching).
SERVICE_SKILLS: dict[str, set[str]] = {
    "commercial_production": {"production_studio", "director", "videographer", "cinematographer"},
    "documentary": {"filmmaker", "director", "cinematographer", "videographer"},
    "weddings": {"photographer", "videographer"},
    "corporate_video": {"videographer", "production_studio", "editor"},
    "interviews": {"videographer", "sound_engineer", "filmmaker"},
    "podcasts": {"sound_engineer", "videographer", "editor"},
    "music_videos": {"director", "videographer", "cinematographer", "colorist"},
    "real_estate": {"photographer", "drone_operator", "videographer"},
    "drone_services": {"drone_operator"},
    "product_photography": {"photographer", "retoucher"},
    "social_media_content": {"videographer", "photographer", "editor", "motion_designer"},
    "events": {"photographer", "videographer"},
    "sports": {"photographer", "videographer"},
    "hospitality": {"photographer", "videographer"},
    "news_editorial": {"photographer", "videographer", "filmmaker"},
    "video_editing": {"editor", "colorist"},
    "photo_editing": {"retoucher", "photographer"},
    "animation": {"motion_designer"},
    "motion_graphics": {"motion_designer"},
    "short_films": {"filmmaker", "director", "cinematographer", "production_studio"},
    "promotional_campaigns": {"production_studio", "media_agency", "videographer", "photographer"},
}


def now() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def creator_of(db: Session, user: User) -> CreatorProfile | None:
    return db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user.id))


def is_staff(user: User) -> bool:
    return user.has_role(RoleCode.admin, RoleCode.moderator, RoleCode.finance_admin)


def current_commission_rule(db: Session) -> RevenueShareRule:
    rule = db.scalar(select(RevenueShareRule).where(RevenueShareRule.code == "services_commission")
                     .order_by(RevenueShareRule.version.desc()))
    if not rule:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Services commission is not configured")
    return rule


# --- Requests ---------------------------------------------------------------------------

def can_view_request(db: Session, req: ProjectRequest, user: User | None) -> bool:
    if req.visibility is RequestVisibility.public and req.status is RequestStatus.open:
        return True
    if not user:
        return False
    if req.client_user_id == user.id or is_staff(user):
        return True
    creator = creator_of(db, user)
    if not creator:
        return False
    invited = db.scalar(select(RequestInvitation.id).where(RequestInvitation.request_id == req.id,
                                                           RequestInvitation.creator_id == creator.id))
    proposed = db.scalar(select(Proposal.id).where(Proposal.request_id == req.id, Proposal.creator_id == creator.id))
    return bool(invited or proposed)


def invite(db: Session, req: ProjectRequest, client: User, creator: CreatorProfile, message: str) -> None:
    if req.client_user_id != client.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if req.status is not RequestStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is no longer open")
    if creator.user_id == client.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot invite yourself")
    if not db.scalar(select(RequestInvitation.id).where(RequestInvitation.request_id == req.id,
                                                        RequestInvitation.creator_id == creator.id)):
        db.add(RequestInvitation(request_id=req.id, creator_id=creator.id, message=message[:2000]))
        notify(db, creator.user_id, "request_invitation", f"You're invited to quote: {req.title}",
               message[:300], f"/requests/{req.id}", send_email=True)


def match_creators(db: Session, req: ProjectRequest, limit: int = 10) -> list[dict]:
    """Rules-based matching: skills, location, availability, budget and track record."""
    skills = SERVICE_SKILLS.get(req.category, set())
    budget_max = req.budget_max_cents or req.budget_min_cents
    results = []
    for c in db.scalars(select(CreatorProfile).where(CreatorProfile.user_id != req.client_user_id)):
        reasons, score = [], 0.0
        overlap = skills & set(c.categories or [])
        if overlap:
            score += 4
            reasons.append("Skills: " + ", ".join(sorted(overlap)).replace("_", " "))
        same_city = (req.location_city and c.city and c.city.lower() == req.location_city.lower()
                     and (not req.location_country or c.country_code == req.location_country))
        if same_city:
            score += 3
            reasons.append(f"Based in {c.city}")
        elif req.location_country and c.country_code == req.location_country:
            score += 1
            if c.travel_available:
                score += 1
                reasons.append("Travels for work")
        if req.remote_ok and c.remote_available:
            score += 1.5
            reasons.append("Works remotely")
        if c.verification_status.value == "verified":
            score += 1
            reasons.append("Verified creator")
        rating = creator_rating(db, c.id)
        if rating["count"]:
            score += (rating["average"] - 3) + min(rating["completed_projects"], 10) * 0.2
            reasons.append(f"{rating['average']:.1f}★ from {rating['count']} reviews")
        if c.is_emerging_talent and budget_max is not None and budget_max <= 100_000:
            score += 1
            reasons.append("Emerging talent within budget")
        if score >= 3:
            results.append({"creator": c, "score": round(score, 2), "reasons": reasons})
    results.sort(key=lambda r: (-r["score"], r["creator"].display_name))
    return results[:limit]


# --- Proposals ----------------------------------------------------------------------------

def submit_proposal(db: Session, req: ProjectRequest, user: User, data: dict) -> Proposal:
    creator = creator_of(db, user)
    if not creator:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Open a storefront before sending proposals")
    if req.client_user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot bid on your own request")
    if req.status is not RequestStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is no longer accepting proposals")
    if req.visibility is RequestVisibility.invite_only and not db.scalar(
            select(RequestInvitation.id).where(RequestInvitation.request_id == req.id,
                                               RequestInvitation.creator_id == creator.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This request is by invitation only")
    milestones = data["milestones"]
    total = sum(m["amount_cents"] for m in milestones)
    if total != data["total_cents"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Milestone amounts must add up to the total")
    existing = db.scalar(select(Proposal).where(Proposal.request_id == req.id, Proposal.creator_id == creator.id))
    if existing and existing.status is not ProposalStatus.submitted and existing.status is not ProposalStatus.withdrawn:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your proposal has already been decided")
    proposal = existing or Proposal(request_id=req.id, creator_id=creator.id)
    if not existing:
        db.add(proposal)
        req.proposal_count += 1
    proposal.cover_letter, proposal.total_cents, proposal.currency = data["cover_letter"], total, req.currency
    proposal.milestones = milestones
    proposal.delivery_days, proposal.revisions_included = data["delivery_days"], data["revisions_included"]
    proposal.rights_type, proposal.rights_terms = data["rights_type"], data["rights_terms"]
    proposal.status = ProposalStatus.submitted
    db.flush()
    conv = messaging.get_or_create(db, ConversationKind.request, req.id, req.client_user_id, user.id,
                                   f"{req.title} · {creator.display_name}")
    messaging.post(db, conv, None, f"{creator.display_name} {'updated' if existing else 'sent'} a proposal: "
                                   f"{total / 100:,.2f} {req.currency}.", system=True)
    notify(db, req.client_user_id, "proposal_received", f"New proposal for {req.title}",
           f"{creator.display_name} quoted {total / 100:,.2f} {req.currency}.", f"/requests/{req.id}", send_email=True)
    return proposal


def _project_from(db: Session, *, client: User, creator: CreatorProfile, title: str, description: str,
                  currency: str, milestones: list[dict], revisions: int, rights_type, rights_terms: str,
                  evidence: dict, request_id=None, proposal_id=None, package_id=None) -> Project:
    rule = current_commission_rule(db)
    today = date.today()
    project = Project(
        client_user_id=client.id, creator_id=creator.id, request_id=request_id, proposal_id=proposal_id,
        package_id=package_id, title=title[:200], description=description, currency=currency,
        total_cents=sum(m["amount_cents"] for m in milestones), revisions_included=revisions,
        rights_type=rights_type, rights_terms=rights_terms, acceptance_evidence=evidence,
        commission_rule_id=rule.id,
        milestones=[
            Milestone(position=i, title=m["title"][:200], description=m.get("description", ""),
                      amount_cents=m["amount_cents"],
                      due_date=today + timedelta(days=m["due_in_days"]) if m.get("due_in_days") else None)
            for i, m in enumerate(milestones)
        ],
    )
    db.add(project)
    db.flush()
    conv = messaging.get_or_create(db, ConversationKind.project, project.id, client.id, creator.user_id,
                                   f"Project: {project.title}")
    messaging.post(db, conv, None, "Project booked. Fund the first milestone to get started.", system=True)
    return project


def accept_proposal(db: Session, proposal: Proposal, client: User, ip: str | None, ua: str | None) -> Project:
    req = db.get(ProjectRequest, proposal.request_id)
    if req.client_user_id != client.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    if req.status is not RequestStatus.open or proposal.status is not ProposalStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal can no longer be accepted")
    creator = db.get(CreatorProfile, proposal.creator_id)
    evidence = {
        "creator_user_id": str(creator.user_id),
        "creator_submitted_at": aware(proposal.updated_at).isoformat(),
        "client_user_id": str(client.id),
        "client_accepted_at": now().isoformat(),
        "client_ip": ip,
        "client_user_agent": (ua or "")[:300],
        "rights_type": proposal.rights_type.value,
        "rights_terms": proposal.rights_terms,
    }
    project = _project_from(db, client=client, creator=creator, title=req.title, description=req.description,
                            currency=proposal.currency, milestones=proposal.milestones,
                            revisions=proposal.revisions_included, rights_type=proposal.rights_type,
                            rights_terms=proposal.rights_terms, evidence=evidence, request_id=req.id,
                            proposal_id=proposal.id)
    proposal.status = ProposalStatus.accepted
    req.status = RequestStatus.awarded
    for other in db.scalars(select(Proposal).where(Proposal.request_id == req.id, Proposal.id != proposal.id,
                                                   Proposal.status == ProposalStatus.submitted)):
        other.status = ProposalStatus.declined
        notify(db, db.get(CreatorProfile, other.creator_id).user_id, "proposal_declined",
               f"Another creator was selected for {req.title}", link=f"/requests/{req.id}")
    notify(db, creator.user_id, "proposal_accepted", f"Your proposal was accepted: {req.title}",
           "The client will fund the first milestone before work starts.", f"/projects/{project.id}", send_email=True)
    audit.record(db, "production.proposal_accepted", client.id, "project", project.id, ip, proposal=proposal.id)
    return project


def book_package(db: Session, package: ServicePackage, client: User, brief: str, ip: str | None,
                 ua: str | None) -> Project:
    if not package.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found")
    creator = db.get(CreatorProfile, package.creator_id)
    if creator.user_id == client.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot book your own package")
    evidence = {
        "creator_user_id": str(creator.user_id),
        "creator_published_at": aware(package.updated_at).isoformat(),
        "client_user_id": str(client.id),
        "client_accepted_at": now().isoformat(),
        "client_ip": ip,
        "client_user_agent": (ua or "")[:300],
        "rights_type": package.rights_type.value,
        "rights_terms": package.rights_terms,
        "package_snapshot": {"title": package.title, "price_cents": package.price_cents,
                             "deliverables": package.deliverables, "delivery_days": package.delivery_days},
    }
    project = _project_from(
        db, client=client, creator=creator, title=package.title, description=brief or package.description,
        currency=package.currency,
        milestones=[{"title": package.title, "description": package.deliverables, "amount_cents": package.price_cents,
                     "due_in_days": package.delivery_days}],
        revisions=package.revisions_included, rights_type=package.rights_type, rights_terms=package.rights_terms,
        evidence=evidence, package_id=package.id,
    )
    notify(db, creator.user_id, "package_booked", f"New booking: {package.title}",
           (brief or "")[:300], f"/projects/{project.id}", send_email=True)
    audit.record(db, "production.package_booked", client.id, "project", project.id, ip, package=package.id)
    return project


# --- Project access and lifecycle ----------------------------------------------------------

def project_role(db: Session, project: Project, user: User) -> str | None:
    if project.client_user_id == user.id:
        return "client"
    if db.get(CreatorProfile, project.creator_id).user_id == user.id:
        return "creator"
    if is_staff(user):
        return "staff"
    return None


def load_project(db: Session, project_id: uuid.UUID, user: User, *roles: str) -> tuple[Project, str]:
    project = db.get(Project, project_id)
    role = project_role(db, project, user) if project else None
    if not project or not role or (roles and role not in roles):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project, role


def load_milestone(db: Session, milestone_id: uuid.UUID, user: User, *roles: str) -> tuple[Milestone, Project, str]:
    m = db.get(Milestone, milestone_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Milestone not found")
    project, role = load_project(db, m.project_id, user, *roles)
    return m, project, role


def _creator_user(db: Session, project: Project) -> uuid.UUID:
    return db.get(CreatorProfile, project.creator_id).user_id


def refresh_project_status(project: Project) -> None:
    states = [m.status for m in project.milestones]
    if any(s is MilestoneStatus.disputed for s in states):
        project.status = ProjectStatus.disputed
    elif states and all(s in TERMINAL for s in states):
        if any(s is MilestoneStatus.approved for s in states):
            project.status, project.completed_at = ProjectStatus.completed, project.completed_at or now()
        else:
            project.status, project.canceled_at = ProjectStatus.canceled, project.canceled_at or now()
    else:
        project.status = ProjectStatus.active


def start_funding(db: Session, provider: PaymentProvider, milestone: Milestone, project: Project, client: User) -> Order:
    # One payments switch for the whole platform (license sales and bookings).
    if not get_settings().feature_paid_licensing:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Payments are not enabled yet")
    if project.status not in (ProjectStatus.active,):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Project is {project.status.value}")
    if milestone.status is not MilestoneStatus.unfunded:
        raise HTTPException(status.HTTP_409_CONFLICT, "This milestone is already funded")
    pending = db.scalar(select(Order).where(Order.milestone_id == milestone.id, Order.status == OrderStatus.pending))
    if pending:
        return pending
    attempt = db.scalar(select(func.count(Order.id)).where(Order.milestone_id == milestone.id)) or 0
    order = Order(buyer_user_id=client.id, currency=project.currency, subtotal_cents=milestone.amount_cents,
                  tax_cents=0, total_cents=milestone.amount_cents, idempotency_key=f"milestone:{milestone.id}:{attempt}",
                  provider=provider.name, purpose=OrderPurpose.milestone, milestone_id=milestone.id, lines=[])
    db.add(order)
    db.flush()
    web = get_settings().public_web_url
    session = provider.create_checkout(
        order_id=str(order.id), currency=order.currency,
        items=[CheckoutItem(f"{project.title}: {milestone.title}", "Custom production milestone",
                            milestone.amount_cents, tax_code="txcd_20030000")],
        customer_email=client.email, success_url=f"{web}/projects/{project.id}?funded={milestone.id}",
        cancel_url=f"{web}/projects/{project.id}", idempotency_key=f"checkout:{order.id}",
    )
    order.provider_session_id, order.checkout_url = session.id, session.url
    audit.record(db, "production.funding_started", client.id, "milestone", milestone.id, order=order.id)
    return order


def fund_from_payment(db: Session, order: Order, payment: PaymentDetails) -> None:
    """Webhook: the client's milestone payment succeeded. Idempotent."""
    if order.status is not OrderStatus.pending or not payment.paid:
        return
    expected = order.subtotal_cents + payment.amount_tax_cents
    if payment.currency.upper() != order.currency or payment.amount_total_cents != expected:
        raise ValueError(f"payment mismatch for milestone order {order.id}")
    m = db.get(Milestone, order.milestone_id)
    if m.status is not MilestoneStatus.unfunded:
        # Paid twice (e.g. two open checkout tabs). Surfaced to finance as a failed
        # event; refund the duplicate payment in the provider dashboard.
        raise ValueError(f"milestone {m.id} is already funded; refund duplicate order {order.id}")
    order.status, order.paid_at = OrderStatus.paid, now()
    order.tax_cents, order.total_cents = payment.amount_tax_cents, payment.amount_total_cents
    order.processing_fee_cents, order.provider_payment_id = payment.fee_cents, payment.payment_id
    ledger.post(db, JournalKind.service_funding, f"milestone-funding:{order.id}", "order", order.id,
                f"Milestone funded {m.id}", order.currency, [
                    ledger.dr(f"clearing:{order.provider}", order.total_cents - order.processing_fee_cents),
                    ledger.dr("processing_fees", order.processing_fee_cents),
                    ledger.cr("tax_payable", order.tax_cents),
                    ledger.cr("client_funds_held", m.amount_cents, f"milestone {m.id}"),
                ])
    m.status, m.funded_at, m.tax_cents = MilestoneStatus.funded, now(), order.tax_cents
    project = m.project
    notify(db, _creator_user(db, project), "milestone_funded", f"Milestone funded: {m.title}",
           "Funds are held until the client approves your delivery.", f"/projects/{project.id}", send_email=True)
    audit.record(db, "production.milestone_funded", order.buyer_user_id, "milestone", m.id, order=order.id)


def submit_milestone(db: Session, m: Milestone, project: Project, note: str) -> None:
    from app.models import Deliverable

    if m.status not in (MilestoneStatus.funded, MilestoneStatus.revision_requested):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only funded milestones can be delivered")
    if not db.scalar(select(Deliverable.id).where(Deliverable.milestone_id == m.id)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload at least one deliverable first")
    m.status, m.submitted_at = MilestoneStatus.submitted, now()
    m.auto_approve_at = now() + timedelta(days=get_settings().milestone_auto_approve_days)
    conv = messaging.get_or_create(db, ConversationKind.project, project.id, project.client_user_id,
                                   _creator_user(db, project), f"Project: {project.title}")
    messaging.post(db, conv, None, f"Delivered “{m.title}”. {note}".strip(), system=True)
    notify(db, project.client_user_id, "milestone_submitted", f"Delivery ready for review: {m.title}",
           f"Approve it or request a revision within {get_settings().milestone_auto_approve_days} days; "
           "otherwise it is approved automatically.", f"/projects/{project.id}", send_email=True)


def request_revision(db: Session, m: Milestone, project: Project, user: User, note: str) -> None:
    from app.models import RevisionRequest

    if m.status is not MilestoneStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only delivered milestones can be sent back")
    if m.revisions_used >= project.revisions_included:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "All included revisions are used. Add a paid milestone or open a dispute.")
    m.revisions_used += 1
    m.status, m.auto_approve_at = MilestoneStatus.revision_requested, None
    db.add(RevisionRequest(milestone_id=m.id, requested_by=user.id, note=note))
    notify(db, _creator_user(db, project), "revision_requested", f"Revision requested: {m.title}", note[:300],
           f"/projects/{project.id}", send_email=True)


def release(db: Session, m: Milestone, project: Project, amount: int, actor_id=None, reason: str = "approved") -> None:
    """Move ``amount`` of a held milestone to the creator (less commission)."""
    if amount <= 0:
        return
    rule = db.get(RevenueShareRule, project.commission_rule_id)
    result = engine.calculate(engine.RoyaltyInput(gross_cents=amount, rule=share_rule(rule),
                                                  creator_party_id="creator", currency=project.currency))
    creator_user = _creator_user(db, project)
    journal = ledger.post(db, JournalKind.service_release, f"milestone-release:{m.id}", "milestone", m.id,
                          f"Milestone released ({reason})", project.currency, [
                              ledger.dr("client_funds_held", amount, f"milestone {m.id}"),
                              ledger.cr(ledger.creator_payable(creator_user), result.creator_pool_cents,
                                        f"milestone {m.id}", creator_user),
                              ledger.cr("platform_revenue", result.platform_net_cents, f"milestone {m.id}"),
                          ], created_by=actor_id)
    if result.creator_pool_cents:
        db.add(Earning(payee_user_id=creator_user, kind=EarningKind.service_milestone, milestone_id=m.id,
                       amount_cents=result.creator_pool_cents, currency=project.currency,
                       status=EarningStatus.pending,
                       available_at=now() + timedelta(days=get_settings().earnings_hold_days), journal_id=journal.id))
    m.released_cents += amount


def refund_held(db: Session, provider: PaymentProvider | None, m: Milestone, project: Project, amount: int,
                reason: RefundReason, note: str, actor_id=None) -> None:
    """Return ``amount`` of a held milestone (plus its share of tax) to the client."""
    if amount <= 0:
        return
    order = db.scalar(select(Order).where(Order.milestone_id == m.id, Order.status.in_(
        [OrderStatus.paid, OrderStatus.partially_refunded])))
    tax = (m.tax_cents * amount) // m.amount_cents if m.amount_cents else 0
    refund_id = None
    if provider is not None:
        refund_id = provider.refund(payment_id=order.provider_payment_id, amount_cents=amount + tax,
                                    idempotency_key=f"milestone-refund:{m.id}",
                                    metadata={"milestone_id": str(m.id), "order_id": str(order.id)})
    journal = ledger.post(db, JournalKind.service_refund, f"milestone-refund:{m.id}", "milestone", m.id,
                          f"Milestone refund ({reason.value})", project.currency, [
                              ledger.dr("client_funds_held", amount, f"milestone {m.id}"),
                              ledger.dr("tax_payable", tax, f"milestone {m.id}"),
                              ledger.cr(f"clearing:{order.provider}", amount + tax, f"milestone {m.id}"),
                          ], created_by=actor_id)
    db.add(Refund(order_id=order.id, order_line_id=None, milestone_id=m.id, amount_cents=amount + tax,
                  currency=project.currency, reason=reason, note=note, provider_refund_id=refund_id,
                  journal_id=journal.id, initiated_by=actor_id))
    order.status = OrderStatus.refunded if amount == m.amount_cents else OrderStatus.partially_refunded
    m.refunded_cents += amount


def approve(db: Session, m: Milestone, project: Project, actor_id=None, auto: bool = False) -> None:
    if m.status is not MilestoneStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only delivered milestones can be approved")
    release(db, m, project, m.amount_cents, actor_id, "auto-approved" if auto else "approved")
    m.status, m.approved_at, m.auto_approve_at = MilestoneStatus.approved, now(), None
    refresh_project_status(project)
    notify(db, _creator_user(db, project), "milestone_approved", f"Milestone approved: {m.title}",
           "Your earnings are pending and will be paid out after the hold period.", "/dashboard?tab=earnings",
           send_email=True)
    audit.record(db, "production.milestone_approved", actor_id, "milestone", m.id, auto=auto)


def creator_refund(db: Session, provider: PaymentProvider, m: Milestone, project: Project, user: User, note: str):
    if m.status not in (MilestoneStatus.funded, MilestoneStatus.submitted, MilestoneStatus.revision_requested):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only held milestones can be refunded")
    refund_held(db, provider, m, project, m.amount_cents, RefundReason.project_canceled, note, user.id)
    m.status, m.auto_approve_at = MilestoneStatus.refunded, None
    refresh_project_status(project)
    notify(db, project.client_user_id, "milestone_refunded", f"Refund issued: {m.title}", note[:300],
           f"/projects/{project.id}", send_email=True)


def cancel_project(db: Session, project: Project, user: User) -> None:
    if any(m.status in HELD for m in project.milestones):
        raise HTTPException(status.HTTP_409_CONFLICT, "A milestone holds funds. The creator can refund it, "
                                                      "or either side can open a dispute.")
    if project.status is not ProjectStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Project is {project.status.value}")
    for m in project.milestones:
        if m.status is MilestoneStatus.unfunded:
            m.status = MilestoneStatus.canceled
    refresh_project_status(project)
    other = _creator_user(db, project) if user.id == project.client_user_id else project.client_user_id
    notify(db, other, "project_canceled", f"Project canceled: {project.title}", link=f"/projects/{project.id}")


def open_dispute(db: Session, m: Milestone, project: Project, user: User, reason: str, description: str):
    if m.status not in (MilestoneStatus.funded, MilestoneStatus.submitted, MilestoneStatus.revision_requested):
        raise HTTPException(status.HTTP_409_CONFLICT, "Disputes can be opened on milestones that hold funds")
    dispute = ProjectDispute(project_id=project.id, milestone_id=m.id, opened_by=user.id, reason=reason,
                             description=description, previous_status=m.status.value)
    db.add(dispute)
    m.status, m.auto_approve_at = MilestoneStatus.disputed, None
    refresh_project_status(project)
    other = _creator_user(db, project) if user.id == project.client_user_id else project.client_user_id
    notify(db, other, "dispute_opened", f"Dispute opened on {m.title}", description[:300],
           f"/projects/{project.id}", send_email=True)
    audit.record(db, "production.dispute_opened", user.id, "milestone", m.id, reason=reason)
    return dispute


def withdraw_dispute(db: Session, dispute: ProjectDispute, user: User) -> None:
    if dispute.status is not DisputeStatus.open or dispute.opened_by != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only the person who opened an open dispute can withdraw it")
    m = db.get(Milestone, dispute.milestone_id)
    m.status = MilestoneStatus(dispute.previous_status)
    if m.status is MilestoneStatus.submitted:
        m.auto_approve_at = now() + timedelta(days=get_settings().milestone_auto_approve_days)
    dispute.status, dispute.resolved_at = DisputeStatus.withdrawn, now()
    refresh_project_status(m.project)


def resolve_dispute(db: Session, provider: PaymentProvider, dispute: ProjectDispute, admin: User, outcome: str,
                    creator_share_bps: int | None, note: str) -> None:
    if dispute.status is not DisputeStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dispute is already closed")
    m = db.get(Milestone, dispute.milestone_id)
    project = m.project
    if outcome == "release":
        to_creator = m.amount_cents
    elif outcome == "refund":
        to_creator = 0
    elif outcome == "split":
        if creator_share_bps is None or not 0 < creator_share_bps < 10_000:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A split needs a creator share between 1 and 9999 bps")
        to_creator = (m.amount_cents * creator_share_bps + 5_000) // 10_000
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Outcome must be release, refund or split")
    release(db, m, project, to_creator, admin.id, "dispute resolution")
    refund_held(db, provider, m, project, m.amount_cents - to_creator, RefundReason.dispute_resolution, note, admin.id)
    m.status = MilestoneStatus.approved if to_creator else MilestoneStatus.refunded
    m.approved_at = now() if to_creator else None
    dispute.status = {"release": DisputeStatus.resolved_release, "refund": DisputeStatus.resolved_refund,
                      "split": DisputeStatus.resolved_split}[outcome]
    dispute.creator_share_bps = creator_share_bps if outcome == "split" else (10_000 if to_creator else 0)
    dispute.resolution_note, dispute.resolved_by, dispute.resolved_at = note, admin.id, now()
    refresh_project_status(project)
    for uid in (project.client_user_id, _creator_user(db, project)):
        notify(db, uid, "dispute_resolved", f"Dispute resolved: {m.title}", note[:300], f"/projects/{project.id}",
               send_email=True)
    audit.record(db, "production.dispute_resolved", admin.id, "project_dispute", dispute.id, outcome=outcome,
                 to_creator=to_creator)


def auto_approve_due(db: Session) -> int:
    due = db.scalars(select(Milestone).where(Milestone.status == MilestoneStatus.submitted,
                                             Milestone.auto_approve_at <= now())).all()
    for m in due:
        approve(db, m, m.project, None, auto=True)
    return len(due)


def chargeback_milestone(db: Session, order: Order, dispute_id: str) -> None:
    """A card chargeback on a milestone payment: pull back held or released funds."""
    m = db.get(Milestone, order.milestone_id)
    project = m.project
    held = m.amount_cents - m.released_cents - m.refunded_cents
    entries = []
    if held > 0:
        entries.append(ledger.dr("client_funds_held", held, f"milestone {m.id}"))
    if m.released_cents:
        alloc = engine.calculate(engine.RoyaltyInput(
            gross_cents=m.released_cents, rule=share_rule(db.get(RevenueShareRule, project.commission_rule_id)),
            creator_party_id="creator"))
        creator_user = _creator_user(db, project)
        entries += [ledger.dr(ledger.creator_payable(creator_user), alloc.creator_pool_cents, f"milestone {m.id}",
                              creator_user),
                    ledger.dr("platform_revenue", alloc.platform_net_cents, f"milestone {m.id}")]
    returned = held + m.released_cents
    tax = (m.tax_cents * returned) // m.amount_cents if m.amount_cents else 0
    entries += [ledger.dr("tax_payable", tax), ledger.cr(f"clearing:{order.provider}", returned + tax, dispute_id)]
    journal = ledger.post(db, JournalKind.dispute, f"dispute:{dispute_id}:{m.id}", "milestone", m.id,
                          f"Chargeback {dispute_id}", order.currency, entries)
    from app.services.payment_service import reverse_earning_rows

    reverse_earning_rows(db, list(db.scalars(select(Earning).where(Earning.milestone_id == m.id,
                                                                   Earning.amount_cents > 0))), journal.id)
    m.status, m.auto_approve_at = MilestoneStatus.refunded, None
    m.refunded_cents += held
    order.status = OrderStatus.disputed
    refresh_project_status(project)
    notify(db, _creator_user(db, project), "chargeback", f"Payment disputed by the bank: {m.title}",
           "The client's bank reversed this payment. Contact support if you have evidence of delivery.",
           f"/projects/{project.id}", send_email=True)


# --- Reviews ---------------------------------------------------------------------------------

def leave_review(db: Session, project: Project, role: str, user: User, rating: int, body: str) -> Review:
    if project.status is not ProjectStatus.completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reviews open once the project is completed")
    if role not in ("client", "creator"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only project participants can review")
    direction = ReviewDirection.client_to_creator if role == "client" else ReviewDirection.creator_to_client
    if db.scalar(select(Review.id).where(Review.project_id == project.id, Review.direction == direction)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already reviewed this project")
    review = Review(project_id=project.id, direction=direction, reviewer_id=user.id, creator_id=project.creator_id,
                    rating=rating, body=body)
    db.add(review)
    other = _creator_user(db, project) if role == "client" else project.client_user_id
    notify(db, other, "review_received", f"New {rating}★ review on {project.title}", body[:200],
           f"/projects/{project.id}")
    return review


def creator_rating(db: Session, creator_id: uuid.UUID) -> dict:
    avg, count = db.execute(select(func.avg(Review.rating), func.count(Review.id)).where(
        Review.creator_id == creator_id, Review.direction == ReviewDirection.client_to_creator,
        Review.is_hidden.is_(False))).one()
    completed = db.scalar(select(func.count(Project.id)).where(Project.creator_id == creator_id,
                                                               Project.status == ProjectStatus.completed)) or 0
    return {"average": round(float(avg), 2) if avg else 0.0, "count": count or 0, "completed_projects": completed}

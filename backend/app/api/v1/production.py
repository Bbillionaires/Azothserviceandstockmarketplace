"""Custom production: requests (incl. Request This Shot), proposals, packages,
projects, milestones, deliverables, disputes and reviews."""

import hashlib
import mimetypes
import re
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import current_user, optional_user, require_roles, verified_user
from app.core.rate_limit import client_ip, limiter
from app.core.security import sign_download, verify_download
from app.models import (
    SERVICE_CATEGORIES,
    Conversation,
    ConversationKind,
    CreatorProfile,
    Deliverable,
    DisputeStatus,
    Milestone,
    MilestoneStatus,
    Project,
    ProjectDispute,
    ProjectRequest,
    ProjectStatus,
    Proposal,
    ProposalStatus,
    RequestInvitation,
    RequestStatus,
    RequestVisibility,
    RevenueShareRule,
    Review,
    ReviewDirection,
    RevisionRequest,
    RoleCode,
    ScanStatus,
    ServicePackage,
    User,
)
from app.schemas.common import Message
from app.schemas.production import (
    AddMilestoneIn,
    BookIn,
    DisputeIn,
    InviteIn,
    NoteIn,
    PackageIn,
    ProposalIn,
    RequestIn,
    ResolveIn,
    ReviewIn,
    RevisionIn,
)
from app.services import audit
from app.services import production_service as svc
from app.services.payments import PaymentProviderError, get_provider
from app.services.scanner import scan_file
from app.services.storage import get_storage

router = APIRouter(tags=["production"])
staff = require_roles(RoleCode.moderator, RoleCode.finance_admin)


def _creator_summary(c: CreatorProfile) -> dict:
    return {"id": c.id, "handle": c.handle, "display_name": c.display_name, "avatar_url": c.avatar_url,
            "verification_status": c.verification_status.value, "city": c.city, "country_code": c.country_code}


def request_out(db: Session, r: ProjectRequest, user: User | None = None, detail: bool = False) -> dict:
    out = {
        "id": r.id, "kind": r.kind.value, "title": r.title, "category": r.category,
        "description": r.description if detail else r.description[:280],
        "location_city": r.location_city, "location_region": r.location_region,
        "location_country": r.location_country, "remote_ok": r.remote_ok, "budget_min_cents": r.budget_min_cents,
        "budget_max_cents": r.budget_max_cents, "currency": r.currency, "deadline": r.deadline,
        "rights_preference": r.rights_preference.value, "visibility": r.visibility.value, "status": r.status.value,
        "proposal_count": r.proposal_count, "created_at": r.created_at,
    }
    if detail:
        client = db.get(User, r.client_user_id)
        out |= {"deliverables": r.deliverables, "reference_urls": r.reference_urls,
                "client_name": client.display_name, "is_owner": bool(user and user.id == r.client_user_id)}
        if user:
            creator = svc.creator_of(db, user)
            mine = db.scalar(select(Proposal).where(Proposal.request_id == r.id, Proposal.creator_id == creator.id)) \
                if creator else None
            out["my_proposal"] = proposal_out(db, mine) if mine else None
            out["is_invited"] = bool(creator and db.scalar(select(RequestInvitation.id).where(
                RequestInvitation.request_id == r.id, RequestInvitation.creator_id == creator.id)))
            out["has_storefront"] = creator is not None
            project = db.scalar(select(Project.id).where(Project.request_id == r.id))
            out["project_id"] = project if project and (out["is_owner"] or mine) else None
    return out


def proposal_out(db: Session, p: Proposal) -> dict:
    c = db.get(CreatorProfile, p.creator_id)
    return {"id": p.id, "request_id": p.request_id, "creator": _creator_summary(c), "cover_letter": p.cover_letter,
            "total_cents": p.total_cents, "currency": p.currency, "milestones": p.milestones,
            "delivery_days": p.delivery_days, "revisions_included": p.revisions_included,
            "rights_type": p.rights_type.value, "rights_terms": p.rights_terms, "status": p.status.value,
            "updated_at": p.updated_at, "rating": svc.creator_rating(db, c.id)}


def package_out(p: ServicePackage) -> dict:
    return {"id": p.id, "creator_id": p.creator_id, "title": p.title, "description": p.description,
            "category": p.category, "deliverables": p.deliverables, "price_cents": p.price_cents,
            "currency": p.currency, "delivery_days": p.delivery_days, "revisions_included": p.revisions_included,
            "rights_type": p.rights_type.value, "rights_terms": p.rights_terms, "is_active": p.is_active}


@router.get("/service-categories")
def service_categories():
    return SERVICE_CATEGORIES


# --- Requests ----------------------------------------------------------------------------

@router.post("/requests", status_code=201)
def create_request(body: RequestIn, request: Request, user: User = Depends(verified_user),
                   db: Session = Depends(get_db)):
    limiter.check(f"request-create:{user.id}", 20, 3600)
    r = ProjectRequest(client_user_id=user.id, **body.model_dump())
    r.currency = r.currency.upper()
    db.add(r)
    db.flush()
    audit.record(db, "production.request_created", user.id, "project_request", r.id, client_ip(request),
                 kind=r.kind.value)
    db.commit()
    return request_out(db, r, user, detail=True)


@router.get("/requests")
def discover_requests(
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None, pattern="^(custom_project|shot_request)$"),
    category: str | None = None,
    city: str | None = Query(None, max_length=120),
    country: str | None = Query(None, min_length=2, max_length=2),
    remote: bool | None = None,
    min_budget: int | None = Query(None, ge=0, description="cents"),
    deadline_before: date | None = None,
    sort: str = Query("newest", pattern="^(newest|deadline|budget)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Open, public requests: the board creators browse (incl. Request This Shot)."""
    stmt = select(ProjectRequest).where(ProjectRequest.status == RequestStatus.open,
                                        ProjectRequest.visibility == RequestVisibility.public)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(ProjectRequest.title).like(like),
                              func.lower(ProjectRequest.description).like(like)))
    if kind:
        stmt = stmt.where(ProjectRequest.kind == kind)
    if category:
        stmt = stmt.where(ProjectRequest.category == category)
    if city:
        stmt = stmt.where(func.lower(ProjectRequest.location_city) == city.lower())
    if country:
        stmt = stmt.where(ProjectRequest.location_country == country.upper())
    if remote is not None:
        stmt = stmt.where(ProjectRequest.remote_ok.is_(remote))
    if min_budget is not None:
        stmt = stmt.where(func.coalesce(ProjectRequest.budget_max_cents, ProjectRequest.budget_min_cents, 0) >= min_budget)
    if deadline_before:
        stmt = stmt.where(ProjectRequest.deadline <= deadline_before)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = {
        "newest": ProjectRequest.created_at.desc(),
        "deadline": ProjectRequest.deadline.asc(),
        "budget": func.coalesce(ProjectRequest.budget_max_cents, ProjectRequest.budget_min_cents, 0).desc(),
    }[sort]
    rows = db.scalars(stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [request_out(db, r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/requests/mine")
def my_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ProjectRequest).where(ProjectRequest.client_user_id == user.id)
                      .order_by(ProjectRequest.created_at.desc()).limit(200))
    return [request_out(db, r) for r in rows]


@router.get("/requests/invitations")
def my_invitations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    creator = svc.creator_of(db, user)
    if not creator:
        return []
    rows = db.scalars(select(ProjectRequest).join(RequestInvitation, RequestInvitation.request_id == ProjectRequest.id)
                      .where(RequestInvitation.creator_id == creator.id).order_by(ProjectRequest.created_at.desc()))
    return [request_out(db, r) for r in rows]


def _load_request(db: Session, request_id: uuid.UUID, user: User | None) -> ProjectRequest:
    r = db.get(ProjectRequest, request_id)
    if not r or not svc.can_view_request(db, r, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return r


@router.get("/requests/{request_id}")
def get_request(request_id: uuid.UUID, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    return request_out(db, _load_request(db, request_id, user), user, detail=True)


@router.post("/requests/{request_id}/close", response_model=Message)
def close_request(request_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(ProjectRequest, request_id)
    if not r or r.client_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if r.status is not RequestStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "Request is not open")
    r.status = RequestStatus.closed
    for p in db.scalars(select(Proposal).where(Proposal.request_id == r.id, Proposal.status == ProposalStatus.submitted)):
        p.status = ProposalStatus.declined
    db.commit()
    return Message(detail="Request closed")


@router.post("/requests/{request_id}/invite", response_model=Message)
def invite_creator(request_id: uuid.UUID, body: InviteIn, user: User = Depends(verified_user),
                   db: Session = Depends(get_db)):
    limiter.check(f"invite:{user.id}", 50, 3600)
    r = db.get(ProjectRequest, request_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    creator = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == body.creator_handle.lower()))
    if not creator:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    svc.invite(db, r, user, creator, body.message)
    db.commit()
    return Message(detail=f"Invited {creator.display_name}")


@router.get("/requests/{request_id}/matches")
def request_matches(request_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(ProjectRequest, request_id)
    if not r or r.client_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return [{"creator": _creator_summary(m["creator"]) | {"headline": m["creator"].headline,
                                                          "categories": m["creator"].categories},
             "score": m["score"], "reasons": m["reasons"],
             "rating": svc.creator_rating(db, m["creator"].id)} for m in svc.match_creators(db, r)]


@router.get("/requests/{request_id}/proposals")
def list_proposals(request_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _load_request(db, request_id, user)
    stmt = select(Proposal).where(Proposal.request_id == r.id).order_by(Proposal.created_at)
    if r.client_user_id != user.id:
        creator = svc.creator_of(db, user)  # bidders only ever see their own proposal
        stmt = stmt.where(Proposal.creator_id == (creator.id if creator else None))
    else:
        stmt = stmt.where(Proposal.status != ProposalStatus.withdrawn)
    return [proposal_out(db, p) for p in db.scalars(stmt)]


@router.post("/requests/{request_id}/proposals", status_code=201)
def submit_proposal(request_id: uuid.UUID, body: ProposalIn, user: User = Depends(verified_user),
                    db: Session = Depends(get_db)):
    limiter.check(f"proposal:{user.id}", 30, 3600)
    r = _load_request(db, request_id, user)
    data = body.model_dump()
    p = svc.submit_proposal(db, r, user, data)
    db.commit()
    return proposal_out(db, p)


def _own_proposal(db: Session, proposal_id: uuid.UUID, user: User) -> Proposal:
    p = db.get(Proposal, proposal_id)
    creator = svc.creator_of(db, user)
    if not p or not creator or p.creator_id != creator.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return p


@router.post("/proposals/{proposal_id}/withdraw", response_model=Message)
def withdraw_proposal(proposal_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _own_proposal(db, proposal_id, user)
    if p.status is not ProposalStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted proposals can be withdrawn")
    p.status = ProposalStatus.withdrawn
    db.commit()
    return Message(detail="Proposal withdrawn")


def _client_proposal(db: Session, proposal_id: uuid.UUID, user: User) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if not p or db.get(ProjectRequest, p.request_id).client_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return p


@router.post("/proposals/{proposal_id}/decline", response_model=Message)
def decline_proposal(proposal_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _client_proposal(db, proposal_id, user)
    if p.status is not ProposalStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Proposal is not open")
    p.status = ProposalStatus.declined
    db.commit()
    return Message(detail="Proposal declined")


@router.post("/proposals/{proposal_id}/accept", status_code=201)
def accept_proposal(proposal_id: uuid.UUID, request: Request, user: User = Depends(verified_user),
                    db: Session = Depends(get_db)):
    p = _client_proposal(db, proposal_id, user)
    project = svc.accept_proposal(db, p, user, client_ip(request), request.headers.get("user-agent"))
    db.commit()
    return {"project_id": project.id}


# --- Packages -------------------------------------------------------------------------------

@router.get("/creators/{handle}/packages")
def creator_packages(handle: str, db: Session = Depends(get_db)):
    c = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == handle.lower()))
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    rows = db.scalars(select(ServicePackage).where(ServicePackage.creator_id == c.id, ServicePackage.is_active)
                      .order_by(ServicePackage.price_cents))
    return [package_out(p) for p in rows]


@router.get("/creators/{handle}/reputation")
def creator_reputation(handle: str, db: Session = Depends(get_db)):
    c = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == handle.lower()))
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    reviews = db.execute(select(Review, Project, User).join(Project, Project.id == Review.project_id)
                         .join(User, User.id == Review.reviewer_id)
                         .where(Review.creator_id == c.id, Review.direction == ReviewDirection.client_to_creator,
                                Review.is_hidden.is_(False)).order_by(Review.created_at.desc()).limit(20)).all()
    return svc.creator_rating(db, c.id) | {"reviews": [
        {"id": r.id, "rating": r.rating, "body": r.body, "created_at": r.created_at, "project_title": p.title,
         "reviewer_name": u.display_name, "verified": True} for r, p, u in reviews]}


def _my_creator(db: Session, user: User) -> CreatorProfile:
    c = svc.creator_of(db, user)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create your storefront first")
    return c


@router.get("/packages/mine")
def my_packages(user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _my_creator(db, user)
    return [package_out(p) for p in db.scalars(select(ServicePackage).where(ServicePackage.creator_id == c.id)
                                               .order_by(ServicePackage.created_at))]


@router.post("/packages", status_code=201)
def create_package(body: PackageIn, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    c = _my_creator(db, user)
    if db.scalar(select(func.count(ServicePackage.id)).where(ServicePackage.creator_id == c.id)) >= 30:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Package limit reached")
    p = ServicePackage(creator_id=c.id, **body.model_dump())
    p.currency = p.currency.upper()
    db.add(p)
    db.commit()
    return package_out(p)


@router.put("/packages/{package_id}")
def update_package(package_id: uuid.UUID, body: PackageIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    c = _my_creator(db, user)
    p = db.get(ServicePackage, package_id)
    if not p or p.creator_id != c.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()  # existing bookings keep the snapshot taken at booking time
    return package_out(p)


@router.post("/packages/{package_id}/book", status_code=201)
def book_package(package_id: uuid.UUID, body: BookIn, request: Request, user: User = Depends(verified_user),
                 db: Session = Depends(get_db)):
    if not body.accept_terms:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Accept the package terms to book")
    limiter.check(f"book:{user.id}", 20, 3600)
    p = db.get(ServicePackage, package_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found")
    project = svc.book_package(db, p, user, body.brief, client_ip(request), request.headers.get("user-agent"))
    db.commit()
    return {"project_id": project.id}


# --- Projects ---------------------------------------------------------------------------------

def project_out(db: Session, project: Project, role: str) -> dict:
    creator = db.get(CreatorProfile, project.creator_id)
    client = db.get(User, project.client_user_id)
    rule = db.get(RevenueShareRule, project.commission_rule_id)
    milestones = []
    for m in project.milestones:
        deliverables = db.scalars(select(Deliverable).where(Deliverable.milestone_id == m.id)
                                  .order_by(Deliverable.created_at)).all()
        revisions = db.scalars(select(RevisionRequest).where(RevisionRequest.milestone_id == m.id)
                               .order_by(RevisionRequest.created_at)).all()
        milestones.append({
            "id": m.id, "position": m.position, "title": m.title, "description": m.description,
            "amount_cents": m.amount_cents, "due_date": m.due_date, "status": m.status.value,
            "funded_at": m.funded_at, "submitted_at": m.submitted_at, "auto_approve_at": m.auto_approve_at,
            "approved_at": m.approved_at, "revisions_used": m.revisions_used, "released_cents": m.released_cents,
            "refunded_cents": m.refunded_cents + m.reversed_release_cents,
            "deliverables": [{"id": d.id, "filename": d.filename, "size_bytes": d.size_bytes,
                              "content_type": d.content_type, "note": d.note, "created_at": d.created_at,
                              "scan_status": d.scan_status}
                             for d in deliverables],
            "revision_requests": [{"note": r.note, "created_at": r.created_at} for r in revisions],
        })
    disputes = db.scalars(select(ProjectDispute).where(ProjectDispute.project_id == project.id)
                          .order_by(ProjectDispute.created_at)).all()
    reviews = db.scalars(select(Review).where(Review.project_id == project.id)).all()
    conv = db.scalar(select(Conversation.id).where(Conversation.kind == ConversationKind.project,
                                                   Conversation.subject_id == project.id))
    return {
        "id": project.id, "title": project.title, "description": project.description, "status": project.status.value,
        "currency": project.currency, "total_cents": project.total_cents,
        "revisions_included": project.revisions_included, "rights_type": project.rights_type.value,
        "rights_terms": project.rights_terms, "acceptance_evidence": project.acceptance_evidence,
        "commission_percent": (10_000 - rule.creator_bps) / 100, "role": role,
        "creator": _creator_summary(creator), "client_name": client.display_name,
        "request_id": project.request_id, "package_id": project.package_id, "conversation_id": conv,
        "created_at": project.created_at, "completed_at": project.completed_at, "milestones": milestones,
        "disputes": [{"id": d.id, "milestone_id": d.milestone_id, "reason": d.reason, "description": d.description,
                      "status": d.status.value, "opened_by_me": False, "resolution_note": d.resolution_note,
                      "created_at": d.created_at} for d in disputes],
        "reviews": [{"direction": r.direction.value, "rating": r.rating, "body": r.body, "created_at": r.created_at}
                    for r in reviews if not r.is_hidden],
        "auto_approve_days": get_settings().milestone_auto_approve_days,
    }


@router.get("/projects/mine")
def my_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    creator = svc.creator_of(db, user)
    stmt = select(Project).where(or_(Project.client_user_id == user.id,
                                     Project.creator_id == (creator.id if creator else None)))
    out = []
    for p in db.scalars(stmt.order_by(Project.updated_at.desc()).limit(200)):
        role = "client" if p.client_user_id == user.id else "creator"
        c = db.get(CreatorProfile, p.creator_id)
        next_m = next((m for m in p.milestones if m.status not in svc.TERMINAL), None)
        out.append({"id": p.id, "title": p.title, "status": p.status.value, "role": role,
                    "total_cents": p.total_cents, "currency": p.currency, "creator_name": c.display_name,
                    "client_name": db.get(User, p.client_user_id).display_name,
                    "next_milestone": {"title": next_m.title, "status": next_m.status.value} if next_m else None,
                    "updated_at": p.updated_at})
    return out


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project, role = svc.load_project(db, project_id, user)
    out = project_out(db, project, role)
    for d in out["disputes"]:
        d["opened_by_me"] = db.get(ProjectDispute, d["id"]).opened_by == user.id
    return out


@router.post("/projects/{project_id}/milestones", status_code=201)
def add_milestone(project_id: uuid.UUID, body: AddMilestoneIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    project, _ = svc.load_project(db, project_id, user, "client")
    if project.status is not ProjectStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Project is {project.status.value}")
    m = Milestone(project_id=project.id, position=len(project.milestones), title=body.title,
                  description=body.description, amount_cents=body.amount_cents,
                  due_date=date.today() + timedelta(days=body.due_in_days) if body.due_in_days else None)
    project.milestones.append(m)
    project.total_cents += body.amount_cents
    db.commit()
    return {"id": m.id}


@router.post("/milestones/{milestone_id}/fund")
def fund_milestone(milestone_id: uuid.UUID, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "client")
    try:
        order = svc.start_funding(db, get_provider(), m, project, user)
    except PaymentProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Payment provider error: {exc}") from None
    db.commit()
    return {"order_id": order.id, "checkout_url": order.checkout_url}


SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


@router.post("/milestones/{milestone_id}/deliverables", status_code=201)
async def upload_deliverable(milestone_id: uuid.UUID, file: UploadFile = File(...), note: str = Form("", max_length=2000),
                             user: User = Depends(verified_user), db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "creator")
    if m.status not in (MilestoneStatus.funded, MilestoneStatus.revision_requested):
        raise HTTPException(status.HTTP_409_CONFLICT, "Deliver files once the milestone is funded")
    limiter.check(f"deliverable:{user.id}", 200, 3600)
    limit = get_settings().max_deliverable_mb * 1024 * 1024
    name = SAFE_NAME.sub("_", Path(file.filename or "file").name)[:200] or "file"
    with tempfile.TemporaryDirectory(prefix="deliv-") as tmp:
        path = Path(tmp) / "upload"
        digest, size = hashlib.sha256(), 0
        with path.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is too large")
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
        if scan_file(path) is ScanStatus.infected:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file failed the malware scan")
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        key = f"deliverables/{project.id}/{m.id}/{uuid.uuid4().hex}/{name}"
        get_storage().put_file(key, path, content_type, public=False)
    d = Deliverable(milestone_id=m.id, uploaded_by=user.id, filename=name, content_type=content_type,
                    size_bytes=size, storage_key=key, checksum_sha256=digest.hexdigest(), note=note)
    db.add(d)
    audit.record(db, "production.deliverable_uploaded", user.id, "milestone", m.id, filename=name, size=size)
    db.commit()
    return {"id": d.id, "filename": d.filename, "size_bytes": size}


@router.post("/deliverables/{deliverable_id}/link")
def deliverable_link(deliverable_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Deliverable, deliverable_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    m, project, role = svc.load_milestone(db, d.milestone_id, user)
    if d.scan_status == "pending":  # a direct upload whose scan job has not finished
        raise HTTPException(status.HTTP_409_CONFLICT, "This file is still being scanned; try again shortly")
    # Clients can preview deliveries before approving; files are watermark-free originals,
    # which is why funds are already held before the creator delivers.
    audit.record(db, "production.deliverable_link", user.id, "deliverable", d.id, role=role)
    db.commit()
    return {"url": f"{get_settings().api_prefix}/deliverables/download/{sign_download(d.id, 'deliverable')}"}


@router.get("/deliverables/download/{token}")
def deliverable_download(token: str, db: Session = Depends(get_db)):
    parsed = verify_download(token)
    if not parsed or parsed[1] != "deliverable":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Link is invalid or has expired")
    d = db.get(Deliverable, parsed[0])
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    storage = get_storage()
    presigned = storage.private_download_url(d.storage_key, d.filename, 300)
    if presigned:
        return RedirectResponse(presigned, status_code=302)
    return StreamingResponse(storage.open_private(d.storage_key), media_type=d.content_type,
                             headers={"Content-Disposition": f'attachment; filename="{d.filename}"',
                                      "Cache-Control": "private, no-store"})


@router.post("/milestones/{milestone_id}/submit", response_model=Message)
def submit_milestone(milestone_id: uuid.UUID, body: NoteIn, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "creator")
    svc.submit_milestone(db, m, project, body.note)
    db.commit()
    return Message(detail="Delivered. The client has been notified.")


@router.post("/milestones/{milestone_id}/revision", response_model=Message)
def request_revision(milestone_id: uuid.UUID, body: RevisionIn, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "client")
    svc.request_revision(db, m, project, user, body.note)
    db.commit()
    return Message(detail="Revision requested")


@router.post("/milestones/{milestone_id}/approve", response_model=Message)
def approve_milestone(milestone_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "client")
    svc.approve(db, m, project, user.id)
    db.commit()
    return Message(detail="Approved. Payment released to the creator.")


@router.post("/milestones/{milestone_id}/refund", response_model=Message)
def refund_milestone(milestone_id: uuid.UUID, body: NoteIn, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    m, project, _ = svc.load_milestone(db, milestone_id, user, "creator")
    try:
        svc.creator_refund(db, get_provider(), m, project, user, body.note)
    except PaymentProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Payment provider error: {exc}") from None
    db.commit()
    return Message(detail="Refund issued to the client")


@router.post("/projects/{project_id}/cancel", response_model=Message)
def cancel_project(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project, _ = svc.load_project(db, project_id, user, "client", "creator")
    svc.cancel_project(db, project, user)
    db.commit()
    return Message(detail="Project canceled")


@router.post("/projects/{project_id}/disputes", status_code=201)
def open_dispute(project_id: uuid.UUID, body: DisputeIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    project, _ = svc.load_project(db, project_id, user, "client", "creator")
    m = db.get(Milestone, body.milestone_id)
    if not m or m.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Milestone not found")
    d = svc.open_dispute(db, m, project, user, body.reason, body.description)
    db.commit()
    return {"id": d.id}


@router.post("/disputes/{dispute_id}/withdraw", response_model=Message)
def withdraw_dispute(dispute_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ProjectDispute, dispute_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispute not found")
    svc.withdraw_dispute(db, d, user)
    db.commit()
    return Message(detail="Dispute withdrawn")


@router.post("/projects/{project_id}/reviews", status_code=201)
def review_project(project_id: uuid.UUID, body: ReviewIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    project, role = svc.load_project(db, project_id, user, "client", "creator")
    r = svc.leave_review(db, project, role, user, body.rating, body.body)
    db.commit()
    return {"id": r.id}


# --- Admin ----------------------------------------------------------------------------------

@router.get("/admin/production/disputes")
def admin_disputes(status_filter: DisputeStatus | None = Query(DisputeStatus.open, alias="status"),
                   _: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(ProjectDispute).order_by(ProjectDispute.created_at)
    if status_filter:
        stmt = stmt.where(ProjectDispute.status == status_filter)
    out = []
    for d in db.scalars(stmt):
        m = db.get(Milestone, d.milestone_id)
        project = m.project
        out.append({"id": d.id, "project_id": project.id, "project_title": project.title, "milestone": m.title,
                    "amount_cents": m.amount_cents, "currency": project.currency, "reason": d.reason,
                    "description": d.description, "status": d.status.value,
                    "opened_by": "client" if d.opened_by == project.client_user_id else "creator",
                    "created_at": d.created_at, "resolution_note": d.resolution_note})
    return out


@router.post("/admin/production/disputes/{dispute_id}/resolve", response_model=Message)
def resolve_dispute(dispute_id: uuid.UUID, body: ResolveIn, user: User = Depends(staff),
                    db: Session = Depends(get_db)):
    d = db.get(ProjectDispute, dispute_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispute not found")
    try:
        svc.resolve_dispute(db, get_provider(), d, user, body.outcome, body.creator_share_bps, body.note)
    except PaymentProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Payment provider error: {exc}") from None
    db.commit()
    return Message(detail=f"Dispute {d.status.value}")


@router.post("/admin/production/reviews/{review_id}/hide", response_model=Message)
def hide_review(review_id: uuid.UUID, hidden: bool = True, user: User = Depends(require_roles(RoleCode.moderator)),
                db: Session = Depends(get_db)):
    r = db.get(Review, review_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    r.is_hidden = hidden
    audit.record(db, "moderation.review_hidden", user.id, "review", r.id, hidden=hidden)
    db.commit()
    return Message(detail="Updated")


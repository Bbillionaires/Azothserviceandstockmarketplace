"""Phase 3: requests, proposals, projects, milestone money, disputes,
reviews, packages, messaging and client galleries."""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update

from app.core.database import SessionLocal
from app.core.rate_limit import limiter
from app.models import Milestone, Notification, User
from app.services import email, ledger, payout_service
from app.services import payment_service as ps
from app.services import production_service as svc
from app.services.payments import ProviderEvent, get_provider
from app.services.payments.fake import fake_fee
from tests.conftest import CSRF, jpeg_bytes, make_role, new_client, register

M1, M2 = 60_000, 40_000  # milestone amounts (cents)


def login_as(email_addr, role):
    c = register(new_client(), email_addr)
    make_role(email_addr, role)
    c.post("/api/v1/auth/login", json={"email": email_addr, "password": "correct-horse-battery"})
    return c


def creator_client(email_addr, handle, categories=("drone_operator", "videographer"), city="Jacksonville"):
    c = register(new_client(), email_addr)
    r = c.post("/api/v1/creators", json={"handle": handle, "display_name": handle.replace("-", " ").title(),
                                         "categories": list(categories), "city": city, "country_code": "US",
                                         "remote_available": True})
    assert r.status_code == 201, r.text
    return c


def post_request(client, **extra):
    body = {"kind": "shot_request", "title": "Drone footage of the riverfront tower",
            "description": "4K aerial orbit of the riverfront tower at sunset for a launch video.",
            "category": "drone_services", "location_city": "Jacksonville", "location_country": "us",
            "budget_min_cents": 50_000, "budget_max_cents": 150_000,
            "deadline": (date.today() + timedelta(days=30)).isoformat(), "rights_preference": "exclusive"} | extra
    r = client.post("/api/v1/requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def proposal_body(**extra):
    return {"cover_letter": "FAA Part 107 certified, I have flown this area many times.", "total_cents": M1 + M2,
            "milestones": [{"title": "Shoot", "amount_cents": M1, "due_in_days": 7},
                           {"title": "Edit and color", "amount_cents": M2, "due_in_days": 14}],
            "delivery_days": 14, "revisions_included": 1, "rights_type": "exclusive",
            "rights_terms": "Client receives exclusive worldwide rights; creator may show it in their portfolio."} | extra


def booked_project():
    client = register(new_client(), "client@example.com")
    drone = creator_client("drone@example.com", "sky-cam")
    req = post_request(client)
    proposal = drone.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body()).json()
    project_id = client.post(f"/api/v1/proposals/{proposal['id']}/accept").json()["project_id"]
    return client, drone, project_id


def fund(client, milestone_id):
    r = client.post(f"/api/v1/milestones/{milestone_id}/fund")
    assert r.status_code == 200, r.text
    order_id = r.json()["order_id"]
    assert client.post(f"/api/v1/payments/dev/complete/{order_id}").json()["outcome"] == "milestone_funded"
    return order_id


def deliver(creator, milestone_id):
    r = creator.post(f"/api/v1/milestones/{milestone_id}/deliverables",
                     files={"file": ("final cut.mp4", b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000, "video/mp4")},
                     data={"note": "Master file"})
    assert r.status_code == 201, r.text
    assert creator.post(f"/api/v1/milestones/{milestone_id}/submit", json={"note": "Ready"}).status_code == 200


def reconcile_ok():
    with SessionLocal() as db:
        run = payout_service.reconcile(db)
        db.commit()
        assert run.status == "ok", run.findings


def uid(email_addr):
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == email_addr))


def test_request_this_shot_discovery_matching_and_confidential_bids():
    client = register(new_client(), "client@example.com")
    drone = creator_client("drone@example.com", "sky-cam")
    other = creator_client("other@example.com", "wedding-pro", categories=("photographer",), city="Miami")
    req = post_request(client)
    assert req["kind"] == "shot_request" and req["location_country"] == "US"

    board = new_client().get("/api/v1/requests", params={"kind": "shot_request", "city": "jacksonville"}).json()
    assert board["total"] == 1 and board["items"][0]["id"] == req["id"]
    assert new_client().get("/api/v1/requests", params={"category": "weddings"}).json()["total"] == 0

    matches = client.get(f"/api/v1/requests/{req['id']}/matches").json()
    assert matches[0]["creator"]["handle"] == "sky-cam"
    assert any("Jacksonville" in r for r in matches[0]["reasons"])
    assert drone.get(f"/api/v1/requests/{req['id']}/matches").status_code == 404  # client only

    bad = proposal_body(total_cents=1)
    assert drone.post(f"/api/v1/requests/{req['id']}/proposals", json=bad).status_code == 422
    mismatch = proposal_body(total_cents=M1 + M2 + 100)
    assert drone.post(f"/api/v1/requests/{req['id']}/proposals", json=mismatch).status_code == 400
    p1 = drone.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body()).json()
    p2 = other.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body(total_cents=M1, milestones=[
        {"title": "All", "amount_cents": M1}])).json()
    assert client.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body()).status_code in (400, 403)

    # Bidders only see their own proposal; the client sees both.
    assert [p["id"] for p in other.get(f"/api/v1/requests/{req['id']}/proposals").json()] == [p2["id"]]
    assert {p["id"] for p in client.get(f"/api/v1/requests/{req['id']}/proposals").json()} == {p1["id"], p2["id"]}

    project_id = client.post(f"/api/v1/proposals/{p1['id']}/accept").json()["project_id"]
    assert client.get(f"/api/v1/requests/{req['id']}").json()["status"] == "awarded"
    assert other.get(f"/api/v1/requests/{req['id']}/proposals").json()[0]["status"] == "declined"
    assert new_client().get("/api/v1/requests").json()["total"] == 0  # no longer on the board
    project = client.get(f"/api/v1/projects/{project_id}").json()
    assert project["rights_type"] == "exclusive" and project["total_cents"] == M1 + M2
    assert project["acceptance_evidence"]["client_user_id"] == str(uid("client@example.com"))
    assert [m["status"] for m in project["milestones"]] == ["unfunded", "unfunded"]
    assert project["commission_percent"] == 15
    with SessionLocal() as db:
        kinds = {n.kind for n in db.scalars(select(Notification).where(Notification.user_id == uid("drone@example.com")))}
        assert "proposal_accepted" in kinds
    # Strangers can't see the project.
    assert register(new_client(), "stranger@example.com").get(f"/api/v1/projects/{project_id}").status_code == 404


def test_invite_only_request_and_invitation():
    client = register(new_client(), "client@example.com")
    drone = creator_client("drone@example.com", "sky-cam")
    outsider = creator_client("out@example.com", "outsider")
    req = post_request(client, visibility="invite_only", kind="custom_project", rights_preference="custom")
    assert new_client().get(f"/api/v1/requests/{req['id']}").status_code == 404
    assert outsider.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body()).status_code == 404
    assert client.post(f"/api/v1/requests/{req['id']}/invite", json={"creator_handle": "sky-cam",
                                                                     "message": "Would love a quote"}).status_code == 200
    assert drone.get(f"/api/v1/requests/{req['id']}").json()["is_invited"] is True
    assert drone.get("/api/v1/requests/invitations").json()[0]["id"] == req["id"]
    assert drone.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body()).status_code == 201


def test_milestone_lifecycle_money_and_reviews():
    client, drone, project_id = booked_project()
    project = client.get(f"/api/v1/projects/{project_id}").json()
    m1, m2 = (m["id"] for m in project["milestones"])

    # Only the client funds; creator can't deliver before funding.
    assert drone.post(f"/api/v1/milestones/{m1}/fund").status_code == 404
    r = drone.post(f"/api/v1/milestones/{m1}/deliverables", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 409
    fund(client, m1)
    with SessionLocal() as db:
        assert ledger.balance(db, "client_funds_held", "USD") == M1
        assert ledger.balance(db, "processing_fees", "USD") == fake_fee(M1)
    reconcile_ok()

    assert drone.post(f"/api/v1/milestones/{m1}/submit", json={}).status_code == 400  # no files yet
    deliver(drone, m1)
    detail = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]
    assert detail["status"] == "submitted" and detail["auto_approve_at"]
    link = client.post(f"/api/v1/deliverables/{detail['deliverables'][0]['id']}/link").json()["url"]
    dl = new_client().get(link)
    assert dl.status_code == 200 and dl.content.startswith(b"\x00\x00\x00\x18ftyp")
    assert register(new_client(), "xavier@example.com").post(
        f"/api/v1/deliverables/{detail['deliverables'][0]['id']}/link").status_code == 404

    assert client.post(f"/api/v1/milestones/{m1}/revision", json={"note": "Please brighten the opening"}).status_code == 200
    deliver(drone, m1)
    # One revision included; the second is refused.
    assert client.post(f"/api/v1/milestones/{m1}/revision", json={"note": "Another change"}).status_code == 409
    assert client.post(f"/api/v1/milestones/{m1}/approve").status_code == 200

    creator_share = (M1 * 8500 + 5000) // 10000
    summary = drone.get("/api/v1/earnings/summary").json()
    assert summary["pending_cents"] == creator_share and summary["by_kind"] == {"service_milestone": creator_share}
    rows = drone.get("/api/v1/earnings").json()["items"]
    assert rows[0]["rule"] == "services_commission v1" and rows[0]["license_name"] == "Custom production"
    with SessionLocal() as db:
        assert ledger.balance(db, "client_funds_held", "USD") == 0
        assert ledger.balance(db, "platform_revenue", "USD") == M1 - creator_share
    reconcile_ok()

    # Second milestone: funded, then the creator refunds it.
    fund(client, m2)
    assert drone.post(f"/api/v1/milestones/{m2}/refund", json={"note": "Scope changed"}).status_code == 200
    assert get_provider().refunds[-1]["amount"] == M2
    project = client.get(f"/api/v1/projects/{project_id}").json()
    assert project["status"] == "completed"
    reconcile_ok()

    # Verified reviews, once per side.
    assert client.post(f"/api/v1/projects/{project_id}/reviews", json={"rating": 5, "body": "Stunning work"}).status_code == 201
    assert client.post(f"/api/v1/projects/{project_id}/reviews", json={"rating": 4}).status_code == 409
    assert drone.post(f"/api/v1/projects/{project_id}/reviews", json={"rating": 5, "body": "Great client"}).status_code == 201
    rep = new_client().get("/api/v1/creators/sky-cam/reputation").json()
    assert rep["average"] == 5 and rep["count"] == 1 and rep["completed_projects"] == 1
    assert rep["reviews"][0]["verified"] is True

    # Payout after the hold period.
    with SessionLocal() as db:
        db.execute(update(__import__("app.models", fromlist=["Earning"]).Earning)
                   .values(available_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()
    drone.post("/api/v1/payouts/account/onboard", json={"country": "US"})
    fin = login_as("cfo@example.com", "finance_admin")
    assert fin.post("/api/v1/admin/finance/payouts/run").json()["sent"] == 1
    assert get_provider().transfers[-1]["amount"] == creator_share
    reconcile_ok()


def test_dispute_split_resolution():
    client, drone, project_id = booked_project()
    m1 = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["id"]
    fund(client, m1)
    deliver(drone, m1)
    r = client.post(f"/api/v1/projects/{project_id}/disputes", json={
        "milestone_id": m1, "reason": "quality", "description": "Footage is out of focus for most of the clip."})
    assert r.status_code == 201
    dispute_id = r.json()["id"]
    p = client.get(f"/api/v1/projects/{project_id}").json()
    assert p["status"] == "disputed" and p["milestones"][0]["auto_approve_at"] is None
    assert client.post(f"/api/v1/milestones/{m1}/approve").status_code == 409  # frozen while disputed

    assert client.get("/api/v1/admin/production/disputes").status_code == 403
    mod = login_as("mod@example.com", "moderator")
    assert mod.get("/api/v1/admin/production/disputes").json()[0]["id"] == dispute_id
    r = mod.post(f"/api/v1/admin/production/disputes/{dispute_id}/resolve",
                 json={"outcome": "split", "creator_share_bps": 6000, "note": "Partially usable footage."})
    assert r.status_code == 200, r.text
    to_creator = M1 * 6000 // 10000
    assert get_provider().refunds[-1]["amount"] == M1 - to_creator
    assert drone.get("/api/v1/earnings/summary").json()["pending_cents"] == (to_creator * 8500 + 5000) // 10000
    assert client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["status"] == "approved"
    reconcile_ok()


def test_dispute_withdrawal_restores_state():
    client, drone, project_id = booked_project()
    m1 = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["id"]
    fund(client, m1)
    d = drone.post(f"/api/v1/projects/{project_id}/disputes", json={
        "milestone_id": m1, "reason": "unresponsive", "description": "Client has not replied for two weeks."}).json()
    assert client.post(f"/api/v1/disputes/{d['id']}/withdraw").status_code == 409  # only the opener
    assert drone.post(f"/api/v1/disputes/{d['id']}/withdraw").status_code == 200
    p = client.get(f"/api/v1/projects/{project_id}").json()
    assert p["status"] == "active" and p["milestones"][0]["status"] == "funded"


def test_auto_approval_and_cancellation_rules():
    client, drone, project_id = booked_project()
    m1, m2 = (m["id"] for m in client.get(f"/api/v1/projects/{project_id}").json()["milestones"])
    fund(client, m1)
    assert client.post(f"/api/v1/projects/{project_id}/cancel").status_code == 409  # funds held
    deliver(drone, m1)
    with SessionLocal() as db:
        db.execute(update(Milestone).where(Milestone.id == uuid.UUID(m1))
                   .values(auto_approve_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
        assert svc.auto_approve_due(db) == 1
        db.commit()
    p = client.get(f"/api/v1/projects/{project_id}").json()
    assert p["milestones"][0]["status"] == "approved"
    # Remaining milestone is unfunded, so the project can now be canceled; it counts as completed.
    assert drone.post(f"/api/v1/projects/{project_id}/cancel").status_code == 200
    p = client.get(f"/api/v1/projects/{project_id}").json()
    assert p["milestones"][1]["status"] == "canceled" and p["status"] == "completed"
    reconcile_ok()


def test_unfunded_project_cancel_and_added_milestone():
    client, drone, project_id = booked_project()
    r = client.post(f"/api/v1/projects/{project_id}/milestones", json={"title": "Extra social cutdowns",
                                                                       "amount_cents": 15_000})
    assert r.status_code == 201
    sneaky = {"title": "Sneaky", "amount_cents": 100}
    assert drone.post(f"/api/v1/projects/{project_id}/milestones", json=sneaky).status_code == 404
    assert client.get(f"/api/v1/projects/{project_id}").json()["total_cents"] == M1 + M2 + 15_000
    assert client.post(f"/api/v1/projects/{project_id}/cancel").status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}").json()["status"] == "canceled"


def test_packages_booking():
    drone = creator_client("drone@example.com", "sky-cam")
    pkg = {"title": "Real estate aerial package", "description": "Twenty aerial photos and a 60-second video tour.",
           "category": "real_estate", "deliverables": "20 photos, 1 video", "price_cents": 45_000,
           "delivery_days": 5, "revisions_included": 2, "rights_type": "nonexclusive",
           "rights_terms": "Client may use for marketing the listing; creator keeps copyright."}
    created = drone.post("/api/v1/packages", json=pkg).json()
    assert new_client().get("/api/v1/creators/sky-cam/packages").json()[0]["price_cents"] == 45_000
    assert drone.post(f"/api/v1/packages/{created['id']}/book", json={"accept_terms": True}).status_code == 400
    client = register(new_client(), "client@example.com")
    assert client.post(f"/api/v1/packages/{created['id']}/book", json={"accept_terms": False}).status_code == 400
    project_id = client.post(f"/api/v1/packages/{created['id']}/book",
                             json={"brief": "123 Main St listing", "accept_terms": True}).json()["project_id"]
    project = client.get(f"/api/v1/projects/{project_id}").json()
    assert project["revisions_included"] == 2 and len(project["milestones"]) == 1
    assert project["acceptance_evidence"]["package_snapshot"]["price_cents"] == 45_000
    # Later package edits don't change the booked terms.
    drone.put(f"/api/v1/packages/{created['id']}", json=pkg | {"price_cents": 99_000})
    assert client.get(f"/api/v1/projects/{project_id}").json()["total_cents"] == 45_000
    assert [p["role"] for p in drone.get("/api/v1/projects/mine").json()] == ["creator"]


def test_messaging_and_notifications():
    client, drone, project_id = booked_project()
    conv_id = client.get(f"/api/v1/projects/{project_id}").json()["conversation_id"]
    assert client.post(f"/api/v1/conversations/{conv_id}/messages", json={"body": "Can we shoot Friday?"}).status_code == 201
    convs = drone.get("/api/v1/conversations").json()
    project_conv = next(c for c in convs if c["id"] == conv_id)
    assert project_conv["unread"] == 1 and project_conv["link"] == f"/projects/{project_id}"
    thread = drone.get(f"/api/v1/conversations/{conv_id}").json()
    assert any(m["body"] == "Can we shoot Friday?" and not m["mine"] for m in thread["messages"])
    assert next(c for c in drone.get("/api/v1/conversations").json() if c["id"] == conv_id)["unread"] == 0
    stranger = register(new_client(), "stranger@example.com")
    assert stranger.get(f"/api/v1/conversations/{conv_id}").status_code == 404
    assert stranger.post(f"/api/v1/conversations/{conv_id}/messages", json={"body": "hi"}).status_code == 404

    # Contact from the storefront creates a direct conversation.
    r = stranger.post("/api/v1/conversations", json={"creator_handle": "sky-cam", "body": "Available in May?"})
    assert r.status_code == 201
    assert drone.get("/api/v1/notifications/unread-count").json()["notifications"] >= 2
    drone.post("/api/v1/notifications/read")
    assert drone.get("/api/v1/notifications/unread-count").json()["notifications"] == 0


def test_client_gallery_proofing():
    drone = creator_client("drone@example.com", "sky-cam")
    g = drone.post("/api/v1/galleries", json={"title": "Smith wedding proofs", "client_name": "Jane Smith",
                                              "client_email": "jane@example.com", "password": "secret-pass",
                                              "selection_limit": 1, "allow_downloads": False}).json()
    token = g["share_url"].rsplit("/", 1)[1]
    assert new_client().get(f"/api/v1/galleries/public/{token}").status_code == 404  # draft
    assert drone.post(f"/api/v1/galleries/{g['id']}/share").status_code == 400  # empty
    for i in range(2):
        r = drone.post(f"/api/v1/galleries/{g['id']}/items",
                       files={"file": (f"img{i}.jpg", jpeg_bytes((1600, 1000), (40 * i, 90, 140)), "image/jpeg")})
        assert r.status_code == 202, r.text
    assert drone.post(f"/api/v1/galleries/{g['id']}/share").status_code == 200
    assert any(m["to"] == "jane@example.com" for m in email.outbox())

    public = new_client()
    public.cookies.clear()
    assert public.get(f"/api/v1/galleries/public/{token}").status_code == 401
    assert public.post(f"/api/v1/galleries/public/{token}/unlock", json={"password": "nope"}).status_code == 401
    key = public.post(f"/api/v1/galleries/public/{token}/unlock", json={"password": "secret-pass"}).json()["key"]
    h = {"X-Gallery-Key": key} | CSRF
    view = public.get(f"/api/v1/galleries/public/{token}", headers=h).json()
    assert view["id"] is None and len(view["items"]) == 2 and "share_url" not in view
    assert all("PROOF" not in (i["preview_url"] or "") for i in view["items"])
    a, b = (i["id"] for i in view["items"])
    assert public.patch(f"/api/v1/galleries/public/{token}/items/{a}", json={"is_selected": True}, headers=h).status_code == 200
    assert public.patch(f"/api/v1/galleries/public/{token}/items/{b}", json={"is_selected": True}, headers=h).status_code == 409
    public.post(f"/api/v1/galleries/public/{token}/comments", json={"body": "Crop tighter please", "item_id": a,
                                                                   "is_revision_request": True}, headers=h)
    assert public.post(f"/api/v1/galleries/public/{token}/items/{a}/download", headers=h).status_code == 403
    assert public.post(f"/api/v1/galleries/public/{token}/approve", headers=h).status_code == 200
    owner = drone.get(f"/api/v1/galleries/{g['id']}").json()
    assert owner["status"] == "approved" and owner["selected_count"] == 1
    assert owner["comments"][0]["is_revision_request"] is True

    # Enable downloads; the client can fetch the original through a signed link.
    drone.put(f"/api/v1/galleries/{g['id']}", json={"title": g["title"], "allow_downloads": True})
    url = public.post(f"/api/v1/galleries/public/{token}/items/{a}/download", headers=h).json()["url"]
    assert new_client().get(url).content[:3] == b"\xff\xd8\xff"
    # Another creator can't manage this gallery.
    other = creator_client("other@example.com", "other-cam")
    assert other.get(f"/api/v1/galleries/{g['id']}").status_code == 404


def test_chargeback_on_held_milestone():
    client, drone, project_id = booked_project()
    m1 = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["id"]
    order_id = fund(client, m1)
    with SessionLocal() as db:
        out = ps.handle_event(db, get_provider(), ProviderEvent("evt_cb", "charge.dispute.created", {
            "id": "dp_9", "payment_intent": f"fake_pi_{order_id}", "balance_transactions": [{"fee": 1500}]}))
        db.commit()
        assert out == "disputed"
        assert ledger.balance(db, "client_funds_held", "USD") == 0
    assert client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["status"] == "refunded"
    reconcile_ok()


def test_request_validation():
    client = register(new_client(), "client@example.com")
    limiter.reset()
    base = {"title": "Need a promo", "description": "A thirty second promo for our restaurant opening.",
            "category": "hospitality", "rights_preference": "nonexclusive"}
    assert client.post("/api/v1/requests", json=base | {"category": "nope"}).status_code == 422
    assert client.post("/api/v1/requests", json=base | {"deadline": "2000-01-01"}).status_code == 422
    assert client.post("/api/v1/requests", json=base | {"budget_min_cents": 9000, "budget_max_cents": 500}).status_code == 422
    assert client.post("/api/v1/requests", json=base | {"reference_urls": ["javascript:alert(1)"]}).status_code == 422
    assert client.post("/api/v1/requests", json=base).status_code == 201
    unverified = register(new_client(), "unverified@example.com", verify=False)
    assert unverified.post("/api/v1/requests", json=base).status_code == 403


def test_funding_requires_payments_enabled():
    from app.core.config import get_settings

    client, _, project_id = booked_project()
    m1 = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["id"]
    settings = get_settings()
    settings.feature_paid_licensing = False
    try:
        assert client.post(f"/api/v1/milestones/{m1}/fund").status_code == 403
    finally:
        settings.feature_paid_licensing = True

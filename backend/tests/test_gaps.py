"""Gap closure: partial and provider-side refunds, provider reconciliation,
referral bonuses and booking commissions, milestone refunds after release,
chargebacks that are later won, duplicate payments and gallery sales."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.database import SessionLocal
from app.models import Earning, Milestone, Order, PayoutAccount, PayoutAccountStatus
from app.services import email, ledger, payout_service
from app.services import payment_service as ps
from app.services.payments import ProviderEvent, get_provider
from app.services.payments.fake import fake_fee
from tests.conftest import CSRF, become_creator, jpeg_bytes, new_client, register, upload_photo
from tests.test_commerce import PRICE, buy, listed_asset, login_as, make_available, reconcile_ok, user_id
from tests.test_production import M1, creator_client, deliver, fund, post_request, proposal_body

CREATOR_BPS, AFF_BPS = 8500, 1000


def event(kind, data):
    with SessionLocal() as db:
        out = ps.handle_event(db, get_provider(), ProviderEvent(f"evt_{uuid.uuid4().hex}", kind, data))
        db.commit()
    return out


def referred_client(email_addr, code):
    c = new_client()
    r = c.post("/api/v1/auth/register", json={"email": email_addr, "password": "correct-horse-battery",
                                               "display_name": email_addr.split("@")[0].title(), "accept_terms": True,
                                               "referral_code": code})
    assert r.status_code == 201, r.text
    msg = next(m for m in reversed(email.outbox()) if m["to"] == email_addr)
    token = re.search(r"token=([\w-]+)", msg["body"]).group(1)
    assert c.post("/api/v1/auth/verify-email", json={"token": token}, headers=CSRF).status_code == 200
    return c


def service_split(gross):
    creator = (gross * CREATOR_BPS + 5000) // 10000
    affiliate = (gross - creator) * AFF_BPS // 10000
    return creator, affiliate


# --- License partial refunds ------------------------------------------------------------------------

def test_partial_refunds_then_final_refund():
    creator, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buy(buyer, listing_id)
    cert = order["lines"][0]["certificate_number"]
    full_share = creator.get("/api/v1/earnings/summary").json()["pending_cents"]
    fin = login_as("cfo@example.com", "finance_admin")
    url = f"/api/v1/admin/finance/orders/{order['id']}/refund"

    r = fin.post(url, json={"reason": "price_adjustment", "amount_cents": 1000})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "partially_refunded" and r.json()["lines"][0]["refunded_cents"] == 1000
    assert get_provider().refunds[-1]["amount"] == 1000
    assert new_client().get(f"/api/v1/licenses/verify/{cert}").json()["status"] == "active"
    after_first = creator.get("/api/v1/earnings/summary").json()["lifetime_cents"]
    assert 0 < after_first < full_share
    reconcile_ok()

    assert fin.post(url, json={"reason": "price_adjustment", "amount_cents": PRICE}).status_code == 400  # too much
    assert fin.post(url, json={"reason": "price_adjustment", "amount_cents": 900}).status_code == 200
    reconcile_ok()
    r = fin.post(url, json={"reason": "requested_by_customer"})  # the rest
    assert r.json()["status"] == "refunded"
    assert [x["amount"] for x in get_provider().refunds] == [1000, 900, PRICE - 1900]
    assert len({x["idempotency_key"] for x in get_provider().refunds}) == 3
    assert creator.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    assert new_client().get(f"/api/v1/licenses/verify/{cert}").json()["status"] == "refunded"
    with SessionLocal() as db:
        assert ledger.balance(db, ledger.creator_payable(user_id("seller@example.com")), "USD") == 0
        assert ledger.balance(db, "platform_revenue", "USD") == 0
    reconcile_ok()


def test_external_partial_refunds_are_booked():
    creator, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buy(buyer, listing_id)
    pi = f"fake_pi_{order['id']}"
    assert event("charge.refunded", {"id": "ch_1", "payment_intent": pi, "amount_refunded": 500}) == "refunded"
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "partially_refunded"
    assert event("charge.refunded", {"id": "ch_1", "payment_intent": pi, "amount_refunded": 500}) == "already_recorded"
    reconcile_ok()
    assert event("charge.refunded", {"id": "ch_1", "payment_intent": pi, "amount_refunded": PRICE}) == "refunded"
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "refunded"
    assert creator.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    reconcile_ok()


# --- Provider reconciliation ---------------------------------------------------------------------------

def test_provider_reconciliation_flags_differences():
    _, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buy(buyer, listing_id)
    provider = get_provider()
    with SessionLocal() as db:
        run = payout_service.reconcile(db, provider=provider)
        assert run.status == "ok" and run.checks["provider_matches"], run.findings
        provider.charges[f"fake_pi_{order['id']}"]["fee"] += 1  # provider charged a different fee
        provider.refunds.append({"id": "fake_re_x", "payment_id": f"fake_pi_{order['id']}", "amount": 100,
                                 "idempotency_key": "dash", "created": int(datetime.now(UTC).timestamp())})
        run = payout_service.reconcile(db, provider=provider)
        issues = {f.get("issue") for f in run.findings if f["check"] == "provider_matches"}
        assert run.status != "ok" and {"fee_mismatch", "refund_total_mismatch"} <= issues
        db.rollback()


# --- Referral bonus and tax status ------------------------------------------------------------------------

def test_creator_recruitment_bonus_paid_once():
    partner = register(new_client(), "partner@example.com")
    code = partner.post("/api/v1/referrals/code").json()["code"]
    seller = referred_client("seller@example.com", code)
    become_creator(seller, "seller")
    asset = upload_photo(seller)
    seller.put(f"/api/v1/media/{asset['id']}/pricing",
               json={"prices": [{"license_code": "standard_commercial", "price_cents": PRICE}]})
    mod = login_as("mod@example.com", "moderator")
    mod.post(f"/api/v1/admin/media/{asset['id']}/decision", json={"action": "approve"})
    listing_id = new_client().get(f"/api/v1/media/{asset['id']}").json()["prices"][0]["id"]
    buyer = register(new_client(), "buyer@example.com")
    buy(buyer, listing_id)
    make_available()
    with SessionLocal() as db:
        payout_service.release_earnings(db)
        db.commit()
    s = partner.get("/api/v1/earnings/summary").json()
    assert s["by_kind"].get("referral_bonus") == 2500 and s["available_cents"] == 2500
    rows = partner.get("/api/v1/earnings").json()["items"]
    assert rows[0]["license_name"] == "Referral program"
    # A second sale does not pay the bonus again.
    buy(buyer, listing_id)
    make_available()
    with SessionLocal() as db:
        payout_service.release_earnings(db)
        db.commit()
    assert partner.get("/api/v1/earnings/summary").json()["by_kind"]["referral_bonus"] == 2500
    with SessionLocal() as db:
        assert ledger.balance(db, "referral_bonuses", "USD") == 2500
    reconcile_ok()


def test_tax_info_status():
    from app.api.v1.earnings import tax_info_status

    acct = PayoutAccount(status=PayoutAccountStatus.restricted, details_submitted=True, payouts_enabled=False,
                         requirements_due=["individual.ssn_last_4"])
    assert tax_info_status(acct) == "required"
    acct.requirements_due, acct.payouts_enabled = [], True
    assert tax_info_status(acct) == "provided"
    acct.details_submitted = False
    assert tax_info_status(acct) == "pending"


# --- Milestones ---------------------------------------------------------------------------------------------

def referred_project():
    partner = register(new_client(), "partner@example.com")
    code = partner.post("/api/v1/referrals/code").json()["code"]
    client = referred_client("client@example.com", code)
    drone = creator_client("drone@example.com", "sky-cam")
    req = post_request(client)
    proposal = drone.post(f"/api/v1/requests/{req['id']}/proposals", json=proposal_body()).json()
    project_id = client.post(f"/api/v1/proposals/{proposal['id']}/accept").json()["project_id"]
    m1 = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["id"]
    return partner, client, drone, project_id, m1


def test_booking_referral_commission_and_refunds_after_release():
    partner, client, drone, project_id, m1 = referred_project()
    order_id = fund(client, m1)
    deliver(drone, m1)
    assert client.post(f"/api/v1/milestones/{m1}/approve").status_code == 200
    creator_share, affiliate = service_split(M1)
    assert drone.get("/api/v1/earnings/summary").json()["pending_cents"] == creator_share
    p = partner.get("/api/v1/earnings/summary").json()
    assert p["by_kind"] == {"affiliate_commission": affiliate}
    assert "Referral commission" in partner.get("/api/v1/earnings").json()["items"][0]["license_name"]
    with SessionLocal() as db:
        assert ledger.balance(db, "platform_revenue", "USD") == M1 - creator_share - affiliate
    reconcile_ok()

    # Goodwill refund after release: each party gives back its share.
    fin = login_as("cfo@example.com", "finance_admin")
    r = fin.post(f"/api/v1/admin/finance/orders/{order_id}/refund",
                 json={"reason": "requested_by_customer", "amount_cents": 10_000})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "partially_refunded" and get_provider().refunds[-1]["amount"] == 10_000
    assert drone.get("/api/v1/earnings/summary").json()["lifetime_cents"] < creator_share
    assert partner.get("/api/v1/earnings/summary").json()["lifetime_cents"] < affiliate
    reconcile_ok()

    # The rest is refunded in the provider dashboard.
    assert event("charge.refunded", {"id": "ch_m", "payment_intent": f"fake_pi_{order_id}",
                                     "amount_refunded": M1}) == "refunded"
    assert drone.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    assert partner.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    with SessionLocal() as db:
        assert db.get(Order, uuid.UUID(order_id)).status.value == "refunded"
        assert ledger.balance(db, "platform_revenue", "USD") == 0
    reconcile_ok()


def test_external_refund_of_held_milestone():
    _, client, drone, project_id, m1 = referred_project()
    order_id = fund(client, m1)
    assert event("charge.refunded", {"id": "ch_h", "payment_intent": f"fake_pi_{order_id}",
                                     "amount_refunded": 20_000}) == "refunded"
    m = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]
    assert m["status"] == "funded"  # partially refunded, the rest still held
    reconcile_ok()
    deliver(drone, m1)
    assert client.post(f"/api/v1/milestones/{m1}/approve").status_code == 200
    assert drone.get("/api/v1/earnings/summary").json()["pending_cents"] == service_split(M1 - 20_000)[0]
    reconcile_ok()


def test_chargeback_after_release_then_won():
    partner, client, drone, project_id, m1 = referred_project()
    order_id = fund(client, m1)
    deliver(drone, m1)
    client.post(f"/api/v1/milestones/{m1}/approve")
    creator_share, affiliate = service_split(M1)
    pi = f"fake_pi_{order_id}"
    assert event("charge.dispute.created", {"id": "dp_m", "payment_intent": pi,
                                            "balance_transactions": [{"fee": 1500}]}) == "disputed"
    assert drone.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    assert partner.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    reconcile_ok()
    assert event("charge.dispute.closed", {"id": "dp_m", "payment_intent": pi, "status": "won"}) == "dispute_won"
    assert drone.get("/api/v1/earnings/summary").json()["pending_cents"] == creator_share
    assert partner.get("/api/v1/earnings/summary").json()["pending_cents"] == affiliate
    assert client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["status"] == "approved"
    with SessionLocal() as db:
        assert db.get(Order, uuid.UUID(order_id)).status.value == "paid"
        assert ledger.balance(db, "refund_losses", "USD") == 1500
    reconcile_ok()


def test_chargeback_on_held_milestone_then_won():
    _, client, drone, project_id, m1 = referred_project()
    order_id = fund(client, m1)
    pi = f"fake_pi_{order_id}"
    event("charge.dispute.created", {"id": "dp_h", "payment_intent": pi})
    assert client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["status"] == "refunded"
    reconcile_ok()
    event("charge.dispute.closed", {"id": "dp_h", "payment_intent": pi, "status": "won"})
    assert client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["status"] == "funded"
    with SessionLocal() as db:
        assert ledger.balance(db, "client_funds_held", "USD") == M1
    reconcile_ok()
    deliver(drone, m1)
    assert client.post(f"/api/v1/milestones/{m1}/approve").status_code == 200
    reconcile_ok()


def test_duplicate_milestone_payment_is_refunded_automatically():
    _, client, _, project_id, m1 = referred_project()
    first = client.post(f"/api/v1/milestones/{m1}/fund").json()["order_id"]
    with SessionLocal() as db:  # a second checkout opened in another tab
        db.execute(update(Order).where(Order.id == uuid.UUID(first)).values(status="canceled"))
        db.commit()
    second = client.post(f"/api/v1/milestones/{m1}/fund").json()["order_id"]
    assert second != first
    with SessionLocal() as db:
        db.execute(update(Order).where(Order.id == uuid.UUID(first)).values(status="pending"))
        db.commit()
    assert client.post(f"/api/v1/payments/dev/complete/{second}").json()["outcome"] == "milestone_funded"
    assert client.post(f"/api/v1/payments/dev/complete/{first}").json()["outcome"] == "milestone_funded"
    refund = get_provider().refunds[-1]
    assert refund["amount"] == M1 and refund["payment_id"] == f"fake_pi_{first}"
    with SessionLocal() as db:
        assert db.get(Order, uuid.UUID(first)).status.value == "refunded"
        assert ledger.balance(db, "client_funds_held", "USD") == M1
        assert ledger.balance(db, "processing_fees", "USD") == 2 * fake_fee(M1)
        m = db.get(Milestone, uuid.UUID(m1))
        assert m.status.value == "funded"
    assert any("Duplicate payment refunded" in n["title"] for n in client.get("/api/v1/notifications").json())
    reconcile_ok()


# --- Gallery sales -------------------------------------------------------------------------------------------

ADDRESS = {"name": "Jane Smith", "line1": "1 Main St", "city": "Jacksonville", "region": "FL",
           "postal_code": "32202", "country": "US"}


def gallery_for_sale(items=2):
    drone = creator_client("drone@example.com", "sky-cam")
    g = drone.post("/api/v1/galleries", json={"title": "Smith wedding", "client_name": "Jane Smith",
                                              "client_email": "jane@example.com", "download_price_cents": 1500}).json()
    for i in range(items):
        r = drone.post(f"/api/v1/galleries/{g['id']}/items",
                       files={"file": (f"img{i}.jpg", jpeg_bytes((1200, 800), (40 * i, 90, 140)), "image/jpeg")})
        assert r.status_code == 202, r.text
    opt = drone.post(f"/api/v1/galleries/{g['id']}/print-options", json={"name": "8×10 lustre", "price_cents": 4500})
    assert opt.status_code == 201, opt.text
    assert drone.post(f"/api/v1/galleries/{g['id']}/share").status_code == 200
    token = g["share_url"].rsplit("/", 1)[1]
    return drone, g, token, opt.json()["id"]


def test_gallery_downloads_and_prints_sale_refunds():
    drone, g, token, option_id = gallery_for_sale()
    public = new_client()
    view = public.get(f"/api/v1/galleries/public/{token}").json()
    assert view["download_price_cents"] == 1500 and view["print_options"][0]["price_cents"] == 4500
    a, b = (i["id"] for i in view["items"])
    url = f"/api/v1/galleries/public/{token}/orders"
    base = {"client_name": "Jane Smith", "client_email": "jane@example.com"}
    prints = {"item_id": b, "kind": "print", "print_option_id": option_id, "quantity": 2}
    assert public.post(url, json=base | {"items": [prints]}).status_code == 400  # no address
    assert public.post(url, json=base | {"items": [{"item_id": a, "kind": "digital"}] * 2}).status_code == 400
    r = public.post(url, json=base | {"items": [{"item_id": a, "kind": "digital"}, prints],
                                      "shipping_address": ADDRESS})
    assert r.status_code == 201, r.text
    order_id, subtotal = r.json()["order_id"], 1500 + 2 * 4500
    assert r.json()["total_cents"] == subtotal and "/checkout/dev-pay" in r.json()["checkout_url"]
    assert public.post(f"/api/v1/galleries/public/{token}/items/{a}/download").status_code == 403
    assert new_client().post(f"/api/v1/payments/dev/complete/{order_id}").json()["outcome"] == "gallery_paid"

    assert public.get(f"/api/v1/galleries/public/{token}/orders/{order_id}").json()["status"] == "paid"
    link = public.post(f"/api/v1/galleries/public/{token}/items/{a}/download").json()["url"]
    assert new_client().get(link).content[:3] == b"\xff\xd8\xff"
    assert public.post(f"/api/v1/galleries/public/{token}/items/{b}/download").status_code == 403  # print only
    assert any(m["to"] == "jane@example.com" and "order" in m["subject"] for m in email.outbox())
    creator_share = (subtotal * CREATOR_BPS + 5000) // 10000
    assert drone.get("/api/v1/earnings/summary").json()["by_kind"] == {"gallery_sale": creator_share}
    row = drone.get("/api/v1/earnings").json()["items"][0]
    assert row["asset_title"] == "Gallery order: Smith wedding" and row["gross_cents"] == subtotal
    reconcile_ok()

    orders = drone.get(f"/api/v1/galleries/{g['id']}/orders").json()
    assert len(orders) == 1 and orders[0]["shipping_address"]["city"] == "Jacksonville"
    r = drone.post(f"/api/v1/galleries/{g['id']}/orders/{orders[0]['id']}/ship",
                   json={"carrier": "UPS", "tracking_number": "1Z999"})
    assert r.status_code == 200 and r.json()["status"] == "shipped"
    assert any("shipped" in m["subject"] for m in email.outbox() if m["to"] == "jane@example.com")

    fin = login_as("cfo@example.com", "finance_admin")
    r = fin.post(f"/api/v1/admin/finance/orders/{order_id}/refund", json={"reason": "other", "amount_cents": 2000})
    assert r.status_code == 200, r.text
    assert any(o["id"] == order_id and o["buyer_email"] == "jane@example.com"
               for o in fin.get("/api/v1/admin/finance/orders").json()["items"])
    assert public.post(f"/api/v1/galleries/public/{token}/items/{a}/download").status_code == 200  # still unlocked
    reconcile_ok()
    assert event("charge.refunded", {"id": "ch_g", "payment_intent": f"fake_pi_{order_id}",
                                     "amount_refunded": subtotal}) == "refunded"
    assert public.post(f"/api/v1/galleries/public/{token}/items/{a}/download").status_code == 403
    assert drone.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    with SessionLocal() as db:
        assert ledger.balance(db, "platform_revenue", "USD") == 0
    reconcile_ok()


def test_gallery_chargeback_then_won():
    drone, g, token, _ = gallery_for_sale(items=1)
    public = new_client()
    a = public.get(f"/api/v1/galleries/public/{token}").json()["items"][0]["id"]
    order_id = public.post(f"/api/v1/galleries/public/{token}/orders", json={
        "client_name": "Jane", "client_email": "jane@example.com",
        "items": [{"item_id": a, "kind": "digital"}]}).json()["order_id"]
    new_client().post(f"/api/v1/payments/dev/complete/{order_id}")
    pi = f"fake_pi_{order_id}"
    assert event("charge.dispute.created", {"id": "dp_g", "payment_intent": pi}) == "disputed"
    assert public.post(f"/api/v1/galleries/public/{token}/items/{a}/download").status_code == 403
    assert drone.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    reconcile_ok()
    assert event("charge.dispute.closed", {"id": "dp_g", "payment_intent": pi, "status": "won"}) == "dispute_won"
    assert public.post(f"/api/v1/galleries/public/{token}/items/{a}/download").status_code == 200
    assert drone.get("/api/v1/earnings/summary").json()["pending_cents"] == (1500 * CREATOR_BPS + 5000) // 10000
    reconcile_ok()


def test_gallery_sales_guards():
    drone, g, token, option_id = gallery_for_sale(items=1)
    public = new_client()
    a = public.get(f"/api/v1/galleries/public/{token}").json()["items"][0]["id"]
    url = f"/api/v1/galleries/public/{token}/orders"
    body = {"client_name": "Jane", "client_email": "jane@example.com"}
    assert public.post(url, json=body | {"items": [{"item_id": a, "kind": "print",
                                                     "print_option_id": str(uuid.uuid4())}],
                                         "shipping_address": ADDRESS}).status_code == 400
    assert drone.delete(f"/api/v1/galleries/{g['id']}/print-options/{option_id}").status_code == 200
    assert public.get(f"/api/v1/galleries/public/{token}").json()["print_options"] == []
    drone.put(f"/api/v1/galleries/{g['id']}", json={"title": g["title"], "allow_downloads": True})
    # Nothing left for sale: downloads are free now and prints were removed.
    assert public.post(url, json=body | {"items": [{"item_id": a, "kind": "digital"}]}).status_code == 400
    with SessionLocal() as db:
        assert not db.scalars(select(Earning)).all()

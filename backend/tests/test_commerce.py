"""Phase 2: checkout, royalties in the ledger, refunds, disputes, payouts,
referrals, reconciliation and the Stripe adapter."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.rate_limit import limiter
from app.models import Earning, LedgerAccount, Order, User
from app.services import ledger, payout_service
from app.services import payment_service as ps
from app.services.payments import PaymentProviderError, ProviderEvent, get_provider
from app.services.payments.fake import fake_fee
from app.services.payments.stripe_provider import StripeProvider
from tests.conftest import become_creator, make_role, new_client, register, upload_photo

PRICE = 2900  # standard commercial
FEE = fake_fee(PRICE)  # 2.9% + 30c = 114
NET = PRICE - FEE  # 2786
CREATOR = (NET * 5000 + 5000) // 10000  # 1393


def login_as(email, role):
    c = register(new_client(), email)
    make_role(email, role)
    c.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery"})
    return c


def listed_asset():
    creator = register(new_client(), "seller@example.com")
    become_creator(creator, "seller")
    asset = upload_photo(creator)
    r = creator.put(f"/api/v1/media/{asset['id']}/pricing",
                    json={"prices": [{"license_code": "standard_commercial", "price_cents": PRICE}]})
    assert r.status_code == 200, r.text
    mod = login_as("mod@example.com", "moderator")
    assert mod.post(f"/api/v1/admin/media/{asset['id']}/decision", json={"action": "approve"}).status_code == 200
    detail = new_client().get(f"/api/v1/media/{asset['id']}").json()
    return creator, asset["id"], detail["prices"][0]["id"]


def buy(client, listing_id, key=None):
    r = client.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id, "licensee_name": "Acme Inc"}],
                                            "idempotency_key": key or uuid.uuid4().hex})
    assert r.status_code == 201, r.text
    order = r.json()
    r = client.post(f"/api/v1/payments/dev/complete/{order['id']}")
    assert r.json()["outcome"] == "fulfilled", r.text
    return client.get(f"/api/v1/orders/{order['id']}").json()


def reconcile_ok():
    with SessionLocal() as db:
        run = payout_service.reconcile(db)
        db.commit()
        assert run.status == "ok", run.findings
        return run


def user_id(email):
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == email))


def make_available():
    with SessionLocal() as db:
        db.execute(update(Earning).values(available_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()


def test_checkout_fulfills_with_royalties_ledger_and_license():
    creator, asset_id, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    r = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}], "idempotency_key": "order-key-1"})
    order = r.json()
    assert order["status"] == "pending" and "/checkout/dev-pay" in order["checkout_url"]
    # Same idempotency key returns the same order.
    again = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}], "idempotency_key": "order-key-1"})
    assert again.json()["id"] == order["id"]

    buyer.post(f"/api/v1/payments/dev/complete/{order['id']}")
    paid = buyer.get(f"/api/v1/orders/{order['id']}").json()
    assert paid["status"] == "paid" and paid["lines"][0]["certificate_number"].startswith("LC-")
    cert = paid["lines"][0]["certificate_number"]

    lic = new_client().get(f"/api/v1/licenses/verify/{cert}").json()
    assert lic["price_cents"] == PRICE and lic["license_code"] == "standard_commercial"
    dl = buyer.post(f"/api/v1/licenses/{cert}/download").json()
    assert new_client().get(dl["download_url"]).status_code == 200

    summary = creator.get("/api/v1/earnings/summary").json()
    assert summary["pending_cents"] == CREATOR and summary["available_cents"] == 0
    rows = creator.get("/api/v1/earnings").json()["items"]
    assert rows[0]["rule"] == "model_a_nonexclusive v1" and rows[0]["gross_cents"] == PRICE
    assert any("Creator pool (50%)" in line for line in rows[0]["explanation"])

    with SessionLocal() as db:
        assert ledger.balance(db, "clearing:fake", "USD") == PRICE - FEE
        assert ledger.balance(db, "processing_fees", "USD") == FEE
        assert ledger.balance(db, "fee_recovery", "USD") == FEE
        assert ledger.balance(db, ledger.creator_payable(user_id("seller@example.com")), "USD") == CREATOR
        assert ledger.balance(db, "platform_revenue", "USD") == NET - CREATOR
    reconcile_ok()


def test_duplicate_webhook_event_processed_once():
    _, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}],
                                               "idempotency_key": "dup-test-1"}).json()
    provider = get_provider()
    with SessionLocal() as db:
        o = db.get(Order, uuid.UUID(order["id"]))
        provider.remember_session(o.provider_session_id, order["id"], "USD", PRICE)
        event = ProviderEvent("evt_same", "checkout.session.completed",
                              {"id": o.provider_session_id, "payment_status": "paid", "metadata": {"order_id": order["id"]}})
        assert ps.handle_event(db, provider, event) == "fulfilled"
        assert ps.handle_event(db, provider, event) == "duplicate"
        db.commit()
    assert len(buyer.get("/api/v1/licenses/mine").json()) == 1
    reconcile_ok()


def test_webhook_endpoint_accepts_fake_events():
    _, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}],
                                               "idempotency_key": "hook-test-1"}).json()
    get_provider().remember_session(f"fake_cs_{order['id']}", order["id"], "USD", PRICE)
    body = {"id": "evt_hook", "type": "checkout.session.completed",
            "data": {"object": {"id": f"fake_cs_{order['id']}", "payment_status": "paid", "metadata": {"order_id": order["id"]}}}}
    r = new_client().post("/api/v1/payments/webhooks/fake", content=json.dumps(body))
    assert r.status_code == 200 and r.json()["outcome"] == "fulfilled"
    assert new_client().post("/api/v1/payments/webhooks/stripe", content="{}").status_code == 404


def test_amount_mismatch_is_recorded_and_retryable():
    _, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}],
                                               "idempotency_key": "mismatch-1"}).json()
    provider = get_provider()
    provider.remember_session(f"fake_cs_{order['id']}", order["id"], "USD", PRICE - 100)  # underpaid
    body = {"id": "evt_bad", "type": "checkout.session.completed",
            "data": {"object": {"id": f"fake_cs_{order['id']}", "payment_status": "paid", "metadata": {"order_id": order["id"]}}}}
    r = new_client().post("/api/v1/payments/webhooks/fake", content=json.dumps(body))
    assert r.status_code == 500  # provider will retry
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "pending"
    fin = login_as("cfo@example.com", "finance_admin")
    failed = fin.get("/api/v1/admin/finance/events").json()
    assert failed[0]["provider_event_id"] == "evt_bad"
    provider.remember_session(f"fake_cs_{order['id']}", order["id"], "USD", PRICE)  # corrected at provider
    assert fin.post(f"/api/v1/admin/finance/events/{failed[0]['id']}/retry").json()["outcome"] == "fulfilled"
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "paid"
    reconcile_ok()


def test_checkout_guards():
    creator, asset_id, listing_id = listed_asset()
    r = creator.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}], "idempotency_key": "own-media"})
    assert r.status_code == 400  # cannot license own media
    buyer = register(new_client(), "buyer@example.com")
    r = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": str(uuid.uuid4())}], "idempotency_key": "nope-1234"})
    assert r.status_code == 400
    settings = get_settings()
    settings.feature_paid_licensing = False
    try:
        r = buyer.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}], "idempotency_key": "flag-off"})
        assert r.status_code == 403
    finally:
        settings.feature_paid_licensing = True
    unverified = register(new_client(), "unverified@example.com", verify=False)
    r = unverified.post("/api/v1/orders", json={"items": [{"price_listing_id": listing_id}], "idempotency_key": "unv-1234"})
    assert r.status_code == 403


def test_affiliate_commission_comes_from_platform_share():
    creator, _, listing_id = listed_asset()
    partner = register(new_client(), "partner@example.com")
    stats = partner.post("/api/v1/referrals/code").json()
    assert stats["link"].endswith(stats["code"])
    referred = new_client()
    r = referred.post("/api/v1/auth/register", json={"email": "referred@example.com", "password": "correct-horse-battery",
                                                     "display_name": "Referred", "accept_terms": True,
                                                     "referral_code": stats["code"]})
    assert r.status_code == 201
    referred = register(new_client(), "referred2@example.com")  # unrelated control buyer
    buyer = new_client()
    buyer.post("/api/v1/auth/login", json={"email": "referred@example.com", "password": "correct-horse-battery"})
    from app.services import email

    token = [m for m in email.outbox() if m["to"] == "referred@example.com"][-1]["body"].split("token=")[1].split()[0]
    buyer.post("/api/v1/auth/verify-email", json={"token": token})
    buy(buyer, listing_id)

    affiliate = (NET - CREATOR) * 1000 // 10000
    assert creator.get("/api/v1/earnings/summary").json()["pending_cents"] == CREATOR  # unchanged
    s = partner.get("/api/v1/earnings/summary").json()
    assert s["pending_cents"] == affiliate and s["by_kind"] == {"affiliate_commission": affiliate}
    me = partner.get("/api/v1/referrals/me").json()
    assert me["referred_accounts"] == 1 and me["paying_customers"] == 1
    with SessionLocal() as db:
        assert ledger.balance(db, "platform_revenue", "USD") == NET - CREATOR - affiliate
    reconcile_ok()


def test_referral_ip_velocity_rejected():
    partner = register(new_client(), "partner@example.com")
    code = partner.post("/api/v1/referrals/code").json()["code"]
    for i in range(4):
        new_client().post("/api/v1/auth/register", json={"email": f"farm{i}@example.com", "password": "correct-horse-battery",
                                                         "display_name": f"Farm {i}", "accept_terms": True,
                                                         "referral_code": code})
    me = partner.get("/api/v1/referrals/me").json()
    assert me["referred_accounts"] == 4 and me["rejected_referrals"] == 1


def test_refund_before_payout_reverses_everything():
    creator, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buy(buyer, listing_id)
    cert = order["lines"][0]["certificate_number"]
    dl = buyer.post(f"/api/v1/licenses/{cert}/download").json()["download_url"]
    fin = login_as("cfo@example.com", "finance_admin")
    r = fin.post(f"/api/v1/admin/finance/orders/{order['id']}/refund", json={"reason": "requested_by_customer"})
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert get_provider().refunds[0]["amount"] == PRICE
    assert new_client().get(dl).status_code == 403  # license no longer permits downloads
    assert new_client().get(f"/api/v1/licenses/verify/{cert}").json()["status"] == "refunded"
    s = creator.get("/api/v1/earnings/summary").json()
    assert s["pending_cents"] == 0 and s["lifetime_cents"] == 0
    # Refunding again is rejected.
    assert fin.post(f"/api/v1/admin/finance/orders/{order['id']}/refund", json={}).status_code == 409
    with SessionLocal() as db:
        assert ledger.balance(db, ledger.creator_payable(user_id("seller@example.com")), "USD") == 0
        assert ledger.balance(db, "clearing:fake", "USD") == -FEE  # provider kept its fee
        assert ledger.balance(db, "platform_revenue", "USD") == 0
    reconcile_ok()


def test_payouts_hold_onboarding_clawback_and_failures():
    creator, _, listing_id = listed_asset()
    buyers = [register(new_client(), f"buyer{i}@example.com") for i in range(2)]
    orders = [buy(b, listing_id) for b in buyers]
    fin = login_as("cfo@example.com", "finance_admin")

    # Inside the hold period nothing is paid.
    assert fin.post("/api/v1/admin/finance/payouts/run").json()["created"] == 0
    make_available()
    # No payout account yet: skipped, but earnings become available.
    result = fin.post("/api/v1/admin/finance/payouts/run").json()
    assert result["created"] == 0 and result["skipped"] == 1
    assert creator.get("/api/v1/earnings/summary").json()["available_cents"] == 2 * CREATOR

    onboard = creator.post("/api/v1/payouts/account/onboard", json={"country": "US"}).json()
    assert onboard["account"]["status"] == "enabled"

    provider = get_provider()
    provider.fail_transfers = True
    result = fin.post("/api/v1/admin/finance/payouts/run").json()
    assert result["failed"] == 1
    assert creator.get("/api/v1/earnings/summary").json()["available_cents"] == 2 * CREATOR
    reconcile_ok()

    provider.fail_transfers = False
    result = fin.post("/api/v1/admin/finance/payouts/run").json()
    assert result["sent"] == 1 and provider.transfers[-1]["amount"] == 2 * CREATOR
    s = creator.get("/api/v1/earnings/summary").json()
    assert s["paid_cents"] == 2 * CREATOR and s["available_cents"] == 0
    assert [p["status"] for p in creator.get("/api/v1/payouts").json()] == ["sent", "failed"]
    reconcile_ok()

    # Refund after payout: a clawback nets against future earnings.
    fin.post(f"/api/v1/admin/finance/orders/{orders[0]['id']}/refund", json={"reason": "rights_issue"})
    s = creator.get("/api/v1/earnings/summary").json()
    assert s["available_cents"] == -CREATOR
    assert any(r["is_clawback"] for r in creator.get("/api/v1/earnings").json()["items"])
    reconcile_ok()

    # Negative balance blocks payouts until new sales cover it.
    assert fin.post("/api/v1/admin/finance/payouts/run").json()["created"] == 0
    limiter.reset()  # many sign-ups from one test IP
    for i in range(2, 4):
        buy(register(new_client(), f"buyer{i}@example.com"), listing_id)
    make_available()
    fin.post("/api/v1/admin/finance/payouts/run")
    assert provider.transfers[-1]["amount"] == CREATOR  # 2 new sales minus the clawback
    reconcile_ok()

    csv_text = creator.get("/api/v1/earnings/statement.csv", params={"month": datetime.now(UTC).strftime("%Y-%m")}).text
    assert "stock_license (clawback)" in csv_text and "model_a_nonexclusive v1" in csv_text


def test_transfer_reversed_returns_funds_to_payee():
    creator, _, listing_id = listed_asset()
    buy(register(new_client(), "buyer@example.com"), listing_id)
    make_available()
    creator.post("/api/v1/payouts/account/onboard", json={"country": "US"})
    fin = login_as("cfo@example.com", "finance_admin")
    fin.post("/api/v1/admin/finance/payouts/run")
    transfer_id = get_provider().transfers[-1]["id"]
    with SessionLocal() as db:
        assert ps.handle_event(db, get_provider(), ProviderEvent("evt_tr", "transfer.reversed", {"id": transfer_id})) \
            == "payout_reversed"
        db.commit()
    assert creator.get("/api/v1/earnings/summary").json()["available_cents"] == CREATOR
    reconcile_ok()


def test_chargeback_and_dispute_won():
    creator, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buy(buyer, listing_id)
    payment_id = f"fake_pi_{order['id']}"
    provider = get_provider()
    with SessionLocal() as db:
        out = ps.handle_event(db, provider, ProviderEvent("evt_dp1", "charge.dispute.created", {
            "id": "dp_1", "payment_intent": payment_id, "balance_transactions": [{"fee": 1500}]}))
        db.commit()
    assert out == "disputed"
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "disputed"
    assert creator.get("/api/v1/earnings/summary").json()["lifetime_cents"] == 0
    reconcile_ok()
    with SessionLocal() as db:
        out = ps.handle_event(db, provider, ProviderEvent("evt_dp2", "charge.dispute.closed", {
            "id": "dp_1", "payment_intent": payment_id, "status": "won"}))
        db.commit()
        assert ledger.balance(db, "refund_losses", "USD") == 1500
    assert out == "dispute_won"
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "paid"
    assert creator.get("/api/v1/earnings/summary").json()["pending_cents"] == CREATOR
    cert = buyer.get(f"/api/v1/orders/{order['id']}").json()["lines"][0]["certificate_number"]
    assert new_client().get(f"/api/v1/licenses/verify/{cert}").json()["status"] == "active"
    reconcile_ok()


def test_external_full_refund_recorded():
    _, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    order = buy(buyer, listing_id)
    with SessionLocal() as db:
        out = ps.handle_event(db, get_provider(), ProviderEvent("evt_rf", "charge.refunded", {
            "id": "ch_1", "payment_intent": f"fake_pi_{order['id']}", "amount": PRICE, "amount_refunded": PRICE}))
        db.commit()
    assert out == "refunded"
    assert buyer.get(f"/api/v1/orders/{order['id']}").json()["status"] == "refunded"
    reconcile_ok()


def test_finance_overview_and_permissions():
    _, _, listing_id = listed_asset()
    buyer = register(new_client(), "buyer@example.com")
    buy(buyer, listing_id)
    buy(buyer, listing_id)
    assert register(new_client(), "nobody@example.com").get("/api/v1/admin/finance/overview").status_code == 403
    fin = login_as("cfo@example.com", "finance_admin")
    o = fin.get("/api/v1/admin/finance/overview").json()
    assert o["gmv_cents"] == 2 * PRICE and o["orders"] == 2 and o["paying_customers"] == 1
    assert o["repeat_customer_rate"] == 1.0 and o["creator_earnings_cents"] == 2 * CREATOR
    assert fin.get("/api/v1/admin/finance/orders").json()["total"] == 2
    assert fin.post("/api/v1/admin/finance/reconciliation/run").json()["status"] == "ok"
    codes = {a["code"].split(":")[0] for a in fin.get("/api/v1/admin/finance/ledger/accounts").json()}
    assert {"clearing", "creator_payable", "platform_revenue", "processing_fees"} <= codes


def test_ledger_rejects_unbalanced_and_is_idempotent():
    with SessionLocal() as db:
        with pytest.raises(ledger.LedgerError):
            ledger.post(db, ledger.JournalKind.adjustment, "bad", "test", "1", "bad", "USD",
                        [ledger.dr("platform_revenue", 100), ledger.cr("tax_payable", 99)])
        j1 = ledger.post(db, ledger.JournalKind.adjustment, "k1", "test", "1", "ok", "USD",
                         [ledger.dr("processing_fees", 100), ledger.cr("clearing:fake", 100)])
        j2 = ledger.post(db, ledger.JournalKind.adjustment, "k1", "test", "1", "ok", "USD",
                         [ledger.dr("processing_fees", 100), ledger.cr("clearing:fake", 100)])
        assert j1.id == j2.id and ledger.balance(db, "processing_fees", "USD") == 100
        assert db.scalar(select(LedgerAccount).where(LedgerAccount.code == "processing_fees")).account_type.value == "expense"


def test_prorate_exact():
    assert ps.prorate(100, [1, 1, 1]) == [34, 33, 33]
    assert sum(ps.prorate(997, [2900, 14900, 100])) == 997
    assert ps.prorate(0, [5, 5]) == [0, 0]


# --- Stripe adapter (no network) ------------------------------------------------------------

def stripe_signature(payload: str, secret: str) -> str:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_stripe_webhook_signature_verification():
    provider = StripeProvider("sk_test_x", "whsec_test")
    payload = json.dumps({"id": "evt_1", "object": "event", "type": "checkout.session.completed",
                          "data": {"object": {"id": "cs_1", "object": "checkout.session", "payment_status": "paid"}}})
    event = provider.parse_webhook(payload.encode(), stripe_signature(payload, "whsec_test"))
    assert event.id == "evt_1" and event.data["id"] == "cs_1"
    with pytest.raises(PaymentProviderError):
        provider.parse_webhook(payload.encode(), stripe_signature(payload, "whsec_wrong"))
    two = StripeProvider("sk_test_x", "whsec_platform, whsec_connect")
    assert two.parse_webhook(payload.encode(), stripe_signature(payload, "whsec_connect")).id == "evt_1"


def test_stripe_payment_details_and_calls(monkeypatch):
    import stripe

    calls = {}

    def fake_retrieve(**kw):
        calls["retrieve"] = kw
        return {"id": "cs_1", "payment_status": "paid", "currency": "usd", "amount_total": 3132,
                "total_details": {"amount_tax": 232},
                "payment_intent": {"id": "pi_1", "latest_charge": {"balance_transaction": {"fee": 121}}}}

    class Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def fake_create(**kw):
        calls["create"] = kw
        return Obj(id="cs_1", url="https://checkout.stripe.com/c/pay/cs_1")

    monkeypatch.setattr(stripe.checkout.Session, "retrieve", fake_retrieve)
    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)
    provider = StripeProvider("sk_test_x", "whsec_test", tax_enabled=True)
    details = provider.payment_details("cs_1")
    assert (details.payment_id, details.amount_total_cents, details.amount_tax_cents, details.fee_cents) == \
        ("pi_1", 3132, 232, 121)
    assert calls["retrieve"]["expand"] == ["payment_intent.latest_charge.balance_transaction"]
    from app.services.payments import CheckoutItem

    session = provider.create_checkout(order_id="o1", currency="USD", items=[CheckoutItem("A", "B", 2900)],
                                       customer_email="b@example.com", success_url="s", cancel_url="c",
                                       idempotency_key="checkout:o1")
    assert session.url.startswith("https://checkout.stripe.com")
    assert calls["create"]["idempotency_key"] == "checkout:o1"
    assert calls["create"]["automatic_tax"] == {"enabled": True}
    assert calls["create"]["payment_intent_data"]["transfer_group"] == "order_o1"
    assert calls["create"]["line_items"][0]["price_data"]["unit_amount"] == 2900


def test_stripe_errors_are_wrapped(monkeypatch):
    import stripe

    def boom(**kw):
        raise stripe.APIConnectionError("network down")

    monkeypatch.setattr(stripe.Transfer, "create", boom)
    with pytest.raises(PaymentProviderError):
        StripeProvider("sk_test_x", "whsec").transfer(amount_cents=100, currency="USD", destination="acct_1",
                                                      idempotency_key="k", description="d", metadata={})
    with pytest.raises(PaymentProviderError):
        StripeProvider("", "").refund(payment_id="pi", amount_cents=1, idempotency_key="k", metadata={})


def test_free_distribution_media_cannot_be_sold():
    creator = register(new_client(), "seller@example.com")
    become_creator(creator, "seller")
    asset = upload_photo(creator, distribution="free")
    r = creator.put(f"/api/v1/media/{asset['id']}/pricing",
                    json={"prices": [{"license_code": "standard_commercial", "price_cents": PRICE}]})
    assert r.status_code == 400
    r = creator.put(f"/api/v1/media/{asset['id']}/pricing", json={"free_license_code": "free_commercial"})
    assert r.status_code == 200


def test_statement_csv_neutralizes_formulas():
    from app.api.v1.earnings import _cell

    assert _cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert _cell("Sunset") == "Sunset"


@pytest.mark.skipif(not __import__("os").environ.get("TEST_DATABASE_URL"), reason="PostgreSQL advisory lock")
def test_concurrent_payout_run_is_refused():
    from sqlalchemy import text

    from app.core.database import engine

    with SessionLocal() as db:
        assert "busy" not in payout_service.run_payouts(db, get_provider())  # lock released afterwards
        with engine.connect() as holder:
            assert holder.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": payout_service.PAYOUT_LOCK_ID})
            try:
                assert payout_service.run_payouts(db, get_provider()) == {"busy": True}
            finally:
                holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": payout_service.PAYOUT_LOCK_ID})
                holder.commit()
        assert "busy" not in payout_service.run_payouts(db, get_provider())

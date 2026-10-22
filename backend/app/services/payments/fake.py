"""Deterministic fake provider for local development and tests.

It never moves money. Checkout redirects to a dev-only page in the web app
that "pays" by calling ``POST /api/v1/payments/dev/complete/{order_id}``,
which feeds a synthetic ``checkout.session.completed`` event through the same
webhook handler Stripe uses. Refused in production by settings validation.
"""

from __future__ import annotations

import json
import uuid

from app.core.config import get_settings
from app.services.payments.base import (
    AccountState,
    CheckoutItem,
    CheckoutSession,
    PaymentDetails,
    PaymentProviderError,
    ProviderEvent,
)

# Mirrors a typical card rate so ledger flows can be exercised realistically.
FEE_BPS, FEE_FIXED = 290, 30


def fake_fee(total_cents: int) -> int:
    return (total_cents * FEE_BPS + 5_000) // 10_000 + FEE_FIXED if total_cents else 0


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.fail_transfers = False
        self.transfers: list[dict] = []
        self.refunds: list[dict] = []

    def create_checkout(self, *, order_id, currency, items: list[CheckoutItem], customer_email, success_url,
                        cancel_url, idempotency_key) -> CheckoutSession:
        session_id = f"fake_cs_{order_id}"
        total = sum(i.unit_amount_cents for i in items)
        self.sessions[session_id] = {"order_id": order_id, "currency": currency, "total": total}
        url = f"{get_settings().public_web_url}/checkout/dev-pay?order={order_id}"
        return CheckoutSession(id=session_id, url=url)

    def payment_details(self, session_id: str) -> PaymentDetails:
        # Sessions created in another process (dev server restart) are rebuilt
        # by the caller from the order; see payment_service.
        info = self.sessions.get(session_id)
        if not info:
            raise PaymentProviderError("unknown fake session")
        return PaymentDetails(session_id=session_id, payment_id=f"fake_pi_{info['order_id']}", paid=True,
                              currency=info["currency"], amount_total_cents=info["total"], amount_tax_cents=0,
                              fee_cents=fake_fee(info["total"]))

    def remember_session(self, session_id: str, order_id: str, currency: str, total: int) -> None:
        self.sessions[session_id] = {"order_id": order_id, "currency": currency, "total": total}

    def parse_webhook(self, payload: bytes, signature: str | None) -> ProviderEvent:
        if get_settings().is_production:
            raise PaymentProviderError("fake provider is disabled in production")
        body = json.loads(payload)
        return ProviderEvent(id=body["id"], type=body["type"], data=body["data"]["object"])

    def create_connected_account(self, *, email, country, user_id) -> str:
        return f"fake_acct_{user_id}"

    def onboarding_link(self, account_id, *, refresh_url, return_url) -> str:
        return return_url

    def account_state(self, account_id) -> AccountState:
        return AccountState(details_submitted=True, payouts_enabled=True, country="US", requirements_due=[])

    def transfer(self, *, amount_cents, currency, destination, idempotency_key, description, metadata) -> str:
        if self.fail_transfers:
            raise PaymentProviderError("simulated transfer failure")
        existing = next((t for t in self.transfers if t["idempotency_key"] == idempotency_key), None)
        if existing:
            return existing["id"]
        tid = f"fake_tr_{uuid.uuid4().hex[:16]}"
        self.transfers.append({"id": tid, "amount": amount_cents, "currency": currency, "destination": destination,
                               "idempotency_key": idempotency_key})
        return tid

    def refund(self, *, payment_id, amount_cents, idempotency_key, metadata) -> str:
        existing = next((r for r in self.refunds if r["idempotency_key"] == idempotency_key), None)
        if existing:
            return existing["id"]
        rid = f"fake_re_{uuid.uuid4().hex[:16]}"
        self.refunds.append({"id": rid, "payment_id": payment_id, "amount": amount_cents,
                             "idempotency_key": idempotency_key})
        return rid

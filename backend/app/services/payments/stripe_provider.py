"""Stripe Checkout + Connect Express adapter.

Model: *separate charges and transfers*. The platform account receives the
buyer's payment; after the hold period, transfers go to each payee's Express
connected account (creators, affiliates). Card data never touches our servers.
"""

from __future__ import annotations

import stripe

from app.services.payments.base import (
    AccountState,
    BalanceActivity,
    CheckoutItem,
    CheckoutSession,
    PaymentDetails,
    PaymentProviderError,
    ProviderEvent,
)


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class StripeProvider:
    name = "stripe"

    def __init__(self, api_key: str, webhook_secret: str, tax_enabled: bool = False):
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.tax_enabled = tax_enabled

    def _call(self, fn, **params):
        if not self.api_key:
            raise PaymentProviderError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
        try:
            return fn(api_key=self.api_key, **params)
        except stripe.StripeError as exc:  # network, card, invalid request, auth...
            raise PaymentProviderError(getattr(exc, "user_message", None) or str(exc)) from exc

    def create_checkout(self, *, order_id, currency, items: list[CheckoutItem], customer_email, success_url,
                        cancel_url, idempotency_key) -> CheckoutSession:
        params = {
            "mode": "payment",
            "client_reference_id": order_id,
            "customer_email": customer_email,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": item.unit_amount_cents,
                        # Digital license; Stripe Tax uses this product tax code.
                        "product_data": {"name": item.name[:250], "description": item.description[:500],
                                         "tax_code": item.tax_code},
                        "tax_behavior": "exclusive",
                    },
                }
                for item in items
            ],
            "metadata": {"order_id": order_id},
            "payment_intent_data": {"transfer_group": f"order_{order_id}", "metadata": {"order_id": order_id}},
        }
        if self.tax_enabled:
            params["automatic_tax"] = {"enabled": True}
            params["billing_address_collection"] = "required"
        session = self._call(stripe.checkout.Session.create, idempotency_key=idempotency_key, **params)
        return CheckoutSession(id=session.id, url=session.url)

    def payment_details(self, session_id: str) -> PaymentDetails:
        session = self._call(stripe.checkout.Session.retrieve, id=session_id,
                             expand=["payment_intent.latest_charge.balance_transaction"])
        intent = _get(session, "payment_intent")
        charge = _get(intent, "latest_charge")
        txn = _get(charge, "balance_transaction")
        totals = _get(session, "total_details") or {}
        line_tax = None
        if int(_get(totals, "amount_tax", 0) or 0):
            items = self._call(stripe.checkout.Session.list_line_items, session=session_id, limit=100)
            line_tax = [int(_get(i, "amount_tax", 0) or 0) for i in _get(items, "data", [])]
        return PaymentDetails(
            session_id=session_id,
            payment_id=_get(intent, "id") or str(intent or ""),
            paid=_get(session, "payment_status") == "paid",
            currency=str(_get(session, "currency", "")).upper(),
            amount_total_cents=int(_get(session, "amount_total", 0) or 0),
            amount_tax_cents=int(_get(totals, "amount_tax", 0) or 0),
            fee_cents=int(_get(txn, "fee", 0) or 0),
            line_tax_cents=line_tax,
            charge_id=_get(charge, "id"),
        )

    def parse_webhook(self, payload: bytes, signature: str | None) -> ProviderEvent:
        # Comma-separated: the platform endpoint and the Connect endpoint each
        # have their own signing secret.
        secrets = [s.strip() for s in self.webhook_secret.split(",") if s.strip()]
        if not secrets:
            raise PaymentProviderError("STRIPE_WEBHOOK_SECRET is not configured")
        event = None
        for secret in secrets:
            try:
                event = stripe.Webhook.construct_event(payload, signature or "", secret)
                break
            except stripe.SignatureVerificationError:
                continue
            except ValueError as exc:
                raise PaymentProviderError("Malformed webhook payload") from exc
        if event is None:
            raise PaymentProviderError("Invalid webhook signature")
        data = event["data"]["object"]
        return ProviderEvent(id=event["id"], type=event["type"],
                             data=data.to_dict() if hasattr(data, "to_dict") else dict(data))

    def create_connected_account(self, *, email, country, user_id) -> str:
        account = self._call(
            stripe.Account.create,
            type="express",
            email=email,
            country=country,
            capabilities={"transfers": {"requested": True}},
            business_profile={"product_description": "Licensing photography and video through the marketplace"},
            metadata={"user_id": user_id},
            idempotency_key=f"connect-account:{user_id}",
        )
        return account.id

    def onboarding_link(self, account_id, *, refresh_url, return_url) -> str:
        link = self._call(stripe.AccountLink.create, account=account_id, refresh_url=refresh_url,
                          return_url=return_url, type="account_onboarding")
        return link.url

    def account_state(self, account_id) -> AccountState:
        acct = self._call(stripe.Account.retrieve, id=account_id)
        return self.state_from_account(acct)

    @staticmethod
    def state_from_account(acct) -> AccountState:
        req = _get(acct, "requirements") or {}
        return AccountState(
            details_submitted=bool(_get(acct, "details_submitted")),
            payouts_enabled=bool(_get(acct, "payouts_enabled")),
            country=_get(acct, "country"),
            requirements_due=list(_get(req, "currently_due") or []),
        )

    def transfer(self, *, amount_cents, currency, destination, idempotency_key, description, metadata) -> str:
        transfer = self._call(stripe.Transfer.create, amount=amount_cents, currency=currency.lower(),
                              destination=destination, description=description[:300], metadata=metadata,
                              idempotency_key=idempotency_key)
        return transfer.id

    def refund(self, *, payment_id, amount_cents, idempotency_key, metadata) -> str:
        refund = self._call(stripe.Refund.create, payment_intent=payment_id, amount=amount_cents,
                            metadata=metadata, idempotency_key=idempotency_key)
        return refund.id

    def balance_activity(self, since: int, until: int) -> list[BalanceActivity]:
        page = self._call(stripe.BalanceTransaction.list, created={"gte": since, "lt": until},
                          expand=["data.source"], limit=100)
        out = []
        for txn in page.auto_paging_iter():
            source = _get(txn, "source")
            kind = _get(txn, "type")
            amount = int(_get(txn, "amount", 0) or 0)
            base = {"id": _get(txn, "id"), "fee_cents": int(_get(txn, "fee", 0) or 0),
                    "currency": str(_get(txn, "currency", "")).upper(), "created": int(_get(txn, "created", 0) or 0)}
            if kind in ("charge", "payment"):
                out.append(BalanceActivity(type="charge", amount_cents=amount,
                                           payment_id=_get(source, "payment_intent"), **base))
            elif kind in ("refund", "payment_refund"):
                out.append(BalanceActivity(type="refund", amount_cents=-amount,
                                           payment_id=_get(source, "payment_intent"), **base))
            elif kind == "transfer":
                out.append(BalanceActivity(type="transfer", amount_cents=-amount,
                                           transfer_id=_get(source, "id") or source, **base))
            else:
                out.append(BalanceActivity(type="other", amount_cents=amount, **base))
        return out

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class PaymentProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckoutItem:
    name: str
    description: str
    unit_amount_cents: int
    tax_code: str = "txcd_10000000"  # electronically supplied services (licenses)


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class PaymentDetails:
    """What actually happened at the provider for a completed checkout."""

    session_id: str
    payment_id: str  # Stripe PaymentIntent id
    paid: bool
    currency: str
    amount_total_cents: int
    amount_tax_cents: int
    fee_cents: int  # processing fee charged by the provider
    line_tax_cents: list[int] | None = None  # per checkout line, in order, when the provider reports it
    charge_id: str | None = None


@dataclass(frozen=True)
class ProviderEvent:
    id: str
    type: str
    data: dict
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AccountState:
    details_submitted: bool
    payouts_enabled: bool
    country: str | None
    requirements_due: list[str]


@dataclass(frozen=True)
class BalanceActivity:
    """One movement in the provider balance, normalized for reconciliation."""

    id: str
    type: str  # charge | refund | transfer | other
    amount_cents: int  # positive for charges, positive magnitude for refunds/transfers
    fee_cents: int
    currency: str
    payment_id: str | None = None  # charges and refunds
    transfer_id: str | None = None  # transfers
    created: int = 0  # unix seconds


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, *, order_id: str, currency: str, items: list[CheckoutItem], customer_email: str,
                        success_url: str, cancel_url: str, idempotency_key: str) -> CheckoutSession: ...

    def payment_details(self, session_id: str) -> PaymentDetails: ...

    def parse_webhook(self, payload: bytes, signature: str | None) -> ProviderEvent: ...

    def create_connected_account(self, *, email: str, country: str, user_id: str) -> str: ...

    def onboarding_link(self, account_id: str, *, refresh_url: str, return_url: str) -> str: ...

    def account_state(self, account_id: str) -> AccountState: ...

    def transfer(self, *, amount_cents: int, currency: str, destination: str, idempotency_key: str,
                 description: str, metadata: dict) -> str: ...

    def refund(self, *, payment_id: str, amount_cents: int, idempotency_key: str, metadata: dict) -> str: ...

    def balance_activity(self, since: int, until: int) -> list[BalanceActivity]: ...

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrderItemIn(BaseModel):
    price_listing_id: uuid.UUID
    licensee_name: str | None = Field(default=None, max_length=200)


class OrderIn(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")


class OrderLineOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    asset_title: str
    thumbnail_url: str | None
    license_name: str
    size_tier: str
    licensee_name: str
    unit_price_cents: int
    tax_cents: int
    status: str
    certificate_number: str | None


class OrderOut(BaseModel):
    id: uuid.UUID
    status: str
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    checkout_url: str | None
    created_at: datetime
    paid_at: datetime | None
    lines: list[OrderLineOut]
    purpose: str = "license"
    project_id: uuid.UUID | None = None


class EarningOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    amount_cents: int
    currency: str
    available_at: datetime
    created_at: datetime
    asset_title: str
    license_name: str
    gross_cents: int
    rule: str
    explanation: list[str]
    is_clawback: bool


class EarningsSummary(BaseModel):
    currency: str
    pending_cents: int
    available_cents: int
    paid_cents: int
    lifetime_cents: int
    by_kind: dict[str, int]
    next_release_at: datetime | None
    hold_days: int
    min_payout_cents: int
    payout_account: dict | None


class PayoutOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    currency: str
    status: str
    created_at: datetime
    sent_at: datetime | None
    failure_reason: str | None


class RefundIn(BaseModel):
    line_ids: list[uuid.UUID] = Field(default_factory=list, description="Empty = every fulfilled line")
    reason: str = "requested_by_customer"
    note: str = Field(default="", max_length=2000)


class OnboardIn(BaseModel):
    country: str = Field(default="US", min_length=2, max_length=2)

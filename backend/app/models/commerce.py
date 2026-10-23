"""Phase 2 commerce: orders, financial events, double-entry ledger, royalty
allocations, earnings, payout accounts, payouts, refunds, referrals and
reconciliation runs.

Rules
-----
* Money is integer minor units plus an ISO currency code.
* ``financial_events``, ``ledger_journals`` and ``ledger_entries`` are
  append-only. Corrections are new reversing journals.
* Every journal must balance (sum of debits == sum of credits); the ledger
  service enforces it before insert and reconciliation re-checks it.
* Idempotency keys (provider event ids, our own journal keys, payout keys)
  carry UNIQUE constraints so retries cannot double-post.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk, str_enum, utcnow


class OrderPurpose(str, enum.Enum):
    license = "license"  # stock media license lines
    milestone = "milestone"  # funding a custom-production milestone
    gallery = "gallery"  # client-gallery add-on downloads and prints


class OrderStatus(str, enum.Enum):
    pending = "pending"  # awaiting payment
    paid = "paid"
    partially_refunded = "partially_refunded"
    refunded = "refunded"
    disputed = "disputed"
    canceled = "canceled"  # checkout expired or abandoned


class Order(UUIDPk, Timestamps, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("buyer_user_id", "idempotency_key"),
        CheckConstraint("subtotal_cents >= 0", name="subtotal_non_negative"),
        Index("ix_orders_status_created", "status", "created_at"),
    )

    # Null for gallery orders, where the client pays without an account.
    buyer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    buyer_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, "order_status"), default=OrderStatus.pending)
    currency: Mapped[str] = mapped_column(String(3))
    subtotal_cents: Mapped[int] = mapped_column(Integer)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer)
    processing_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(20))
    provider_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    affiliate_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[OrderPurpose] = mapped_column(
        str_enum(OrderPurpose, "order_purpose"), default=OrderPurpose.license, server_default="license"
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("milestones.id", ondelete="RESTRICT"), index=True
    )

    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="OrderLine.position"
    )


class OrderLineStatus(str, enum.Enum):
    pending = "pending"
    fulfilled = "fulfilled"
    refunded = "refunded"
    disputed = "disputed"


class OrderLine(UUIDPk, Base):
    __tablename__ = "order_lines"
    __table_args__ = (CheckConstraint("unit_price_cents > 0", name="price_positive"),)

    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="RESTRICT"), index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="RESTRICT"), index=True)
    price_listing_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("price_listings.id", ondelete="RESTRICT"))
    license_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("license_types.id", ondelete="RESTRICT"))
    contributor_agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contributor_agreements.id", ondelete="RESTRICT")
    )
    revenue_share_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_share_rules.id", ondelete="RESTRICT")
    )
    size_tier: Mapped[str] = mapped_column(String(20))
    licensee_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(300))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    processing_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # incl. tax
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[OrderLineStatus] = mapped_column(
        str_enum(OrderLineStatus, "order_line_status"), default=OrderLineStatus.pending
    )
    rights_grant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("rights_grants.id", ondelete="RESTRICT"))

    order: Mapped[Order] = relationship(back_populates="lines")


class FinancialEvent(UUIDPk, Base):
    """Raw provider event, stored once. The UNIQUE event id makes webhook
    processing idempotent."""

    __tablename__ = "financial_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id"),)

    provider: Mapped[str] = mapped_column(String(20))
    provider_event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    revenue = "revenue"
    expense = "expense"


class LedgerAccount(UUIDPk, Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (UniqueConstraint("code", "currency"),)

    code: Mapped[str] = mapped_column(String(120))  # e.g. creator_payable:<user id>
    name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[AccountType] = mapped_column(str_enum(AccountType, "ledger_account_type"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JournalKind(str, enum.Enum):
    sale = "sale"
    refund = "refund"
    dispute = "dispute"
    dispute_reinstated = "dispute_reinstated"
    payout = "payout"
    payout_reversal = "payout_reversal"
    adjustment = "adjustment"
    service_funding = "service_funding"
    service_release = "service_release"
    service_refund = "service_refund"
    gallery_sale = "gallery_sale"
    referral_bonus = "referral_bonus"


class LedgerJournal(UUIDPk, Base):
    __tablename__ = "ledger_journals"

    kind: Mapped[JournalKind] = mapped_column(str_enum(JournalKind, "journal_kind"))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    reference_type: Mapped[str] = mapped_column(String(40))
    reference_id: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(String(300))
    currency: Mapped[str] = mapped_column(String(3))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="journal", lazy="selectin")


class LedgerEntry(UUIDPk, Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "(debit_cents > 0 AND credit_cents = 0) OR (credit_cents > 0 AND debit_cents = 0)",
            name="one_sided_positive",
        ),
        Index("ix_ledger_entries_account", "account_id"),
    )

    journal_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ledger_journals.id", ondelete="RESTRICT"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"))
    debit_cents: Mapped[int] = mapped_column(Integer, default=0)
    credit_cents: Mapped[int] = mapped_column(Integer, default=0)
    memo: Mapped[str] = mapped_column(String(300), default="")

    journal: Mapped[LedgerJournal] = relationship(back_populates="entries")
    account: Mapped[LedgerAccount] = relationship(lazy="joined")


class RoyaltyAllocation(UUIDPk, Base):
    """The royalty engine's output for one order line, kept for statements."""

    __tablename__ = "royalty_allocations"

    order_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("order_lines.id", ondelete="RESTRICT"), unique=True
    )
    rule_code: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[int] = mapped_column(Integer)
    gross_cents: Mapped[int] = mapped_column(Integer)
    deductions: Mapped[dict] = mapped_column(JSON)
    net_cents: Mapped[int] = mapped_column(Integer)
    creator_bps: Mapped[int] = mapped_column(Integer)
    creator_pool_cents: Mapped[int] = mapped_column(Integer)
    platform_share_cents: Mapped[int] = mapped_column(Integer)
    affiliate_cents: Mapped[int] = mapped_column(Integer)
    platform_net_cents: Mapped[int] = mapped_column(Integer)
    allocations: Mapped[list] = mapped_column(JSON)
    explanation: Mapped[list] = mapped_column(JSON)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EarningKind(str, enum.Enum):
    stock_license = "stock_license"
    affiliate_commission = "affiliate_commission"
    service_milestone = "service_milestone"
    gallery_sale = "gallery_sale"
    referral_bonus = "referral_bonus"


class EarningStatus(str, enum.Enum):
    pending = "pending"  # inside the refund/chargeback hold window
    available = "available"  # eligible for the next payout
    paid = "paid"
    reversed = "reversed"  # refunded or charged back before payout


class Earning(UUIDPk, Base):
    """Payee sub-ledger. Mirrors the payable ledger accounts and adds the
    hold-period status used to decide what can be paid out.

    A refund of an earning that was already paid out creates a *negative*
    earning of the same kind (``reverses_earning_id`` set), which is netted
    against the payee's next payout."""

    __tablename__ = "earnings"
    __table_args__ = (Index("ix_earnings_payee_status", "payee_user_id", "status"),)

    payee_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[EarningKind] = mapped_column(str_enum(EarningKind, "earning_kind"))
    order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("order_lines.id", ondelete="RESTRICT"), index=True
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("milestones.id", ondelete="RESTRICT"), index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(  # gallery sales
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[EarningStatus] = mapped_column(str_enum(EarningStatus, "earning_status"), default=EarningStatus.pending)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    journal_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ledger_journals.id", ondelete="RESTRICT"))
    payout_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("payouts.id", ondelete="RESTRICT"), index=True)
    reverses_earning_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("earnings.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PayoutAccountStatus(str, enum.Enum):
    onboarding = "onboarding"
    enabled = "enabled"
    restricted = "restricted"


class PayoutAccount(UUIDPk, Timestamps, Base):
    __tablename__ = "payout_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_account_id: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[PayoutAccountStatus] = mapped_column(
        str_enum(PayoutAccountStatus, "payout_account_status"), default=PayoutAccountStatus.onboarding
    )
    country: Mapped[str | None] = mapped_column(String(2))
    details_submitted: Mapped[bool] = mapped_column(default=False)
    payouts_enabled: Mapped[bool] = mapped_column(default=False)
    requirements_due: Mapped[list] = mapped_column(JSON, default=list)


class PayoutStatus(str, enum.Enum):
    processing = "processing"
    sent = "sent"
    failed = "failed"
    reversed = "reversed"


class Payout(UUIDPk, Timestamps, Base):
    __tablename__ = "payouts"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="amount_positive"),)

    payee_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    payout_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payout_accounts.id", ondelete="RESTRICT"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[PayoutStatus] = mapped_column(str_enum(PayoutStatus, "payout_status"), default=PayoutStatus.processing)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    provider_transfer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    journal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ledger_journals.id", ondelete="RESTRICT"))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefundReason(str, enum.Enum):
    requested_by_customer = "requested_by_customer"
    duplicate = "duplicate"
    fraudulent = "fraudulent"
    rights_issue = "rights_issue"
    chargeback = "chargeback"
    project_canceled = "project_canceled"
    dispute_resolution = "dispute_resolution"
    price_adjustment = "price_adjustment"
    other = "other"


class Refund(UUIDPk, Base):
    __tablename__ = "refunds"

    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("order_lines.id", ondelete="RESTRICT"), index=True
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("milestones.id", ondelete="RESTRICT"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)  # amount + tax returned to the buyer
    # Per-account amounts reversed by this refund ({account code: cents}); lets a
    # final partial refund reverse exactly what is left.
    allocation: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[RefundReason] = mapped_column(str_enum(RefundReason, "refund_reason"))
    note: Mapped[str] = mapped_column(Text, default="")
    provider_refund_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    journal_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ledger_journals.id", ondelete="RESTRICT"))
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReferralCode(UUIDPk, Base):
    __tablename__ = "referral_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReferralStatus(str, enum.Enum):
    active = "active"
    rejected = "rejected"  # failed a fraud check


class Referral(UUIDPk, Base):
    """One referred account. Only a direct referrer is ever credited:
    there are no multi-level commissions."""

    __tablename__ = "referrals"

    referrer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    code: Mapped[str] = mapped_column(String(40))
    status: Mapped[ReferralStatus] = mapped_column(str_enum(ReferralStatus, "referral_status"), default=ReferralStatus.active)
    fraud_flags: Mapped[list] = mapped_column(JSON, default=list)
    signup_ip: Mapped[str | None] = mapped_column(String(45))
    attributed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    creator_bonus_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReconciliationRun(UUIDPk, Base):
    __tablename__ = "reconciliation_runs"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # ok | issues | error
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

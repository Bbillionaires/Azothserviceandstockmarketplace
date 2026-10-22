"""Licensing: license catalog, versioned agreements, revenue-share rules,
creator price listings, rights grants (license certificates) and download
entitlements.

Design notes
------------
* Agreement templates and revenue-share rules are *versioned and immutable*.
  A change is a new version; signed agreements keep pointing at the version
  the creator accepted, so administrators cannot retroactively alter terms.
* ``RightsGrant`` is the authoritative record of what a buyer may do with an
  asset. The rights-availability service checks it before any new grant so
  conflicting exclusive licenses cannot be issued.
* Money is stored as integer minor units (cents) plus an ISO currency code.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class LicenseType(UUIDPk, Base):
    """Buyer-facing license catalog entry (personal, editorial, commercial...)."""

    __tablename__ = "license_types"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    is_exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    allows_commercial_use: Mapped[bool] = mapped_column(Boolean, default=False)
    allows_editorial_use: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_attribution: Mapped[bool] = mapped_column(Boolean, default=False)
    # Usage categories conferred, checked by the rights-availability service.
    permitted_uses: Mapped[list[str]] = mapped_column(JSON, default=list)
    terms_version: Mapped[str] = mapped_column(String(20))
    terms_markdown: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RevenueModel(str, enum.Enum):
    nonexclusive = "nonexclusive"  # Model A
    exclusive = "exclusive"  # Model B
    free = "free"  # Model C


class RevenueShareRule(UUIDPk, Base):
    """Versioned commission configuration. Rows are never updated in place.

    All shares are basis points (1/100 of a percent, 10_000 = 100%).
    """

    __tablename__ = "revenue_share_rules"
    __table_args__ = (
        UniqueConstraint("code", "version"),
        CheckConstraint("creator_bps BETWEEN 0 AND 10000", name="creator_bps_range"),
        CheckConstraint("affiliate_bps_of_platform BETWEEN 0 AND 10000", name="affiliate_bps_range"),
    )

    code: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    revenue_model: Mapped[RevenueModel] = mapped_column(str_enum(RevenueModel, "revenue_model"))
    # Creator share for ordinary qualifying transactions.
    creator_bps: Mapped[int] = mapped_column(Integer)
    # Creator share for the initial exclusive-license transaction (Model B).
    initial_exclusive_creator_bps: Mapped[int | None] = mapped_column(Integer)
    # Affiliate commission, taken from the platform share (never the creator's).
    affiliate_bps_of_platform: Mapped[int] = mapped_column(Integer, default=0)
    # Which deductions reduce gross to "net licensing revenue". See
    # docs/LICENSING_AND_ROYALTIES.md for the definition.
    net_revenue_deductions: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LegalReviewStatus(str, enum.Enum):
    draft = "draft"
    under_review = "under_review"
    approved = "approved"
    retired = "retired"


class AgreementTemplate(UUIDPk, Base):
    """A versioned creator-platform contributor agreement (Model A/B/C)."""

    __tablename__ = "agreement_templates"
    __table_args__ = (UniqueConstraint("code", "version"),)

    code: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    revenue_model: Mapped[RevenueModel] = mapped_column(str_enum(RevenueModel, "agreement_revenue_model"))
    revenue_share_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_share_rules.id", ondelete="RESTRICT")
    )
    body_markdown: Mapped[str] = mapped_column(Text)
    body_sha256: Mapped[str] = mapped_column(String(64))
    # Default grant terms written into every acceptance of this version.
    territory: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["WORLDWIDE"])
    permitted_uses: Mapped[list[str]] = mapped_column(JSON, default=list)
    sublicensing_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    duration: Mapped[str] = mapped_column(String(40), default="perpetual")
    withdrawal_terms: Mapped[str] = mapped_column(Text, default="")
    legal_review_status: Mapped[LegalReviewStatus] = mapped_column(
        str_enum(LegalReviewStatus, "legal_review_status"), default=LegalReviewStatus.draft
    )
    legal_reviewed_by: Mapped[str | None] = mapped_column(String(200))
    legal_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revenue_share_rule: Mapped[RevenueShareRule] = relationship(lazy="joined")


class AgreementStatus(str, enum.Enum):
    active = "active"
    superseded = "superseded"
    terminated = "terminated"


class SignatureMethod(str, enum.Enum):
    clickwrap = "clickwrap"
    esign_provider = "esign_provider"


class ContributorAgreement(UUIDPk, Timestamps, Base):
    """A creator's executed acceptance of a specific agreement template version."""

    __tablename__ = "contributor_agreements"
    __table_args__ = (Index("ix_contributor_agreements_creator_status", "creator_id", "status"),)

    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agreement_templates.id", ondelete="RESTRICT")
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="RESTRICT"))
    signer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    signer_legal_name: Mapped[str] = mapped_column(String(200))
    rights_owner_name: Mapped[str] = mapped_column(String(200))
    # Terms frozen at signature time (copied from the template version).
    territory: Mapped[list[str]] = mapped_column(JSON)
    permitted_uses: Mapped[list[str]] = mapped_column(JSON)
    sublicensing_allowed: Mapped[bool] = mapped_column(Boolean)
    duration: Mapped[str] = mapped_column(String(40))
    signature_method: Mapped[SignatureMethod] = mapped_column(str_enum(SignatureMethod, "signature_method"))
    # IP, user agent, timestamp, document hash, e-sign envelope id, etc.
    signature_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[AgreementStatus] = mapped_column(
        str_enum(AgreementStatus, "agreement_status"), default=AgreementStatus.active
    )
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    termination_reason: Mapped[str | None] = mapped_column(Text)

    template: Mapped[AgreementTemplate] = relationship(lazy="joined")


class PriceListing(UUIDPk, Timestamps, Base):
    """A creator-set price for one asset × license type × size tier."""

    __tablename__ = "price_listings"
    __table_args__ = (
        UniqueConstraint("asset_id", "license_type_id", "size_tier"),
        CheckConstraint("price_cents >= 0", name="price_non_negative"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    license_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("license_types.id", ondelete="RESTRICT"))
    size_tier: Mapped[str] = mapped_column(String(20), default="original")  # web | hd | 4k | original
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subscription_credit_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    license_type: Mapped[LicenseType] = relationship(lazy="joined")


class GrantStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    revoked = "revoked"
    refunded = "refunded"


class GrantSource(str, enum.Enum):
    free_download = "free_download"
    purchase = "purchase"
    subscription = "subscription"
    exclusive_agreement = "exclusive_agreement"
    negotiated = "negotiated"


class RightsGrant(UUIDPk, Base):
    """A license issued to a buyer. Doubles as the license certificate record."""

    __tablename__ = "rights_grants"
    __table_args__ = (Index("ix_rights_grants_asset_status", "asset_id", "status"),)

    certificate_number: Mapped[str] = mapped_column(String(32), unique=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="RESTRICT"))
    license_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("license_types.id", ondelete="RESTRICT"))
    licensee_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    licensee_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    licensee_name: Mapped[str] = mapped_column(String(200))
    source: Mapped[GrantSource] = mapped_column(str_enum(GrantSource, "grant_source"))
    is_exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    territory: Mapped[list[str]] = mapped_column(JSON)
    permitted_uses: Mapped[list[str]] = mapped_column(JSON)
    size_tier: Mapped[str] = mapped_column(String(20), default="original")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None = perpetual
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    terms_version: Mapped[str] = mapped_column(String(20))
    # Immutable copy of the license terms, asset title and creator at issue.
    terms_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[GrantStatus] = mapped_column(str_enum(GrantStatus, "grant_status"), default=GrantStatus.active)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)

    license_type: Mapped[LicenseType] = relationship(lazy="joined")


class DownloadEntitlement(UUIDPk, Base):
    __tablename__ = "download_entitlements"

    rights_grant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rights_grants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"))
    max_downloads: Mapped[int] = mapped_column(Integer, default=10)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

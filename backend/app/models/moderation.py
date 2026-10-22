"""Moderation decisions, appeals, copyright complaints and the audit log."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, str_enum, utcnow


class ModerationAction(str, enum.Enum):
    approve = "approve"
    reject = "reject"
    request_changes = "request_changes"
    disable = "disable"
    restore = "restore"


class ModerationDecision(UUIDPk, Base):
    __tablename__ = "moderation_decisions"
    __table_args__ = (Index("ix_moderation_subject", "subject_type", "subject_id"),)

    subject_type: Mapped[str] = mapped_column(String(40))  # media_asset | creator_profile | ...
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action: Mapped[ModerationAction] = mapped_column(str_enum(ModerationAction, "moderation_action"))
    reason: Mapped[str] = mapped_column(Text, default="")
    # Automated signals (duplicate match, AI flags) shown to the moderator.
    # Advisory only: never conclusive proof of ownership or infringement.
    automated_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    moderator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppealStatus(str, enum.Enum):
    open = "open"
    upheld = "upheld"  # original decision stands
    overturned = "overturned"


class ContentAppeal(UUIDPk, Timestamps, Base):
    __tablename__ = "content_appeals"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("moderation_decisions.id", ondelete="CASCADE"), index=True
    )
    appellant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[AppealStatus] = mapped_column(str_enum(AppealStatus, "appeal_status"), default=AppealStatus.open)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class ComplaintStatus(str, enum.Enum):
    received = "received"
    under_review = "under_review"
    content_disabled = "content_disabled"
    counter_notice_received = "counter_notice_received"
    restored = "restored"
    rejected = "rejected"
    closed = "closed"


class CopyrightComplaint(UUIDPk, Timestamps, Base):
    """DMCA-style notice. Content is never removed automatically on receipt:
    a moderator reviews the notice for completeness first."""

    __tablename__ = "copyright_complaints"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    complainant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    complainant_name: Mapped[str] = mapped_column(String(200))
    complainant_email: Mapped[str] = mapped_column(String(320))
    complainant_address: Mapped[str] = mapped_column(Text)
    copyrighted_work_description: Mapped[str] = mapped_column(Text)
    good_faith_statement: Mapped[bool] = mapped_column(Boolean)
    accuracy_statement: Mapped[bool] = mapped_column(Boolean)
    electronic_signature: Mapped[str] = mapped_column(String(200))
    status: Mapped[ComplaintStatus] = mapped_column(
        str_enum(ComplaintStatus, "complaint_status"), default=ComplaintStatus.received
    )
    counter_notice: Mapped[dict | None] = mapped_column(JSON)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class AuditLog(UUIDPk, Base):
    """Append-only record of security- and money-relevant actions."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_subject", "subject_type", "subject_id"),
        Index("ix_audit_created", "created_at"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

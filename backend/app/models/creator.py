"""Creator storefronts and follows."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, str_enum, utcnow


class VerificationStatus(str, enum.Enum):
    unverified = "unverified"
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


# Professional categories a storefront can advertise. Stored as a JSON list so
# new categories (e.g. from the production-exchange addendum) need no migration.
PROFESSIONAL_CATEGORIES = [
    "photographer",
    "videographer",
    "filmmaker",
    "drone_operator",
    "editor",
    "retoucher",
    "colorist",
    "motion_designer",
    "sound_engineer",
    "director",
    "cinematographer",
    "production_studio",
    "media_agency",
    "copyright_owner",
]


class CreatorProfile(UUIDPk, Timestamps, Base):
    """A public storefront. Owned by one user; optionally fronts an organization."""

    __tablename__ = "creator_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    handle: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    headline: Mapped[str] = mapped_column(String(200), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    banner_url: Mapped[str | None] = mapped_column(String(500))
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    specialties: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Public, coarse location only: never a street address.
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    region: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    service_radius_km: Mapped[int | None] = mapped_column(Integer)
    remote_available: Mapped[bool] = mapped_column(Boolean, default=False)
    travel_available: Mapped[bool] = mapped_column(Boolean, default=False)
    website: Mapped[str | None] = mapped_column(String(255))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus, "verification_status"), default=VerificationStatus.unverified
    )
    is_emerging_talent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    follower_count: Mapped[int] = mapped_column(Integer, default=0)


class Follow(UUIDPk, Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("user_id", "creator_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("creator_profiles.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

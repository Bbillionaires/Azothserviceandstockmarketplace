"""Media assets, stored files, releases, copyright declarations, collections."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
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


class MediaType(str, enum.Enum):
    photo = "photo"
    video = "video"


class MediaStatus(str, enum.Enum):
    processing = "processing"
    pending_review = "pending_review"
    approved = "approved"
    changes_requested = "changes_requested"
    rejected = "rejected"
    # Disabled pending a copyright complaint; reversible.
    disabled = "disabled"
    withdrawn = "withdrawn"
    failed = "failed"


class Orientation(str, enum.Enum):
    horizontal = "horizontal"
    vertical = "vertical"
    square = "square"


class ScanStatus(str, enum.Enum):
    not_scanned = "not_scanned"
    clean = "clean"
    infected = "infected"
    error = "error"


MEDIA_CATEGORIES = [
    "aerial_drone",
    "architecture",
    "b_roll",
    "business_finance",
    "commercial",
    "documentary",
    "editorial",
    "entertainment",
    "food",
    "historical",
    "lifestyle",
    "motion_graphics",
    "nature_wildlife",
    "product",
    "real_estate",
    "sports",
    "technology",
    "transportation",
    "travel",
]


class MediaAsset(UUIDPk, Timestamps, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        Index("ix_media_assets_status_type", "status", "media_type"),
        Index("ix_media_assets_creator_status", "creator_id", "status"),
    )

    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="RESTRICT"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    contributor_agreement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contributor_agreements.id", ondelete="RESTRICT")
    )
    media_type: Mapped[MediaType] = mapped_column(str_enum(MediaType, "media_type"))
    status: Mapped[MediaStatus] = mapped_column(
        str_enum(MediaStatus, "media_status"), default=MediaStatus.processing
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Lower-cased, space-joined title/description/keywords used by the
    # portable search fallback; PostgreSQL additionally gets a tsvector index.
    search_text: Mapped[str] = mapped_column(Text, default="")

    orientation: Mapped[Orientation | None] = mapped_column(str_enum(Orientation, "orientation"))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    frame_rate: Mapped[float | None] = mapped_column(Float)
    resolution_label: Mapped[str | None] = mapped_column(String(10), index=True)  # SD, HD, 4K, 8K
    file_format: Mapped[str | None] = mapped_column(String(10))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(32), index=True)
    scan_status: Mapped[ScanStatus] = mapped_column(
        str_enum(ScanStatus, "scan_status"), default=ScanStatus.not_scanned
    )

    location_city: Mapped[str | None] = mapped_column(String(120))
    location_region: Mapped[str | None] = mapped_column(String(120))
    location_country: Mapped[str | None] = mapped_column(String(2), index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_editorial_only: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_materially_altered: Mapped[bool] = mapped_column(Boolean, default=False)
    has_model_release: Mapped[bool] = mapped_column(Boolean, default=False)
    has_property_release: Mapped[bool] = mapped_column(Boolean, default=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)

    view_count: Mapped[int] = mapped_column(Integer, default=0)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    processing_error: Mapped[str | None] = mapped_column(Text)

    files: Mapped[list["MediaFile"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", lazy="selectin"
    )

    def file(self, kind: "FileKind") -> "MediaFile | None":
        return next((f for f in self.files if f.kind == kind), None)


class FileKind(str, enum.Enum):
    original = "original"
    preview = "preview"  # watermarked, public
    thumbnail = "thumbnail"  # watermarked, public
    poster = "poster"  # video poster frame, watermarked, public


class MediaFile(UUIDPk, Base):
    """A stored binary for an asset. Originals always live in the private bucket."""

    __tablename__ = "media_files"
    __table_args__ = (UniqueConstraint("asset_id", "kind"),)

    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"))
    kind: Mapped[FileKind] = mapped_column(str_enum(FileKind, "file_kind"))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    asset: Mapped[MediaAsset] = relationship(back_populates="files")


class ReleaseType(str, enum.Enum):
    model = "model"
    property = "property"


class MediaRelease(UUIDPk, Base):
    __tablename__ = "media_releases"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    release_type: Mapped[ReleaseType] = mapped_column(str_enum(ReleaseType, "release_type"))
    subject_name: Mapped[str] = mapped_column(String(200))
    document_storage_key: Mapped[str | None] = mapped_column(String(500))
    signed_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CopyrightDeclaration(UUIDPk, Base):
    """The uploader's sworn statement about ownership, captured per asset."""

    __tablename__ = "copyright_declarations"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), unique=True
    )
    declarant_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    rights_owner_name: Mapped[str] = mapped_column(String(200))
    is_original_author: Mapped[bool] = mapped_column(Boolean)
    holds_necessary_rights: Mapped[bool] = mapped_column(Boolean)
    existing_licenses_disclosure: Mapped[str] = mapped_column(Text, default="")
    has_prior_exclusive_grant: Mapped[bool] = mapped_column(Boolean, default=False)
    declaration_version: Mapped[str] = mapped_column(String(20))
    declaration_text: Mapped[str] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Collection(UUIDPk, Timestamps, Base):
    __tablename__ = "collections"

    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_private: Mapped[bool] = mapped_column(Boolean, default=True)


class CollectionItem(UUIDPk, Base):
    __tablename__ = "collection_items"
    __table_args__ = (UniqueConstraint("collection_id", "asset_id"),)

    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Favorite(UUIDPk, Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "asset_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

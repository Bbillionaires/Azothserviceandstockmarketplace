"""Phase 3: custom production marketplace.

Requests (briefs and "Request This Shot"), invitations, service packages,
proposals, projects (bookings), milestones, deliverables, revision requests,
messaging, notifications, reviews, project disputes and client galleries.

Rights in commissioned work are negotiated per project and recorded on the
proposal and project. Nothing in this module adds deliverables to the stock
catalog: commissioned content is never licensed or resold automatically.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk, str_enum, utcnow

SERVICE_CATEGORIES = [
    "commercial_production",
    "documentary",
    "weddings",
    "corporate_video",
    "interviews",
    "podcasts",
    "music_videos",
    "real_estate",
    "drone_services",
    "product_photography",
    "social_media_content",
    "events",
    "sports",
    "hospitality",
    "news_editorial",
    "video_editing",
    "photo_editing",
    "animation",
    "motion_graphics",
    "short_films",
    "promotional_campaigns",
]


class RequestKind(str, enum.Enum):
    custom_project = "custom_project"
    shot_request = "shot_request"  # "Request This Shot": media that does not exist yet


class RightsType(str, enum.Enum):
    exclusive = "exclusive"
    nonexclusive = "nonexclusive"
    custom = "custom"


class RequestVisibility(str, enum.Enum):
    public = "public"
    invite_only = "invite_only"


class RequestStatus(str, enum.Enum):
    open = "open"
    awarded = "awarded"
    closed = "closed"
    canceled = "canceled"


class ProjectRequest(UUIDPk, Timestamps, Base):
    __tablename__ = "project_requests"
    __table_args__ = (
        Index("ix_project_requests_status_category", "status", "category"),
        CheckConstraint("budget_min_cents IS NULL OR budget_min_cents >= 0", name="budget_min_non_negative"),
        CheckConstraint(
            "budget_max_cents IS NULL OR budget_min_cents IS NULL OR budget_max_cents >= budget_min_cents",
            name="budget_range",
        ),
    )

    client_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[RequestKind] = mapped_column(str_enum(RequestKind, "request_kind"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    deliverables: Mapped[str] = mapped_column(Text, default="")
    reference_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    location_city: Mapped[str | None] = mapped_column(String(120), index=True)
    location_region: Mapped[str | None] = mapped_column(String(120))
    location_country: Mapped[str | None] = mapped_column(String(2), index=True)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_min_cents: Mapped[int | None] = mapped_column(Integer)
    budget_max_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    rights_preference: Mapped[RightsType] = mapped_column(str_enum(RightsType, "rights_preference"))
    visibility: Mapped[RequestVisibility] = mapped_column(
        str_enum(RequestVisibility, "request_visibility"), default=RequestVisibility.public
    )
    status: Mapped[RequestStatus] = mapped_column(str_enum(RequestStatus, "request_status"), default=RequestStatus.open)
    proposal_count: Mapped[int] = mapped_column(Integer, default=0)


class RequestInvitation(UUIDPk, Base):
    __tablename__ = "request_invitations"
    __table_args__ = (UniqueConstraint("request_id", "creator_id"),)

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("project_requests.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServicePackage(UUIDPk, Timestamps, Base):
    """A fixed-price offer on a storefront ("Real estate photo package")."""

    __tablename__ = "service_packages"
    __table_args__ = (CheckConstraint("price_cents >= 100", name="price_minimum"),)

    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), index=True)
    deliverables: Mapped[str] = mapped_column(Text, default="")
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    delivery_days: Mapped[int] = mapped_column(Integer)
    revisions_included: Mapped[int] = mapped_column(Integer, default=1)
    rights_type: Mapped[RightsType] = mapped_column(str_enum(RightsType, "package_rights_type"))
    rights_terms: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProposalStatus(str, enum.Enum):
    submitted = "submitted"
    withdrawn = "withdrawn"
    accepted = "accepted"
    declined = "declined"


class Proposal(UUIDPk, Timestamps, Base):
    """A creator's bid. Visible only to the requesting client and the bidder."""

    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("request_id", "creator_id"),
        CheckConstraint("total_cents >= 100", name="total_minimum"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("project_requests.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="RESTRICT"), index=True)
    cover_letter: Mapped[str] = mapped_column(Text)
    total_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    # [{title, description, amount_cents, due_in_days}], amounts sum to total_cents
    milestones: Mapped[list[dict]] = mapped_column(JSON)
    delivery_days: Mapped[int] = mapped_column(Integer)
    revisions_included: Mapped[int] = mapped_column(Integer, default=1)
    rights_type: Mapped[RightsType] = mapped_column(str_enum(RightsType, "proposal_rights_type"))
    rights_terms: Mapped[str] = mapped_column(Text)
    status: Mapped[ProposalStatus] = mapped_column(
        str_enum(ProposalStatus, "proposal_status"), default=ProposalStatus.submitted
    )


class ProjectStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    canceled = "canceled"
    disputed = "disputed"


class Project(UUIDPk, Timestamps, Base):
    """A booking between a client and a creator."""

    __tablename__ = "projects"

    client_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("project_requests.id", ondelete="RESTRICT"))
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("proposals.id", ondelete="RESTRICT"))
    package_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("service_packages.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    currency: Mapped[str] = mapped_column(String(3))
    total_cents: Mapped[int] = mapped_column(Integer)
    revisions_included: Mapped[int] = mapped_column(Integer, default=1)
    # Rights agreed for this project (snapshot from the accepted proposal or package).
    rights_type: Mapped[RightsType] = mapped_column(str_enum(RightsType, "project_rights_type"))
    rights_terms: Mapped[str] = mapped_column(Text)
    # Both sides' acceptance of the terms: who, when, from where.
    acceptance_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    commission_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_share_rules.id", ondelete="RESTRICT")
    )
    status: Mapped[ProjectStatus] = mapped_column(str_enum(ProjectStatus, "project_status"), default=ProjectStatus.active)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project", lazy="selectin", order_by="Milestone.position", cascade="all, delete-orphan"
    )


class MilestoneStatus(str, enum.Enum):
    unfunded = "unfunded"
    funded = "funded"  # client paid; funds held by the payment provider
    submitted = "submitted"  # creator delivered; awaiting client review
    revision_requested = "revision_requested"
    approved = "approved"  # released to the creator
    refunded = "refunded"
    canceled = "canceled"  # never funded
    disputed = "disputed"


class Milestone(UUIDPk, Timestamps, Base):
    __tablename__ = "milestones"
    __table_args__ = (CheckConstraint("amount_cents >= 100", name="amount_minimum"),)

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    amount_cents: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[MilestoneStatus] = mapped_column(
        str_enum(MilestoneStatus, "milestone_status"), default=MilestoneStatus.unfunded
    )
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    funded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_approve_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revisions_used: Mapped[int] = mapped_column(Integer, default=0)
    released_cents: Mapped[int] = mapped_column(Integer, default=0)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    # ``refunded_cents`` counts held funds returned before release (pre-tax);
    # ``reversed_release_cents`` counts released funds returned afterwards.
    reversed_release_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tax_refunded_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Outstanding released amounts by party (reduced by later refunds/chargebacks).
    affiliate_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    release_creator_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    release_affiliate_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    release_platform_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # What a card chargeback pulled back, so a won dispute can restore it exactly.
    chargeback_snapshot: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship(back_populates="milestones")


class Deliverable(UUIDPk, Base):
    """A file delivered for a milestone. Stored privately; never published to the catalog."""

    __tablename__ = "deliverables"

    milestone_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("milestones.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(500))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    # not_scanned until the malware-scan job runs for direct uploads
    scan_status: Mapped[str] = mapped_column(String(20), default="clean", server_default="clean")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RevisionRequest(UUIDPk, Base):
    __tablename__ = "revision_requests"

    milestone_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("milestones.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationKind(str, enum.Enum):
    direct = "direct"
    request = "request"  # client ↔ one bidder about a request (kept private from other bidders)
    project = "project"


class Conversation(UUIDPk, Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("kind", "subject_id", "pair_key"),)

    kind: Mapped[ConversationKind] = mapped_column(str_enum(ConversationKind, "conversation_kind"))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # request or project id
    # Sorted participant ids, so one conversation exists per pair and subject.
    pair_key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationParticipant(UUIDPk, Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(UUIDPk, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(UUIDPk, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ReviewDirection(str, enum.Enum):
    client_to_creator = "client_to_creator"
    creator_to_client = "creator_to_client"


class Review(UUIDPk, Base):
    """Verified review: only possible on a completed project, once per side."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("project_id", "direction"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    direction: Mapped[ReviewDirection] = mapped_column(str_enum(ReviewDirection, "review_direction"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="RESTRICT"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text, default="")
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # moderation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DisputeStatus(str, enum.Enum):
    open = "open"
    resolved_release = "resolved_release"
    resolved_refund = "resolved_refund"
    resolved_split = "resolved_split"
    withdrawn = "withdrawn"


class ProjectDispute(UUIDPk, Timestamps, Base):
    __tablename__ = "project_disputes"

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    milestone_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("milestones.id", ondelete="RESTRICT"), index=True)
    opened_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    previous_status: Mapped[str] = mapped_column(String(40))
    status: Mapped[DisputeStatus] = mapped_column(str_enum(DisputeStatus, "project_dispute_status"),
                                                  default=DisputeStatus.open)
    creator_share_bps: Mapped[int | None] = mapped_column(Integer)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GalleryStatus(str, enum.Enum):
    draft = "draft"
    shared = "shared"
    approved = "approved"  # client approved the selection
    archived = "archived"


class ClientGallery(UUIDPk, Timestamps, Base):
    """Private proofing gallery, separate from public stock listings."""

    __tablename__ = "client_galleries"

    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("creator_profiles.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    client_name: Mapped[str] = mapped_column(String(200), default="")
    client_email: Mapped[str | None] = mapped_column(String(320))
    access_token: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allow_downloads: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_limit: Mapped[int | None] = mapped_column(Integer)
    # Add-on sales: per-image digital download price (None = not for sale) and prints.
    download_price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    status: Mapped[GalleryStatus] = mapped_column(str_enum(GalleryStatus, "gallery_status"), default=GalleryStatus.draft)
    client_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GalleryItemStatus(str, enum.Enum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class GalleryItem(UUIDPk, Base):
    __tablename__ = "gallery_items"
    __table_args__ = (Index("ix_gallery_items_gallery_position", "gallery_id", "position"),)

    gallery_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client_galleries.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(10))
    status: Mapped[GalleryItemStatus] = mapped_column(
        str_enum(GalleryItemStatus, "gallery_item_status"), default=GalleryItemStatus.processing
    )
    original_key: Mapped[str | None] = mapped_column(String(500))
    original_content_type: Mapped[str | None] = mapped_column(String(100))
    preview_key: Mapped[str | None] = mapped_column(String(500))
    thumbnail_key: Mapped[str | None] = mapped_column(String(500))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    download_unlocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # purchased
    processing_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GalleryComment(UUIDPk, Base):
    __tablename__ = "gallery_comments"

    gallery_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client_galleries.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("gallery_items.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(20))  # client | creator
    body: Mapped[str] = mapped_column(Text)
    is_revision_request: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GalleryPrintOption(UUIDPk, Base):
    """A print product the creator fulfills themselves (e.g. "8×10 lustre print")."""

    __tablename__ = "gallery_print_options"
    __table_args__ = (CheckConstraint("price_cents >= 100", name="price_minimum"),)

    gallery_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client_galleries.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price_cents: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GalleryOrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    shipped = "shipped"  # all print items dispatched (digital-only orders go straight to paid)
    partially_refunded = "partially_refunded"
    refunded = "refunded"
    disputed = "disputed"
    canceled = "canceled"


class GalleryOrder(UUIDPk, Timestamps, Base):
    __tablename__ = "gallery_orders"

    gallery_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client_galleries.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), unique=True)
    client_name: Mapped[str] = mapped_column(String(200))
    client_email: Mapped[str] = mapped_column(String(320))
    shipping_address: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[GalleryOrderStatus] = mapped_column(
        str_enum(GalleryOrderStatus, "gallery_order_status"), default=GalleryOrderStatus.pending
    )
    commission_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_share_rules.id", ondelete="RESTRICT")
    )
    # Outstanding amounts by account after refunds ({code: cents}); set at payment.
    allocation: Mapped[dict] = mapped_column(JSON, default=dict)
    chargeback_snapshot: Mapped[dict | None] = mapped_column(JSON)
    carrier: Mapped[str | None] = mapped_column(String(60))
    tracking_number: Mapped[str | None] = mapped_column(String(120))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GalleryOrderItem(UUIDPk, Base):
    __tablename__ = "gallery_order_items"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 50", name="quantity_range"),)

    gallery_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("gallery_orders.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("gallery_items.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(10))  # digital | print
    print_option_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("gallery_print_options.id", ondelete="RESTRICT")
    )
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_cents: Mapped[int] = mapped_column(Integer)

"""Users, roles, organizations and one-time email tokens."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk, str_enum, utcnow


class UserStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    banned = "banned"
    deactivated = "deactivated"


class RoleCode(str, enum.Enum):
    """Permission roles. A user may hold several at once.

    Professional categories (photographer, drone operator, ...) are profile
    attributes, not permission roles; see ``CreatorProfile.categories``.
    """

    buyer = "buyer"
    creator = "creator"
    rights_owner = "rights_owner"
    affiliate = "affiliate"
    org_admin = "org_admin"
    moderator = "moderator"
    finance_admin = "finance_admin"
    admin = "admin"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[UserStatus] = mapped_column(str_enum(UserStatus, "user_status"), default=UserStatus.active)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Incrementing this invalidates every outstanding access token (logout-all,
    # password change, suspension).
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    country_code: Mapped[str | None] = mapped_column(String(2))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    referred_by_code: Mapped[str | None] = mapped_column(String(40))

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin", foreign_keys="UserRole.user_id"
    )

    @property
    def role_codes(self) -> set[str]:
        return {r.role.code for r in self.roles}

    def has_role(self, *codes: RoleCode | str) -> bool:
        wanted = {c.value if isinstance(c, RoleCode) else c for c in codes}
        return bool(self.role_codes & wanted)


class Role(UUIDPk, Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(255), default="")


class UserRole(UUIDPk, Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="RESTRICT"))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(lazy="joined")


class EmailTokenPurpose(str, enum.Enum):
    verify_email = "verify_email"
    reset_password = "reset_password"


class EmailToken(UUIDPk, Base):
    __tablename__ = "email_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[EmailTokenPurpose] = mapped_column(str_enum(EmailTokenPurpose, "email_token_purpose"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrganizationType(str, enum.Enum):
    production_studio = "production_studio"
    media_agency = "media_agency"
    corporate_buyer = "corporate_buyer"
    university = "university"
    film_club = "film_club"
    association = "association"
    vendor = "vendor"


class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    org_type: Mapped[OrganizationType] = mapped_column(str_enum(OrganizationType, "organization_type"))
    website: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(2))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))


class OrgMemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    student = "student"


class OrganizationMember(UUIDPk, Base):
    """Membership never transfers ownership of the member's own content."""

    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    member_role: Mapped[OrgMemberRole] = mapped_column(str_enum(OrgMemberRole, "org_member_role"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

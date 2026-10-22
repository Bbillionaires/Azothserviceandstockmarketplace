import re
import uuid

from pydantic import BaseModel, Field, field_validator

from app.models.creator import PROFESSIONAL_CATEGORIES
from app.schemas.common import ORM

HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
RESERVED_HANDLES = {"admin", "api", "search", "media", "creators", "login", "register", "dashboard", "support"}


class CreatorBase(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    headline: str = Field(default="", max_length=200)
    bio: str = Field(default="", max_length=5000)
    categories: list[str] = Field(default_factory=list, max_length=8)
    specialties: list[str] = Field(default_factory=list, max_length=20)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    service_radius_km: int | None = Field(default=None, ge=0, le=20000)
    remote_available: bool = False
    travel_available: bool = False
    website: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=500)
    banner_url: str | None = Field(default=None, max_length=500)
    is_emerging_talent: bool = False

    @field_validator("categories")
    @classmethod
    def known_categories(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(PROFESSIONAL_CATEGORIES)
        if unknown:
            raise ValueError(f"Unknown categories: {sorted(unknown)}")
        return v

    @field_validator("country_code")
    @classmethod
    def upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class CreatorCreate(CreatorBase):
    handle: str

    @field_validator("handle")
    @classmethod
    def valid_handle(cls, v: str) -> str:
        v = v.lower()
        if not HANDLE_RE.match(v) or v in RESERVED_HANDLES:
            raise ValueError("Handle must be 3-40 lowercase letters, digits or hyphens")
        return v


class CreatorUpdate(CreatorBase):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)  # type: ignore[assignment]


class CreatorOut(ORM):
    id: uuid.UUID
    handle: str
    display_name: str
    headline: str
    bio: str
    avatar_url: str | None
    banner_url: str | None
    categories: list[str]
    specialties: list[str]
    city: str | None
    region: str | None
    country_code: str | None
    service_radius_km: int | None
    remote_available: bool
    travel_available: bool
    website: str | None
    verification_status: str
    is_emerging_talent: bool
    is_featured: bool
    follower_count: int


class CreatorStats(BaseModel):
    approved_media: int
    total_downloads: int
    total_views: int

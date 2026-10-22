import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORM


class MediaFileOut(BaseModel):
    kind: str
    url: str
    content_type: str
    width: int | None
    height: int | None


class PriceOut(ORM):
    id: uuid.UUID
    license_code: str
    license_name: str
    size_tier: str
    price_cents: int
    currency: str
    subscription_credit_eligible: bool


class CreatorSummary(BaseModel):
    id: uuid.UUID
    handle: str
    display_name: str
    avatar_url: str | None
    verification_status: str


class MediaCard(BaseModel):
    id: uuid.UUID
    title: str
    media_type: str
    category: str
    orientation: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None
    resolution_label: str | None
    is_free: bool
    thumbnail_url: str | None
    preview_url: str | None
    creator: CreatorSummary
    starting_price_cents: int | None = None
    currency: str = "USD"


class MediaDetail(MediaCard):
    description: str
    keywords: list[str]
    status: str
    file_format: str | None
    file_size_bytes: int | None
    frame_rate: float | None
    location_city: str | None
    location_region: str | None
    location_country: str | None
    captured_at: datetime | None
    is_editorial_only: bool
    is_ai_generated: bool
    is_materially_altered: bool
    has_model_release: bool
    has_property_release: bool
    view_count: int
    download_count: int
    published_at: datetime | None
    created_at: datetime
    prices: list[PriceOut]
    free_license_codes: list[str]
    files: list[MediaFileOut]
    processing_error: str | None = None
    rejection_reason: str | None = None


class MediaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = None
    keywords: list[str] | None = Field(default=None, max_length=50)
    location_city: str | None = Field(default=None, max_length=120)
    location_region: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(default=None, min_length=2, max_length=2)


class PriceIn(BaseModel):
    license_code: str
    size_tier: str = Field(default="original", pattern="^(web|hd|4k|8k|original)$")
    price_cents: int = Field(ge=0, le=100_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    subscription_credit_eligible: bool = False


class PricingIn(BaseModel):
    free_license_code: str | None = None
    prices: list[PriceIn] = Field(default_factory=list, max_length=30)


class Facet(BaseModel):
    value: str
    count: int


class SearchOut(BaseModel):
    items: list[MediaCard]
    total: int
    page: int
    page_size: int
    facets: dict[str, list[Facet]]
    interpreted: dict[str, str | None]

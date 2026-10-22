import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.production import SERVICE_CATEGORIES, RequestKind, RequestVisibility, RightsType


def _category(v: str) -> str:
    if v not in SERVICE_CATEGORIES:
        raise ValueError("Unknown service category")
    return v


class RequestIn(BaseModel):
    kind: RequestKind = RequestKind.custom_project
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=20, max_length=10_000)
    category: str
    deliverables: str = Field(default="", max_length=5000)
    reference_urls: list[str] = Field(default_factory=list, max_length=10)
    location_city: str | None = Field(default=None, max_length=120)
    location_region: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(default=None, min_length=2, max_length=2)
    remote_ok: bool = False
    budget_min_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    budget_max_cents: int | None = Field(default=None, ge=100, le=100_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    deadline: date | None = None
    rights_preference: RightsType
    visibility: RequestVisibility = RequestVisibility.public

    _cat = field_validator("category")(_category)

    @field_validator("reference_urls")
    @classmethod
    def http_urls(cls, v: list[str]) -> list[str]:
        for url in v:
            if not url.startswith(("https://", "http://")) or len(url) > 500:
                raise ValueError("Reference links must be http(s) URLs")
        return v

    @model_validator(mode="after")
    def check(self) -> "RequestIn":
        if self.budget_min_cents and self.budget_max_cents and self.budget_max_cents < self.budget_min_cents:
            raise ValueError("Maximum budget must be at least the minimum")
        if self.deadline and self.deadline < date.today():
            raise ValueError("Deadline is in the past")
        if self.location_country:
            self.location_country = self.location_country.upper()
        return self


class MilestoneIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    amount_cents: int = Field(ge=100, le=100_000_000)
    due_in_days: int | None = Field(default=None, ge=0, le=730)


class ProposalIn(BaseModel):
    cover_letter: str = Field(min_length=20, max_length=10_000)
    total_cents: int = Field(ge=100, le=100_000_000)
    milestones: list[MilestoneIn] = Field(min_length=1, max_length=10)
    delivery_days: int = Field(ge=1, le=730)
    revisions_included: int = Field(default=1, ge=0, le=10)
    rights_type: RightsType
    rights_terms: str = Field(min_length=10, max_length=10_000)


class InviteIn(BaseModel):
    creator_handle: str
    message: str = Field(default="", max_length=2000)


class PackageIn(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=20, max_length=5000)
    category: str
    deliverables: str = Field(default="", max_length=5000)
    price_cents: int = Field(ge=100, le=100_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    delivery_days: int = Field(ge=1, le=365)
    revisions_included: int = Field(default=1, ge=0, le=10)
    rights_type: RightsType
    rights_terms: str = Field(min_length=10, max_length=10_000)
    is_active: bool = True

    _cat = field_validator("category")(_category)


class BookIn(BaseModel):
    brief: str = Field(default="", max_length=5000)
    accept_terms: bool


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=5000)


class RevisionIn(BaseModel):
    note: str = Field(min_length=5, max_length=5000)


class AddMilestoneIn(MilestoneIn):
    pass


class DisputeIn(BaseModel):
    milestone_id: uuid.UUID
    reason: str = Field(pattern="^(not_delivered|quality|scope|late|unresponsive|other)$")
    description: str = Field(min_length=20, max_length=5000)


class ResolveIn(BaseModel):
    outcome: str = Field(pattern="^(release|refund|split)$")
    creator_share_bps: int | None = Field(default=None, ge=1, le=9999)
    note: str = Field(min_length=5, max_length=5000)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=5000)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class StartConversationIn(BaseModel):
    creator_handle: str
    body: str = Field(min_length=1, max_length=5000)


class GalleryIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    message: str = Field(default="", max_length=5000)
    client_name: str = Field(default="", max_length=200)
    client_email: EmailStr | None = None
    project_id: uuid.UUID | None = None
    password: str | None = Field(default=None, min_length=6, max_length=200)
    clear_password: bool = False
    expires_at: date | None = None
    allow_downloads: bool = False
    selection_limit: int | None = Field(default=None, ge=1, le=10_000)


class GalleryUnlockIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class GalleryCommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    item_id: uuid.UUID | None = None
    is_revision_request: bool = False


class GalleryFlagsIn(BaseModel):
    is_favorite: bool | None = None
    is_selected: bool | None = None

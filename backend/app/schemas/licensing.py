import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORM


class LicenseTypeOut(ORM):
    code: str
    name: str
    summary: str
    is_free: bool
    is_exclusive: bool
    allows_commercial_use: bool
    requires_attribution: bool
    permitted_uses: list[str]
    terms_version: str


class AgreementTemplateOut(ORM):
    id: uuid.UUID
    code: str
    version: int
    title: str
    revenue_model: str
    body_markdown: str
    body_sha256: str
    territory: list[str]
    permitted_uses: list[str]
    sublicensing_allowed: bool
    duration: str
    withdrawal_terms: str
    legal_review_status: str
    creator_share_percent: float
    initial_exclusive_share_percent: float | None
    available_to_sign: bool


class AgreementAcceptIn(BaseModel):
    template_code: str
    template_version: int
    body_sha256: str
    signer_legal_name: str = Field(min_length=2, max_length=200)
    rights_owner_name: str = Field(min_length=2, max_length=200)
    i_agree: bool


class ContributorAgreementOut(ORM):
    id: uuid.UUID
    template_code: str
    template_version: int
    title: str
    revenue_model: str
    signer_legal_name: str
    rights_owner_name: str
    territory: list[str]
    permitted_uses: list[str]
    sublicensing_allowed: bool
    duration: str
    signature_method: str
    effective_at: datetime
    status: str
    legal_review_status: str


class FreeDownloadIn(BaseModel):
    license_code: str
    licensee_name: str | None = Field(default=None, max_length=200)


class DownloadOut(BaseModel):
    certificate_number: str
    download_url: str
    expires_in_seconds: int


class RightsGrantOut(BaseModel):
    certificate_number: str
    asset_id: uuid.UUID
    asset_title: str
    license_code: str
    license_name: str
    licensee_name: str
    is_exclusive: bool
    territory: list[str]
    permitted_uses: list[str]
    starts_at: datetime
    ends_at: datetime | None
    price_cents: int
    currency: str
    terms_version: str
    status: str
    issued_at: datetime
    creator_display_name: str
    requires_attribution: bool

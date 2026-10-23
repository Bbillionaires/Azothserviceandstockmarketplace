import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import ModerationAction


class DecisionIn(BaseModel):
    action: ModerationAction
    reason: str = Field(default="", max_length=4000)


class QueueItem(BaseModel):
    id: uuid.UUID
    title: str
    media_type: str
    category: str
    status: str
    thumbnail_url: str | None
    preview_url: str | None
    creator_handle: str
    created_at: datetime
    scan_status: str
    automated_signals: dict
    declaration: dict | None


class RoleChangeIn(BaseModel):
    role: str
    grant: bool = True


class StatusChangeIn(BaseModel):
    status: str
    reason: str = Field(default="", max_length=2000)


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    status: str
    roles: list[str]
    email_verified: bool
    created_at: datetime


class RevenueRuleIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    revenue_model: str
    creator_bps: int = Field(ge=0, le=10000)
    initial_exclusive_creator_bps: int | None = Field(default=None, ge=0, le=10000)
    affiliate_bps_of_platform: int = Field(default=0, ge=0, le=10000)
    net_revenue_deductions: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)


class RevenueRuleOut(BaseModel):
    id: uuid.UUID
    code: str
    version: int
    revenue_model: str
    creator_bps: int
    initial_exclusive_creator_bps: int | None
    affiliate_bps_of_platform: int
    net_revenue_deductions: list[str]
    notes: str
    effective_from: datetime


class RoyaltyPreviewIn(BaseModel):
    rule_id: uuid.UUID
    gross_cents: int = Field(ge=0)
    deductions: dict[str, int] = Field(default_factory=dict)
    is_initial_exclusive_transaction: bool = False
    with_affiliate: bool = False
    collaborators_bps: list[int] = Field(default_factory=list)


class LegalReviewIn(BaseModel):
    status: str
    reviewer_name: str = Field(min_length=2, max_length=200)


class ComplaintIn(BaseModel):
    asset_id: uuid.UUID
    complainant_name: str = Field(min_length=2, max_length=200)
    complainant_email: EmailStr
    complainant_address: str = Field(min_length=5, max_length=1000)
    copyrighted_work_description: str = Field(min_length=10, max_length=5000)
    good_faith_statement: bool
    accuracy_statement: bool
    electronic_signature: str = Field(min_length=2, max_length=200)
    captcha_token: str | None = Field(default=None, max_length=4096)


class ComplaintStatusIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=4000)


class CounterNoticeIn(BaseModel):
    statement: str = Field(min_length=20, max_length=5000)
    consent_to_jurisdiction: bool
    electronic_signature: str = Field(min_length=2, max_length=200)


class AppealIn(BaseModel):
    decision_id: uuid.UUID
    statement: str = Field(min_length=10, max_length=5000)


class AppealResolveIn(BaseModel):
    overturn: bool
    note: str = Field(default="", max_length=4000)

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORM


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=2, max_length=120)
    wants_to_sell: bool = False
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    referral_code: str | None = Field(default=None, max_length=40)
    accept_terms: bool
    captcha_token: str | None = Field(default=None, max_length=4096)

    @field_validator("accept_terms")
    @classmethod
    def must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms of Service and Privacy Policy")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    mfa_required: bool = False


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: EmailStr
    captcha_token: str | None = Field(default=None, max_length=4096)


class PasswordResetIn(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=256)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class UserOut(ORM):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    status: str
    email_verified: bool
    mfa_enabled: bool
    roles: list[str]
    creator_handle: str | None = None
    created_at: datetime

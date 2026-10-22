"""Registration, login (with optional TOTP MFA), email verification, password reset."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import current_user, mfa_pending_user
from app.core.rate_limit import client_ip, limiter
from app.core.security import (
    create_access_token,
    hash_opaque_token,
    hash_password,
    new_opaque_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.models import CreatorProfile, EmailToken, EmailTokenPurpose, Role, RoleCode, User, UserRole, UserStatus
from app.schemas.auth import (
    EmailIn,
    LoginIn,
    MfaCodeIn,
    MfaSetupOut,
    PasswordResetIn,
    RegisterIn,
    TokenIn,
    TokenOut,
    UserOut,
)
from app.schemas.common import Message
from app.services import audit, email

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(db: Session, user: User) -> UserOut:
    handle = db.scalar(select(CreatorProfile.handle).where(CreatorProfile.user_id == user.id))
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status.value,
        email_verified=user.email_verified_at is not None,
        mfa_enabled=user.mfa_enabled,
        roles=sorted(user.role_codes),
        creator_handle=handle,
        created_at=user.created_at,
    )


def grant_role(db: Session, user: User, code: RoleCode, granted_by=None) -> None:
    if user.has_role(code):
        return
    role = db.scalar(select(Role).where(Role.code == code.value))
    if not role:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Reference data not seeded")
    user.roles.append(UserRole(role=role, role_id=role.id, granted_by=granted_by))


def _issue_email_token(db: Session, user: User, purpose: EmailTokenPurpose, hours: int) -> str:
    raw, hashed = new_opaque_token()
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=hashed,
                      expires_at=datetime.now(UTC) + timedelta(hours=hours)))
    return raw


def _consume_email_token(db: Session, raw: str, purpose: EmailTokenPurpose) -> User:
    token = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_opaque_token(raw)))
    expires = token.expires_at.replace(tzinfo=token.expires_at.tzinfo or UTC) if token else None
    if not token or token.purpose != purpose or token.used_at or expires < datetime.now(UTC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    token.used_at = datetime.now(UTC)
    return db.get(User, token.user_id)


def send_verification(db: Session, user: User) -> None:
    settings = get_settings()
    raw = _issue_email_token(db, user, EmailTokenPurpose.verify_email, settings.email_token_hours)
    email.send(
        user.email,
        f"Verify your {settings.brand_name} account",
        f"Hi {user.display_name},\n\nConfirm your email address:\n"
        f"{settings.public_web_url}/verify-email?token={raw}\n\nThis link expires in {settings.email_token_hours} hours.",
    )


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name, token, httponly=True, secure=settings.cookie_secure, samesite="lax",
        max_age=settings.access_token_minutes * 60, path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limiter.check(f"register:{client_ip(request)}", 5)
    email_norm = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email_norm)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        email=email_norm,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        country_code=body.country_code.upper() if body.country_code else None,
        referred_by_code=body.referral_code,
    )
    db.add(user)
    db.flush()
    grant_role(db, user, RoleCode.buyer)
    from app.services.referral_service import attribute_signup

    attribute_signup(db, user, body.referral_code, client_ip(request))
    send_verification(db, user)
    audit.record(db, "user.registered", user.id, "user", user.id, client_ip(request), wants_to_sell=body.wants_to_sell)
    db.commit()
    _set_session_cookie(response, create_access_token(user.id, user.token_version))
    return user_out(db, user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    limiter.check(f"login:{ip}", get_settings().login_rate_limit_per_minute)
    limiter.check(f"login-email:{body.email.lower()}", get_settings().login_rate_limit_per_minute)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        audit.record(db, "auth.login_failed", None, "user", user.id if user else None, ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if user.status != UserStatus.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")
    if user.mfa_enabled:
        return TokenOut(access_token=create_access_token(user.id, user.token_version, mfa_pending=True), mfa_required=True)
    user.last_login_at = datetime.now(UTC)
    audit.record(db, "auth.login", user.id, "user", user.id, ip)
    db.commit()
    token = create_access_token(user.id, user.token_version)
    _set_session_cookie(response, token)
    return TokenOut(access_token=token)


@router.post("/mfa/verify", response_model=TokenOut)
def mfa_verify(body: MfaCodeIn, request: Request, response: Response,
               user: User = Depends(mfa_pending_user), db: Session = Depends(get_db)):
    limiter.check(f"mfa:{user.id}", 5)
    if not user.mfa_enabled or not user.mfa_secret or not verify_totp(user.mfa_secret, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid verification code")
    user.last_login_at = datetime.now(UTC)
    audit.record(db, "auth.login", user.id, "user", user.id, client_ip(request), mfa=True)
    db.commit()
    token = create_access_token(user.id, user.token_version)
    _set_session_cookie(response, token)
    return TokenOut(access_token=token)


@router.post("/logout", response_model=Message)
def logout(response: Response):
    response.delete_cookie(get_settings().cookie_name, path="/")
    return Message(detail="Signed out")


@router.post("/logout-all", response_model=Message)
def logout_all(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    response.delete_cookie(get_settings().cookie_name, path="/")
    return Message(detail="Signed out on all devices")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.post("/verify-email", response_model=Message)
def verify_email(body: TokenIn, db: Session = Depends(get_db)):
    user = _consume_email_token(db, body.token, EmailTokenPurpose.verify_email)
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    audit.record(db, "user.email_verified", user.id, "user", user.id)
    db.commit()
    return Message(detail="Email verified")


@router.post("/resend-verification", response_model=Message)
def resend_verification(user: User = Depends(current_user), db: Session = Depends(get_db)):
    limiter.check(f"resend:{user.id}", 3, 600)
    if user.email_verified_at:
        return Message(detail="Email already verified")
    send_verification(db, user)
    db.commit()
    return Message(detail="Verification email sent")


@router.post("/password-reset/request", response_model=Message)
def password_reset_request(body: EmailIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"reset:{client_ip(request)}", 5)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.status == UserStatus.active:
        settings = get_settings()
        raw = _issue_email_token(db, user, EmailTokenPurpose.reset_password, 1)
        email.send(user.email, f"Reset your {settings.brand_name} password",
                   f"Reset your password:\n{settings.public_web_url}/reset-password?token={raw}\n\n"
                   "This link expires in 1 hour. If you did not request it, ignore this email.")
        db.commit()
    # Same response either way so the endpoint does not reveal which emails exist.
    return Message(detail="If that account exists, a reset link has been sent")


@router.post("/password-reset/confirm", response_model=Message)
def password_reset_confirm(body: PasswordResetIn, request: Request, db: Session = Depends(get_db)):
    user = _consume_email_token(db, body.token, EmailTokenPurpose.reset_password)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit.record(db, "auth.password_reset", user.id, "user", user.id, client_ip(request))
    db.commit()
    return Message(detail="Password updated. Please sign in.")


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "MFA is already enabled")
    user.mfa_secret = new_totp_secret()
    db.commit()
    return MfaSetupOut(secret=user.mfa_secret, otpauth_uri=totp_uri(user.mfa_secret, user.email))


@router.post("/mfa/enable", response_model=Message)
def mfa_enable(body: MfaCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.mfa_secret or not verify_totp(user.mfa_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid verification code")
    user.mfa_enabled = True
    audit.record(db, "auth.mfa_enabled", user.id, "user", user.id)
    db.commit()
    return Message(detail="Multifactor authentication enabled")


@router.post("/mfa/disable", response_model=Message)
def mfa_disable(body: MfaCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.mfa_enabled or not verify_totp(user.mfa_secret or "", body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid verification code")
    user.mfa_enabled = False
    user.mfa_secret = None
    user.token_version += 1
    audit.record(db, "auth.mfa_disabled", user.id, "user", user.id)
    db.commit()
    return Message(detail="Multifactor authentication disabled")

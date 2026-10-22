"""Password hashing, access tokens, signed download links and TOTP MFA."""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pyotp

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"


# --- Passwords --------------------------------------------------------------

def hash_password(password: str) -> str:
    # bcrypt only considers the first 72 bytes; pre-hash so long passphrases
    # are not silently truncated.
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest())
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest())
    try:
        return bcrypt.checkpw(digest, password_hash.encode())
    except ValueError:
        return False


# --- Access tokens ------------------------------------------------------------

def create_access_token(user_id: uuid.UUID, token_version: int, mfa_pending: bool = False) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    minutes = 5 if mfa_pending else settings.access_token_minutes
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "typ": "mfa_pending" if mfa_pending else "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM])


# --- Opaque one-time tokens (email verification, password reset) --------------

def new_opaque_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hash)``. Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_opaque_token(raw)


def hash_opaque_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# --- Signed download links ----------------------------------------------------

def sign_download(entitlement_id: uuid.UUID, rendition: str, expires_at: int | None = None) -> str:
    settings = get_settings()
    expires_at = expires_at or int(time.time()) + settings.download_link_seconds
    message = f"{entitlement_id}:{rendition}:{expires_at}".encode()
    sig = hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()
    return f"{entitlement_id}.{rendition}.{expires_at}.{sig}"


def verify_download(token: str) -> tuple[uuid.UUID, str] | None:
    try:
        ent_id, rendition, expires_at, sig = token.split(".")
        expected = sign_download(uuid.UUID(ent_id), rendition, int(expires_at)).rsplit(".", 1)[1]
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(sig, expected) or int(expires_at) < time.time():
        return None
    return uuid.UUID(ent_id), rendition


# --- TOTP multifactor authentication ------------------------------------------

def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().brand_name)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)

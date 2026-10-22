"""FastAPI dependencies: database session, current user, role checks."""

import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import RoleCode, User, UserStatus

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _token_from_request(request: Request) -> tuple[str | None, bool]:
    """Return (token, came_from_cookie)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip(), False
    cookie = request.cookies.get(get_settings().cookie_name)
    return (cookie, True) if cookie else (None, False)


def _resolve_user(request: Request, db: Session, allow_mfa_pending: bool = False) -> User | None:
    token, from_cookie = _token_from_request(request)
    if not token:
        return None
    if from_cookie and request.method in UNSAFE_METHODS and request.headers.get("x-requested-with") != "fetch":
        # Cookie-authenticated writes must come from our own frontend (CSRF guard;
        # cross-site forms cannot set custom headers).
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing X-Requested-With header")
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from None
    if payload.get("typ") == "mfa_pending" and not allow_mfa_pending:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Multifactor verification required")
    user = db.get(User, user_id)
    if not user or user.token_version != payload.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is no longer valid")
    if user.status != UserStatus.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return _resolve_user(request, db)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _resolve_user(request, db)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return user


def mfa_pending_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _resolve_user(request, db, allow_mfa_pending=True)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return user


def verified_user(user: User = Depends(current_user)) -> User:
    if not user.email_verified_at:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verify your email address first")
    return user


def require_roles(*roles: RoleCode) -> Callable[[User], User]:
    """Allow users holding any of ``roles``. Admins are always allowed."""

    def checker(user: User = Depends(current_user)) -> User:
        if not user.has_role(RoleCode.admin, *roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user

    return checker

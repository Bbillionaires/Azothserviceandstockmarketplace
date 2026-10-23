"""Bot protection with Cloudflare Turnstile.

Disabled when ``TURNSTILE_SECRET_KEY`` is unset (development and tests).
Protected: registration, password-reset requests, copyright notices and the
client-gallery password form.
"""

import logging

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings

log = logging.getLogger("captcha")
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def require_captcha(token: str | None, ip: str | None) -> None:
    secret = get_settings().turnstile_secret_key
    if not secret:
        return
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please complete the human verification")
    try:
        resp = httpx.post(VERIFY_URL, data={"secret": secret, "response": token, "remoteip": ip or ""}, timeout=10)
        ok = resp.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        log.exception("turnstile verification unavailable")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Verification service unavailable; try again") from None
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Human verification failed; please try again")

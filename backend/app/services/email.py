"""Outbound email.

Backends: ``console`` (logs; development), ``smtp`` (any SMTP relay) and
``resend`` (Resend HTTP API, ``RESEND_API_KEY``). Delivery failures are logged
and never break the request that triggered the email.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger("email")
_outbox: list[dict] = []  # inspected by tests


def send(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = {"to": to, "subject": subject, "body": body}
    _outbox.append(message)
    if settings.email_backend == "resend":
        _send_resend(settings, to, subject, body)
    elif settings.email_backend == "smtp":
        import os

        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as smtp:
            smtp.starttls()
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        log.warning("EMAIL to=%s subject=%s\n%s", to, subject, body)


def _send_resend(settings, to: str, subject: str, body: str) -> None:
    import httpx

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": f"{settings.brand_name} <{settings.email_from}>", "to": [to], "subject": subject,
                  "text": body, "reply_to": settings.brand_support_email},
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        log.exception("email delivery failed (to=%s subject=%s)", to, subject)


def outbox() -> list[dict]:
    return _outbox

"""Outbound email. The console backend logs messages for local development;
a transactional provider (Resend, Postmark, SES) plugs in behind ``send``."""

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
    if settings.email_backend == "smtp":
        import os

        msg = EmailMessage()
        msg["From"] = settings.brand_support_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as smtp:
            smtp.starttls()
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        log.warning("EMAIL to=%s subject=%s\n%s", to, subject, body)


def outbox() -> list[dict]:
    return _outbox

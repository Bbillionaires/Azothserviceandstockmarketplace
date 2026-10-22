"""In-app notifications, with email for events that need prompt action."""

import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Notification, User
from app.services import email


def notify(db: Session, user_id: uuid.UUID, kind: str, title: str, body: str = "", link: str = "",
           send_email: bool = False) -> None:
    db.add(Notification(user_id=user_id, kind=kind, title=title[:200], body=body, link=link[:300]))
    if send_email:
        user = db.get(User, user_id)
        if user and user.email_verified_at:
            settings = get_settings()
            url = f"{settings.public_web_url}{link}" if link else settings.public_web_url
            email.send(user.email, f"{settings.brand_name}: {title}", f"{body}\n\n{url}".strip())

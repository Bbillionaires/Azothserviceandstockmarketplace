"""Conversations and notifications."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user, verified_user
from app.core.rate_limit import limiter
from app.models import (
    Conversation,
    ConversationKind,
    ConversationParticipant,
    CreatorProfile,
    Message,
    Notification,
    User,
)
from app.schemas.common import Message as Msg
from app.schemas.production import MessageIn, StartConversationIn
from app.services import messaging

router = APIRouter(tags=["messages"])


def _link(conv: Conversation) -> str | None:
    if conv.kind is ConversationKind.project:
        return f"/projects/{conv.subject_id}"
    if conv.kind is ConversationKind.request:
        return f"/requests/{conv.subject_id}"
    return None


@router.get("/conversations")
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Conversation, ConversationParticipant.last_read_at)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .where(ConversationParticipant.user_id == user.id).order_by(Conversation.last_message_at.desc()).limit(200)
    ).all()
    out = []
    for conv, last_read in rows:
        other_id = next((u for u in messaging.participants(db, conv) if u != user.id), None)
        other = db.get(User, other_id) if other_id else None
        last = db.scalar(select(Message).where(Message.conversation_id == conv.id)
                         .order_by(Message.created_at.desc()).limit(1))
        unread = db.scalar(select(func.count(Message.id)).where(
            Message.conversation_id == conv.id, Message.sender_id != user.id, Message.sender_id.is_not(None),
            Message.created_at > (last_read or datetime(1970, 1, 1, tzinfo=UTC))))
        out.append({"id": conv.id, "kind": conv.kind.value, "title": conv.title, "link": _link(conv),
                    "other_party": other.display_name if other else "", "last_message_at": conv.last_message_at,
                    "preview": last.body[:140] if last else "", "unread": unread or 0})
    return out


@router.post("/conversations", status_code=201)
def start_conversation(body: StartConversationIn, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    """Contact a creator from their storefront."""
    limiter.check(f"dm:{user.id}", 20, 3600)
    creator = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == body.creator_handle.lower()))
    if not creator:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    conv = messaging.get_or_create(db, ConversationKind.direct, None, user.id, creator.user_id,
                                   f"{user.display_name} ↔ {creator.display_name}")
    messaging.post(db, conv, user.id, body.body)
    db.commit()
    return {"id": conv.id}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, before: datetime | None = None,
                     limit: int = Query(100, ge=1, le=500), user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    conv = messaging.require_participant(db, conversation_id, user.id)
    stmt = select(Message).where(Message.conversation_id == conv.id)
    if before:
        stmt = stmt.where(Message.created_at < before)
    msgs = list(reversed(db.scalars(stmt.order_by(Message.created_at.desc()).limit(limit)).all()))
    db.execute(update(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id,
                                                     ConversationParticipant.user_id == user.id)
               .values(last_read_at=datetime.now(UTC)))
    db.commit()
    names = {uid: db.get(User, uid).display_name for uid in messaging.participants(db, conv)}
    return {"id": conv.id, "title": conv.title, "kind": conv.kind.value, "link": _link(conv),
            "messages": [{"id": m.id, "body": m.body, "is_system": m.is_system, "mine": m.sender_id == user.id,
                          "sender": names.get(m.sender_id, "") if m.sender_id else "", "created_at": m.created_at}
                         for m in msgs]}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(conversation_id: uuid.UUID, body: MessageIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    limiter.check(f"msg:{user.id}", 120, 3600)
    conv = messaging.require_participant(db, conversation_id, user.id)
    m = messaging.post(db, conv, user.id, body.body)
    db.commit()
    return {"id": m.id, "created_at": m.created_at}


@router.get("/notifications")
def list_notifications(unread_only: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100))
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
             "read": n.read_at is not None, "created_at": n.created_at} for n in rows]


@router.get("/notifications/unread-count")
def unread_count(user: User = Depends(current_user), db: Session = Depends(get_db)):
    notes = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id,
                                                                Notification.read_at.is_(None))) or 0
    return {"notifications": notes}


@router.post("/notifications/read", response_model=Msg)
def mark_read(ids: list[uuid.UUID] | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    db.execute(stmt.values(read_at=datetime.now(UTC)))
    db.commit()
    return Msg(detail="Marked as read")

"""Conversations between clients and creators.

One conversation exists per pair of users and subject (request, project or
direct). Bids stay confidential because each bidder talks to the client in a
separate request conversation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, ConversationKind, ConversationParticipant, Message
from app.services.notify import notify


def pair_key(a: uuid.UUID, b: uuid.UUID) -> str:
    x, y = sorted([a.hex, b.hex])
    return f"{x[:32]}:{y[:32]}"[:80]


def get_or_create(db: Session, kind: ConversationKind, subject_id: uuid.UUID | None, a: uuid.UUID, b: uuid.UUID,
                  title: str) -> Conversation:
    if a == b:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot message yourself")
    key = pair_key(a, b)
    conv = db.scalar(select(Conversation).where(Conversation.kind == kind, Conversation.pair_key == key,
                                                (Conversation.subject_id == subject_id) if subject_id
                                                else Conversation.subject_id.is_(None)))
    if conv:
        return conv
    conv = Conversation(kind=kind, subject_id=subject_id, pair_key=key, title=title[:200])
    db.add(conv)
    db.flush()
    db.add_all([ConversationParticipant(conversation_id=conv.id, user_id=a),
                ConversationParticipant(conversation_id=conv.id, user_id=b)])
    db.flush()
    return conv


def participants(db: Session, conv: Conversation) -> list[uuid.UUID]:
    return list(db.scalars(select(ConversationParticipant.user_id)
                           .where(ConversationParticipant.conversation_id == conv.id)))


def require_participant(db: Session, conv_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or user_id not in participants(db, conv):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def post(db: Session, conv: Conversation, sender_id: uuid.UUID | None, body: str, system: bool = False) -> Message:
    body = body.strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Message is empty")
    msg = Message(conversation_id=conv.id, sender_id=sender_id, body=body[:5000], is_system=system)
    db.add(msg)
    conv.last_message_at = datetime.now(UTC)
    if sender_id:
        for uid in participants(db, conv):
            if uid == sender_id:
                part = db.scalar(select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conv.id, ConversationParticipant.user_id == uid))
                part.last_read_at = datetime.now(UTC)
            else:
                notify(db, uid, "message", f"New message: {conv.title}", body[:200], f"/messages?c={conv.id}")
    db.flush()
    return msg

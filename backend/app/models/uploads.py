"""Direct-to-storage upload sessions.

The browser asks for an upload URL (a presigned S3 PUT, or an API endpoint
when local storage is used), sends the bytes there, then calls a completion
endpoint for its purpose (stock media, milestone deliverable, gallery item).
Large video never has to pass through the API process.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPk, str_enum, utcnow


class UploadPurpose(str, enum.Enum):
    media = "media"
    deliverable = "deliverable"
    gallery_item = "gallery_item"


class UploadStatus(str, enum.Enum):
    pending = "pending"
    consumed = "consumed"


class UploadSession(UUIDPk, Base):
    __tablename__ = "upload_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[UploadPurpose] = mapped_column(str_enum(UploadPurpose, "upload_purpose"))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # milestone or gallery id
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    declared_size: Mapped[int] = mapped_column(BigInteger)
    max_size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    status: Mapped[UploadStatus] = mapped_column(str_enum(UploadStatus, "upload_status"), default=UploadStatus.pending)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

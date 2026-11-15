"""ORM models for conversations and their messages (Phase 4, P4-M4).

A conversation belongs to one user in one tenant. ``tenant_id`` and
``owner_id`` are UUIDs without foreign keys until users and tenants exist
(Phase 6); the repository filters every query by both.

Assistant messages keep citation metadata (document, page, section, offsets),
never the chunk text, so document content is not copied into chat history.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.documents import _allowed_values_check, _enum_column
from app.db.types import UtcDateTime, utc_now


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # "My recent conversations".
        Index(
            "ix_conversations_tenant_id_owner_id_updated_at", "tenant_id", "owner_id", "updated_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    # Updated whenever a turn is added.
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConversationMessage.position",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "position"),
        _allowed_values_check("role", MessageRole),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # Copied from the conversation so message queries can filter by tenant.
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # 0, 1, 2, ... within the conversation: a user message, then its reply.
    position: Mapped[int]
    role: Mapped[MessageRole] = mapped_column(_enum_column(MessageRole, 16))
    # The question, or the answer; null when the evidence was insufficient.
    content: Mapped[str | None] = mapped_column(Text)
    # Assistant messages: "answered" or "insufficient_evidence", and the reason.
    status: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(32))
    # Assistant messages: cited sources as citation metadata, without chunk text.
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    model_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

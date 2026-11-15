"""Data access for conversations. Every query is scoped to (tenant, owner)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.conversations import Conversation, ConversationMessage
from app.db.types import utc_now


@dataclass(frozen=True)
class ConversationSummary:
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    messages: int


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> Conversation:
        conversation = Conversation(tenant_id=tenant_id, owner_id=owner_id)
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def get(
        self, tenant_id: uuid.UUID, owner_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        return self._session.scalars(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.owner_id == owner_id,
            )
        ).one_or_none()

    def list(
        self, tenant_id: uuid.UUID, owner_id: uuid.UUID, *, limit: int
    ) -> list[ConversationSummary]:
        counts = (
            select(ConversationMessage.conversation_id, func.count().label("messages"))
            .where(ConversationMessage.tenant_id == tenant_id)
            .group_by(ConversationMessage.conversation_id)
            .subquery()
        )
        rows = self._session.execute(
            select(Conversation, func.coalesce(counts.c.messages, 0))
            .outerjoin(counts, counts.c.conversation_id == Conversation.id)
            .where(Conversation.tenant_id == tenant_id, Conversation.owner_id == owner_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(limit)
        )
        return [
            ConversationSummary(c.id, c.created_at, c.updated_at, int(count)) for c, count in rows
        ]

    def messages(self, conversation: Conversation) -> list[ConversationMessage]:
        return list(
            self._session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation.id,
                    ConversationMessage.tenant_id == conversation.tenant_id,
                )
                .order_by(ConversationMessage.position)
            )
        )

    def add_messages(self, conversation: Conversation, messages: list[ConversationMessage]) -> None:
        """Append messages after the current last position and touch the conversation."""
        last = self._session.scalar(
            select(func.max(ConversationMessage.position)).where(
                ConversationMessage.conversation_id == conversation.id
            )
        )
        start = -1 if last is None else last
        for offset, message in enumerate(messages, start=1):
            message.conversation_id = conversation.id
            message.tenant_id = conversation.tenant_id
            message.position = start + offset
            self._session.add(message)
        conversation.updated_at = utc_now()
        self._session.flush()

    def delete(self, conversation: Conversation) -> None:
        # Messages are removed by the database (ON DELETE CASCADE, passive_deletes).
        self._session.delete(conversation)
        self._session.flush()

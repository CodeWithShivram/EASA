"""Synthetic support tickets (Phase 5, P5-M2): the system the agent's tools act on.

A ticket belongs to a tenant and to the user who reported it. Until roles
exist (Phase 6) a user can read only tickets they reported. ``number`` is the
human-facing ticket number, unique per tenant. Only synthetic data is stored.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.documents import _allowed_values_check, _enum_column
from app.db.types import UtcDateTime, utc_now


class TicketStatus(StrEnum):
    DRAFT = "draft"  # created by the agent after confirmation; not yet submitted
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        Index("ix_support_tickets_tenant_id_reporter_id", "tenant_id", "reporter_id"),
        _allowed_values_check("status", TicketStatus),
        _allowed_values_check("priority", TicketPriority),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reporter_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    number: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(_enum_column(TicketStatus, 20))
    priority: Mapped[TicketPriority] = mapped_column(
        _enum_column(TicketPriority, 10), default=TicketPriority.NORMAL
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, onupdate=utc_now)

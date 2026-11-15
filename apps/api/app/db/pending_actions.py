"""Consequential tool calls waiting for the user's decision (Phase 5, P5-M3).

When the agent proposes a consequential tool (for example creating a draft
ticket), nothing runs: the validated arguments are stored here and the user
confirms or cancels. Each action belongs to one user in one tenant, can be
decided once, and expires. The arguments are the user's own request data.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.documents import _allowed_values_check, _enum_column
from app.db.types import UtcDateTime, utc_now


class ActionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"  # confirmed and run successfully
    FAILED = "failed"  # confirmed, but the tool did not succeed
    CANCELLED = "cancelled"


class PendingAction(Base):
    __tablename__ = "pending_actions"
    __table_args__ = (
        Index("ix_pending_actions_tenant_id_user_id_status", "tenant_id", "user_id", "status"),
        _allowed_values_check("status", ActionStatus),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tool: Mapped[str] = mapped_column(String(64))
    # Arguments as validated by the tool's Input model.
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[ActionStatus] = mapped_column(
        _enum_column(ActionStatus, 16), default=ActionStatus.PENDING
    )
    # The tool's output once confirmed, or the failure detail.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

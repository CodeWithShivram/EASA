"""Audit log of protected operations (Phase 5: tool executions).

One row per attempt, whatever the outcome, written in its own transaction so
it survives a rollback of the operation itself. Arguments are stored only as
a SHA-256 digest of their canonical JSON: the log proves what was requested
without keeping possibly sensitive values.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.documents import _allowed_values_check, _enum_column
from app.db.types import UtcDateTime, utc_now


class AuditOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DENIED = "denied"  # permission missing
    UNKNOWN_TOOL = "unknown_tool"  # not on the allowlist
    INVALID_ARGUMENTS = "invalid_arguments"
    FAILED = "failed"
    TIMEOUT = "timeout"


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_id_created_at", "tenant_id", "created_at"),
        _allowed_values_check("outcome", AuditOutcome),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # What was attempted, e.g. "tool.execute", and on what, e.g. a tool name.
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[AuditOutcome] = mapped_column(_enum_column(AuditOutcome, 32))
    # Short machine-readable detail: a missing permission, an error type.
    detail: Mapped[str | None] = mapped_column(String(128))
    # SHA-256 of the canonical JSON arguments; never the arguments themselves.
    arguments_digest: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

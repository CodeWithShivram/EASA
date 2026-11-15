"""Audit records, each written and committed in its own session."""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.audit import AuditLog, AuditOutcome


def arguments_digest(arguments: Any) -> str:
    """SHA-256 of the canonical JSON form (sorted keys, no whitespace)."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        target: str,
        outcome: AuditOutcome,
        detail: str | None = None,
        arguments: Any = None,
        correlation_id: str | None = None,
        duration_ms: int | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            target=target[:128],
            outcome=outcome,
            detail=detail[:128] if detail else None,
            arguments_digest=None if arguments is None else arguments_digest(arguments),
            correlation_id=correlation_id,
            duration_ms=duration_ms,
        )
        # Its own transaction: the record survives a rollback of the operation.
        with self._session_factory() as session:
            session.add(entry)
            session.commit()
            session.refresh(entry)
            session.expunge(entry)
        return entry

    def list_for_tenant(self, tenant_id: uuid.UUID, *, limit: int = 100) -> list[AuditLog]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(AuditLog)
                    .where(AuditLog.tenant_id == tenant_id)
                    .order_by(AuditLog.created_at.desc(), AuditLog.id)
                    .limit(limit)
                )
            )

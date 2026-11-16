"""Data access for pending actions. Reads and decisions are scoped to (tenant, user)."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.pending_actions import ActionStatus, PendingAction
from app.db.types import utc_now


class PendingActionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        tool: str,
        arguments: dict[str, Any],
        *,
        ttl: timedelta,
    ) -> PendingAction:
        action = PendingAction(
            tenant_id=tenant_id,
            user_id=user_id,
            tool=tool,
            arguments=arguments,
            expires_at=utc_now() + ttl,
        )
        self._session.add(action)
        self._session.commit()
        return action

    def get_own(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, action_id: uuid.UUID
    ) -> PendingAction | None:
        return self._session.scalars(
            select(PendingAction).where(
                PendingAction.id == action_id,
                PendingAction.tenant_id == tenant_id,
                PendingAction.user_id == user_id,
            )
        ).one_or_none()

    def count_open(self, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> int:
        """Pending, unexpired actions of one user."""
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(PendingAction)
                .where(
                    PendingAction.tenant_id == tenant_id,
                    PendingAction.user_id == user_id,
                    PendingAction.status == ActionStatus.PENDING,
                    PendingAction.expires_at > now,
                )
            )
            or 0
        )

    def claim(self, action: PendingAction, status: ActionStatus, now: datetime) -> bool:
        """Move a pending, unexpired action to ``status`` exactly once (atomic)."""
        result = self._session.execute(
            update(PendingAction)
            .where(
                PendingAction.id == action.id,
                PendingAction.status == ActionStatus.PENDING,
                PendingAction.expires_at > now,
            )
            .values(status=status, decided_at=now)
        )
        self._session.commit()
        self._session.refresh(action)
        return result.rowcount == 1  # type: ignore[attr-defined]

    def record_result(
        self, action: PendingAction, status: ActionStatus, result: dict[str, Any]
    ) -> None:
        action.status = status
        action.result = result
        self._session.commit()

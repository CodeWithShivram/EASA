"""Confirming or cancelling the agent's pending actions (Phase 5, P5-M3).

An action can be decided once, by its owner, before it expires. Confirming
runs the tool through ToolExecutor with ``confirmed=True``, so the permission
is checked again at that moment and the run is audited like any other.
"""

import logging
import uuid
from http import HTTPStatus

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity import Identity
from app.db.audit import AuditOutcome
from app.db.pending_actions import ActionStatus, PendingAction
from app.db.types import utc_now
from app.repositories.pending_actions import PendingActionRepository
from app.tools.executor import ToolExecutor, ToolResult

logger = logging.getLogger(__name__)


class ActionNotFoundError(AppError):
    def __init__(self) -> None:
        # Same answer for missing actions and other users' actions.
        super().__init__(
            "Action not found.", code="action_not_found", status_code=HTTPStatus.NOT_FOUND
        )


class AgentActionService:
    def __init__(self, session: Session, executor: ToolExecutor) -> None:
        self._repository = PendingActionRepository(session)
        self._executor = executor

    def get(self, identity: Identity, action_id: uuid.UUID) -> PendingAction:
        action = self._repository.get_own(identity.tenant_id, identity.user_id, action_id)
        if action is None:
            raise ActionNotFoundError()
        return action

    def confirm(self, identity: Identity, action_id: uuid.UUID) -> tuple[PendingAction, ToolResult]:
        action = self.get(identity, action_id)
        self._claim(action, ActionStatus.CONFIRMED)
        result = self._executor.execute(identity, action.tool, action.arguments, confirmed=True)
        if result.outcome is AuditOutcome.SUCCEEDED:
            self._repository.record_result(action, ActionStatus.CONFIRMED, result.output or {})
        else:
            self._repository.record_result(
                action,
                ActionStatus.FAILED,
                {
                    "outcome": result.outcome.value,
                    "detail": result.detail,
                    "message": result.message,
                },
            )
        logger.info(
            "pending action confirmed",
            extra={
                "action_id": str(action.id),
                "tool": action.tool,
                "outcome": result.outcome.value,
            },
        )
        return action, result

    def cancel(self, identity: Identity, action_id: uuid.UUID) -> PendingAction:
        action = self.get(identity, action_id)
        self._claim(action, ActionStatus.CANCELLED)
        logger.info("pending action cancelled", extra={"action_id": str(action.id)})
        return action

    def _claim(self, action: PendingAction, status: ActionStatus) -> None:
        now = utc_now()
        if self._repository.claim(action, status, now):
            return
        if action.status is ActionStatus.PENDING:  # still pending, so it has expired
            raise AppError(
                "This action has expired; ask the agent again.",
                code="action_expired",
                status_code=HTTPStatus.CONFLICT,
            )
        raise AppError(
            f"This action was already {action.status.value}.",
            code="action_not_pending",
            status_code=HTTPStatus.CONFLICT,
        )

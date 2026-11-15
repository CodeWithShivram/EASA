"""The agent and its pending actions (Phase 5, P5-M3; development only)."""

import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session, get_identity
from app.api.v1.routes.tools import ToolResultResponse
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.db.pending_actions import PendingAction
from app.services.agent import MAX_MESSAGE_CHARS, AgentService
from app.services.agent_actions import AgentActionService

router = APIRouter(prefix="/agent", tags=["agent"])

_RUN_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (
        HTTPStatus.UNPROCESSABLE_CONTENT,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
    )
}
_ACTION_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse} for status in (HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT)
}


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class AgentStepResponse(BaseModel):
    tool: str
    outcome: str
    detail: str | None


class PendingActionResponse(BaseModel):
    id: uuid.UUID
    tool: str
    arguments: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None


class AgentResponse(BaseModel):
    status: str  # answered, confirmation_required or failed
    answer: str | None
    reason: str | None
    steps: list[AgentStepResponse]
    pending_action: PendingActionResponse | None
    model_id: str | None


class ConfirmResponse(BaseModel):
    action: PendingActionResponse
    result: ToolResultResponse


def _action(action: PendingAction) -> PendingActionResponse:
    return PendingActionResponse(
        id=action.id,
        tool=action.tool,
        arguments=action.arguments,
        status=action.status.value,
        result=action.result,
        created_at=action.created_at,
        expires_at=action.expires_at,
        decided_at=action.decided_at,
    )


def get_agent_service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> AgentService:
    return AgentService(session, request.app.state.tool_executor, request.app.state.chat_model)


def get_action_service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> AgentActionService:
    return AgentActionService(session, request.app.state.tool_executor)


CurrentIdentity = Annotated[Identity, Depends(get_identity)]
Actions = Annotated[AgentActionService, Depends(get_action_service)]


@router.post("", response_model=AgentResponse, responses=_RUN_ERRORS)
def run_agent(
    request: AgentRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    identity: CurrentIdentity,
) -> AgentResponse:
    """Let the agent handle a request with the tools the caller may use."""
    result = service.run(identity, request.message)
    return AgentResponse(
        status=result.status.value,
        answer=result.answer,
        reason=result.reason,
        steps=[
            AgentStepResponse(tool=s.tool, outcome=s.outcome, detail=s.detail) for s in result.steps
        ],
        pending_action=_action(result.pending_action) if result.pending_action else None,
        model_id=result.model_id,
    )


@router.get("/actions/{action_id}", response_model=PendingActionResponse, responses=_ACTION_ERRORS)
def get_action(
    action_id: uuid.UUID, actions: Actions, identity: CurrentIdentity
) -> PendingActionResponse:
    """A pending action of the current user."""
    return _action(actions.get(identity, action_id))


@router.post(
    "/actions/{action_id}/confirm", response_model=ConfirmResponse, responses=_ACTION_ERRORS
)
def confirm_action(
    action_id: uuid.UUID, actions: Actions, identity: CurrentIdentity
) -> ConfirmResponse:
    """Run the pending action now (once; the permission is checked again)."""
    action, result = actions.confirm(identity, action_id)
    return ConfirmResponse(
        action=_action(action),
        result=ToolResultResponse(
            tool=result.tool,
            outcome=result.outcome.value,
            output=result.output,
            arguments=result.arguments,
            detail=result.detail,
            message=result.message,
        ),
    )


@router.post(
    "/actions/{action_id}/cancel", response_model=PendingActionResponse, responses=_ACTION_ERRORS
)
def cancel_action(
    action_id: uuid.UUID, actions: Actions, identity: CurrentIdentity
) -> PendingActionResponse:
    """Cancel the pending action; it can no longer run."""
    return _action(actions.cancel(identity, action_id))

"""The tenant's audit log for administrators (Phase 6, P6-M4)."""

import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.dependencies import require
from app.core.correlation import get_correlation_id
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.db.audit import AuditOutcome
from app.repositories.audit import AuditRepository

router = APIRouter(prefix="/audit", tags=["audit"])

MAX_AUDIT_PAGE = 200
_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.UNPROCESSABLE_CONTENT)
}


class AuditRecordResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID
    action: str
    target: str
    outcome: AuditOutcome
    detail: str | None
    arguments_digest: str | None
    correlation_id: str | None
    duration_ms: int | None


class AuditListResponse(BaseModel):
    items: list[AuditRecordResponse]
    limit: int
    offset: int


@router.get("", responses=_ERRORS)
def list_audit_records(
    request: Request,
    admin: Annotated[Identity, Depends(require("audit:read"))],
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    action: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_.]+$")] = None,
    outcome: AuditOutcome | None = None,
    user_id: uuid.UUID | None = None,
) -> AuditListResponse:
    """Records of the caller's tenant, newest first. Reading the log is itself audited."""
    repository = AuditRepository(request.app.state.session_factory)
    records = repository.list_for_tenant(
        admin.tenant_id, limit=limit, offset=offset, action=action, outcome=outcome, user_id=user_id
    )
    filters = [
        f"{k}={v}" for k, v in (("action", action), ("outcome", outcome), ("user", user_id)) if v
    ]
    repository.record(
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        action="audit.read",
        target="audit",
        outcome=AuditOutcome.SUCCEEDED,
        detail=" ".join(filters) or None,
        correlation_id=get_correlation_id(),
    )
    return AuditListResponse(
        items=[AuditRecordResponse.model_validate(r, from_attributes=True) for r in records],
        limit=limit,
        offset=offset,
    )

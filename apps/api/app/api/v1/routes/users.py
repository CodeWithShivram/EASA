"""User administration (Phase 6, P6-M2): administrators of the caller's tenant only."""

import uuid
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session, require, session_policy
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.db.accounts import User
from app.db.types import utc_now
from app.repositories.audit import AuditRepository
from app.schemas.users import (
    CreateUserRequest,
    PasswordResetRequest,
    UpdateUserRequest,
    UserListResponse,
    UserResponse,
)
from app.services.users import UserAdminService

router = APIRouter(prefix="/users", tags=["users"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
        HTTPStatus.UNPROCESSABLE_CONTENT,
    )
}

Admin = Annotated[Identity, Depends(require("users:manage"))]


def get_user_admin_service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> UserAdminService:
    state = request.app.state
    return UserAdminService(
        session,
        session_policy(state.settings),
        state.role_permissions,
        AuditRepository(state.session_factory),
    )


Service = Annotated[UserAdminService, Depends(get_user_admin_service)]


def _response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        locked=user.locked_until is not None and user.locked_until > utc_now(),
        created_at=user.created_at,
    )


@router.get("", responses=_ERRORS)
def list_users(admin: Admin, service: Service) -> UserListResponse:
    return UserListResponse(items=[_response(u) for u in service.list_users(admin)])


@router.post("", status_code=HTTPStatus.CREATED, responses=_ERRORS)
def create_user(body: CreateUserRequest, admin: Admin, service: Service) -> UserResponse:
    return _response(service.create(admin, body.username, body.password, body.role))


@router.patch("/{user_id}", responses=_ERRORS)
def update_user(
    user_id: uuid.UUID, body: UpdateUserRequest, admin: Admin, service: Service
) -> UserResponse:
    return _response(service.update(admin, user_id, role=body.role, is_active=body.is_active))


@router.post("/{user_id}/password", status_code=HTTPStatus.NO_CONTENT, responses=_ERRORS)
def reset_password(
    user_id: uuid.UUID, body: PasswordResetRequest, admin: Admin, service: Service
) -> Response:
    service.reset_password(admin, user_id, body.password)
    return Response(status_code=HTTPStatus.NO_CONTENT)

from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import get_auth_service, get_bearer_token, get_identity
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.core.roles import Role
from app.db.accounts import User
from app.repositories.accounts import AccountRepository
from app.schemas.auth import CurrentUser, LoginRequest, LoginResponse
from app.services.auth import AuthService, not_authenticated

router = APIRouter(prefix="/auth", tags=["auth"])

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {HTTPStatus.UNAUTHORIZED: {"model": ErrorResponse}}

Service = Annotated[AuthService, Depends(get_auth_service)]


def _current_user(user: User, permissions: frozenset[str]) -> CurrentUser:
    return CurrentUser(
        user_id=user.id,
        username=user.username,
        role=Role(user.role),
        tenant_id=user.tenant_id,
        permissions=sorted(permissions),
    )


@router.post("/login", responses=_UNAUTHORIZED)
def login(body: LoginRequest, service: Service, request: Request) -> LoginResponse:
    signed_in = service.login(body.username, body.password)
    permissions = request.app.state.role_permissions.get(signed_in.user.role, frozenset())
    return LoginResponse(
        token=signed_in.token,
        expires_at=signed_in.expires_at,
        user=_current_user(signed_in.user, permissions),
    )


@router.post("/logout", status_code=HTTPStatus.NO_CONTENT, responses=_UNAUTHORIZED)
def logout(
    service: Service,
    token: Annotated[str, Depends(get_bearer_token)],
    _: Annotated[Identity, Depends(get_identity)],
) -> Response:
    service.logout(token)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.get("/me", responses=_UNAUTHORIZED)
def me(identity: Annotated[Identity, Depends(get_identity)], request: Request) -> CurrentUser:
    with request.app.state.session_factory() as session:
        user = AccountRepository(session).get_user(identity.user_id)
        if user is None:  # deleted between the two reads
            raise not_authenticated()
        return _current_user(user, identity.permissions)

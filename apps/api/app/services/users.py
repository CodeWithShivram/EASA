"""User administration within the administrator's own tenant (Phase 6, P6-M2, ADR-032).

Administrators (``users:manage``) list, create, change the role of, disable,
enable and reset the password of users in their tenant. Users of other tenants
look missing. Administrators cannot change their own role or disable
themselves, so a tenant cannot lose its last way back in by accident.
Disabling a user or resetting a password ends that user's sessions. Every
change is audited; passwords never are.
"""

import logging
import uuid
from http import HTTPStatus

from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id
from app.core.errors import AppError
from app.core.identity import Identity
from app.core.passwords import hash_password
from app.core.roles import Role
from app.db.accounts import User
from app.db.audit import AuditOutcome
from app.db.types import utc_now
from app.repositories.accounts import AccountRepository
from app.repositories.audit import AuditRepository
from app.services.auth import (
    AuthService,
    SessionPolicy,
    check_new_account,
    check_new_password,
    username_taken,
)

logger = logging.getLogger(__name__)


def _not_found() -> AppError:
    return AppError(
        "The user was not found.", code="user_not_found", status_code=HTTPStatus.NOT_FOUND
    )


class UserAdminService:
    def __init__(
        self,
        session: Session,
        policy: SessionPolicy,
        role_permissions: dict[Role, frozenset[str]],
        audit: AuditRepository,
    ) -> None:
        self._accounts = AccountRepository(session)
        self._auth = AuthService(session, policy, role_permissions, audit)
        self._policy = policy
        self._audit = audit

    def _record(self, admin: Identity, action: str, user: User, detail: str | None) -> None:
        self._audit.record(
            tenant_id=admin.tenant_id,
            user_id=admin.user_id,
            action=action,
            target=f"user:{user.id}",
            outcome=AuditOutcome.SUCCEEDED,
            detail=detail,
            correlation_id=get_correlation_id(),
        )

    def _get(self, admin: Identity, user_id: uuid.UUID) -> User:
        user = self._accounts.get_user(user_id)
        if user is None or user.tenant_id != admin.tenant_id:
            raise _not_found()  # same answer for other tenants' users
        return user

    def list_users(self, admin: Identity) -> list[User]:
        return self._accounts.list_users(admin.tenant_id)

    def create(self, admin: Identity, username: str, password: str, role: Role) -> User:
        login = check_new_account(username, password)
        if self._accounts.get_user_by_username(login) is not None:
            raise username_taken()
        user = self._auth.add_user(admin.tenant_id, login, password, role)
        self._record(admin, "user.create", user, f"role={role.value}")
        return user

    def update(
        self, admin: Identity, user_id: uuid.UUID, *, role: Role | None, is_active: bool | None
    ) -> User:
        user = self._get(admin, user_id)
        if user.id == admin.user_id:
            raise AppError(
                "Administrators cannot change their own role or disable themselves.",
                code="cannot_modify_self",
                status_code=HTTPStatus.CONFLICT,
            )
        changes = []
        if role is not None and role != user.role:
            changes.append(f"role={user.role}->{role.value}")
            user.role = role
        if is_active is not None and is_active != user.is_active:
            changes.append("enabled" if is_active else "disabled")
            user.is_active = is_active
            if is_active:  # a re-enabled user starts without a lockout
                user.failed_logins = 0
                user.locked_until = None
        self._accounts.save()
        if is_active is False:
            self._accounts.revoke_all_sessions(user.id, utc_now())
        if changes:
            self._record(admin, "user.update", user, " ".join(changes))
        return user

    def reset_password(self, admin: Identity, user_id: uuid.UUID, password: str) -> None:
        user = self._get(admin, user_id)
        check_new_password(password, user.username)
        user.password_hash = hash_password(password, n=self._policy.password_hash_n)
        user.failed_logins = 0
        user.locked_until = None
        self._accounts.save()
        self._accounts.revoke_all_sessions(user.id, utc_now())
        self._record(admin, "user.password_reset", user, None)

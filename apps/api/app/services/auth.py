"""Sign-in, sessions and user creation (Phase 6, P6-M1, ADR-031).

A successful sign-in returns a random token once; only its SHA-256 is stored.
Requests send it as ``Authorization: Bearer <token>``. A session ends at its
absolute expiry, after the idle limit without use, at logout, or when the user
is disabled. Every sign-in failure gives the same answer, and an unknown user
still costs one password check, so responses do not reveal which usernames
exist. After MAX_FAILED_LOGINS consecutive failures an account is locked for
LOCKOUT. Sign-ins, failures and logouts are audited (P6-M2). Passwords and
tokens are never logged or audited.
"""

import hashlib
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id
from app.core.errors import AppError
from app.core.identity import Identity
from app.core.passwords import (
    MAX_PASSWORD_CHARS,
    PasswordPolicyError,
    check_password_policy,
    hash_password,
    verify_password,
)
from app.core.roles import Role
from app.db.accounts import User
from app.db.audit import AuditOutcome
from app.db.types import utc_now
from app.repositories.accounts import AccountRepository
from app.repositories.audit import AuditRepository

logger = logging.getLogger(__name__)

USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
TENANT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,99}")
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
# last_seen_at is written at most this often (one write per minute, not per request).
TOUCH_INTERVAL = timedelta(minutes=1)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{20,100}")


@dataclass(frozen=True)
class SessionPolicy:
    idle: timedelta
    lifetime: timedelta
    password_hash_n: int


@dataclass(frozen=True)
class SignIn:
    token: str
    expires_at: datetime
    user: User


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@cache
def _dummy_hash(n: int) -> str:
    # Checked when the user does not exist, so that case takes as long as a real one.
    return hash_password(secrets.token_urlsafe(16), n=n)


def _invalid_credentials() -> AppError:
    return AppError(
        "Invalid username or password.",
        code="invalid_credentials",
        status_code=HTTPStatus.UNAUTHORIZED,
    )


def not_authenticated() -> AppError:
    return AppError(
        "Authentication required.",
        code="not_authenticated",
        status_code=HTTPStatus.UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


# Audit records of sign-ins for unknown usernames belong to no tenant or user;
# the typed name is not stored (it may be a mistyped password).
NO_ID = uuid.UUID(int=0)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def check_new_account(username: str, password: str) -> str:
    """The normalized username if it and the password meet the rules; 422 otherwise."""
    login = normalize_username(username)
    if not USERNAME.fullmatch(login):
        raise _bad_request("The username must have 3-64 lowercase letters, digits or . _ -")
    check_new_password(password, login)
    return login


def check_new_password(password: str, username: str) -> None:
    try:
        check_password_policy(password, username)
    except PasswordPolicyError as error:
        raise _bad_request(str(error)) from None


def username_taken() -> AppError:
    return AppError(
        "The username is taken.", code="username_taken", status_code=HTTPStatus.CONFLICT
    )


class AuthService:
    def __init__(
        self,
        session: Session,
        policy: SessionPolicy,
        role_permissions: dict[Role, frozenset[str]],
        audit: AuditRepository | None = None,
    ) -> None:
        self._accounts = AccountRepository(session)
        self._policy = policy
        self._role_permissions = role_permissions
        self._audit = audit

    def _record(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        target: str,
        outcome: AuditOutcome,
        detail: str | None = None,
    ) -> None:
        if self._audit is not None:
            self._audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                target=target,
                outcome=outcome,
                detail=detail,
                correlation_id=get_correlation_id(),
            )

    def create_user(self, tenant_name: str, username: str, password: str, role: Role) -> User:
        """Create a user in a tenant given by name (created if new); used by the CLI."""
        name = tenant_name.strip()
        if not TENANT_NAME.fullmatch(name):
            raise _bad_request("The tenant name must have 1-100 letters, digits, spaces or . _ -")
        login = check_new_account(username, password)
        if self._accounts.get_user_by_username(login) is not None:
            raise username_taken()
        tenant = self._accounts.get_or_create_tenant(name)
        user = self.add_user(tenant.id, login, password, role)
        # No signed-in actor on the command line: the record names the new user.
        self._record(
            tenant.id,
            user.id,
            "user.create",
            f"user:{user.id}",
            AuditOutcome.SUCCEEDED,
            f"cli role={role.value}",
        )
        return user

    def add_user(self, tenant_id: uuid.UUID, login: str, password: str, role: Role) -> User:
        """Insert a user whose username and password were already checked."""
        try:
            user = self._accounts.create_user(
                tenant_id, login, hash_password(password, n=self._policy.password_hash_n), role
            )
        except IntegrityError:  # created concurrently
            raise username_taken() from None
        logger.info("user created", extra={"user_id": str(user.id), "role": role.value})
        return user

    def login(self, username: str, password: str) -> SignIn:
        now = utc_now()
        user = self._accounts.get_user_by_username(normalize_username(username))
        if user is None or len(password) > MAX_PASSWORD_CHARS:
            verify_password(
                password[:MAX_PASSWORD_CHARS], _dummy_hash(self._policy.password_hash_n)
            )
            if user is None:
                self._record(
                    NO_ID, NO_ID, "auth.login", "unknown", AuditOutcome.FAILED, "unknown_user"
                )
            raise _invalid_credentials()
        target = f"user:{user.id}"
        if not user.is_active or (user.locked_until is not None and user.locked_until > now):
            verify_password(password, _dummy_hash(self._policy.password_hash_n))
            reason = "inactive" if not user.is_active else "locked"
            logger.info("sign-in refused", extra={"user_id": str(user.id), "reason": reason})
            self._record(user.tenant_id, user.id, "auth.login", target, AuditOutcome.DENIED, reason)
            raise _invalid_credentials()
        if not verify_password(password, user.password_hash):
            user.failed_logins += 1
            detail = "invalid_password"
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT
                user.failed_logins = 0
                detail = "invalid_password lockout_started"
            self._accounts.save()
            logger.info("sign-in failed", extra={"user_id": str(user.id)})
            self._record(user.tenant_id, user.id, "auth.login", target, AuditOutcome.FAILED, detail)
            raise _invalid_credentials()
        user.failed_logins = 0
        user.locked_until = None
        token = secrets.token_urlsafe(32)
        expires_at = now + self._policy.lifetime
        self._accounts.create_session(user.id, token_digest(token), expires_at)
        logger.info("signed in", extra={"user_id": str(user.id)})
        self._record(user.tenant_id, user.id, "auth.login", target, AuditOutcome.SUCCEEDED)
        return SignIn(token, expires_at, user)

    def authenticate(self, token: str) -> Identity:
        """The identity of a valid session token; 401 otherwise."""
        if not _TOKEN.fullmatch(token):
            raise not_authenticated()
        now = utc_now()
        stored = self._accounts.get_session(token_digest(token))
        if (
            stored is None
            or stored.revoked_at is not None
            or now >= stored.expires_at
            or now - stored.last_seen_at >= self._policy.idle
        ):
            raise not_authenticated()
        user = self._accounts.get_user(stored.user_id)
        if user is None or not user.is_active:
            raise not_authenticated()
        if now - stored.last_seen_at >= TOUCH_INTERVAL:
            stored.last_seen_at = now
            self._accounts.save()
        return Identity(
            tenant_id=user.tenant_id,
            user_id=user.id,
            permissions=self._role_permissions.get(user.role, frozenset()),
            role=user.role,
        )

    def logout(self, token: str, identity: Identity) -> None:
        if _TOKEN.fullmatch(token):
            self._accounts.revoke_session(token_digest(token), utc_now())
            self._record(
                identity.tenant_id,
                identity.user_id,
                "auth.logout",
                f"user:{identity.user_id}",
                AuditOutcome.SUCCEEDED,
            )


def _bad_request(message: str) -> AppError:
    return AppError(message, code="invalid_account", status_code=HTTPStatus.UNPROCESSABLE_CONTENT)

"""Sign-in, sessions and user creation (Phase 6, P6-M1, ADR-031).

A successful sign-in returns a random token once; only its SHA-256 is stored.
Requests send it as ``Authorization: Bearer <token>``. A session ends at its
absolute expiry, after the idle limit without use, at logout, or when the user
is disabled. Every sign-in failure gives the same answer, and an unknown user
still costs one password check, so responses do not reveal which usernames
exist. After MAX_FAILED_LOGINS consecutive failures an account is locked for
LOCKOUT. Passwords and tokens are never logged.
"""

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.db.types import utc_now
from app.repositories.accounts import AccountRepository

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


class AuthService:
    def __init__(
        self,
        session: Session,
        policy: SessionPolicy,
        role_permissions: dict[Role, frozenset[str]],
    ) -> None:
        self._accounts = AccountRepository(session)
        self._policy = policy
        self._role_permissions = role_permissions

    def create_user(self, tenant_name: str, username: str, password: str, role: Role) -> User:
        name = tenant_name.strip()
        login = username.strip().lower()
        if not TENANT_NAME.fullmatch(name):
            raise _bad_request("The tenant name must have 1-100 letters, digits, spaces or . _ -")
        if not USERNAME.fullmatch(login):
            raise _bad_request("The username must have 3-64 lowercase letters, digits or . _ -")
        try:
            check_password_policy(password, login)
        except PasswordPolicyError as error:
            raise _bad_request(str(error)) from None
        if self._accounts.get_user_by_username(login) is not None:
            raise AppError(
                "The username is taken.", code="username_taken", status_code=HTTPStatus.CONFLICT
            )
        tenant = self._accounts.get_or_create_tenant(name)
        try:
            user = self._accounts.create_user(
                tenant.id, login, hash_password(password, n=self._policy.password_hash_n), role
            )
        except IntegrityError:  # created concurrently
            raise AppError(
                "The username is taken.", code="username_taken", status_code=HTTPStatus.CONFLICT
            ) from None
        logger.info("user created", extra={"user_id": str(user.id), "role": role.value})
        return user

    def login(self, username: str, password: str) -> SignIn:
        now = utc_now()
        user = self._accounts.get_user_by_username(username.strip().lower())
        if user is None or len(password) > MAX_PASSWORD_CHARS:
            verify_password(
                password[:MAX_PASSWORD_CHARS], _dummy_hash(self._policy.password_hash_n)
            )
            raise _invalid_credentials()
        if not user.is_active or (user.locked_until is not None and user.locked_until > now):
            verify_password(password, _dummy_hash(self._policy.password_hash_n))
            logger.info(
                "sign-in refused", extra={"user_id": str(user.id), "reason": "inactive_or_locked"}
            )
            raise _invalid_credentials()
        if not verify_password(password, user.password_hash):
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT
                user.failed_logins = 0
            self._accounts.save()
            logger.info("sign-in failed", extra={"user_id": str(user.id)})
            raise _invalid_credentials()
        user.failed_logins = 0
        user.locked_until = None
        token = secrets.token_urlsafe(32)
        expires_at = now + self._policy.lifetime
        self._accounts.create_session(user.id, token_digest(token), expires_at)
        logger.info("signed in", extra={"user_id": str(user.id)})
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

    def logout(self, token: str) -> None:
        if _TOKEN.fullmatch(token):
            self._accounts.revoke_session(token_digest(token), utc_now())


def _bad_request(message: str) -> AppError:
    return AppError(message, code="invalid_account", status_code=HTTPStatus.UNPROCESSABLE_CONTENT)

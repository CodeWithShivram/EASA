"""Data access for tenants, users and sign-in sessions."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.roles import Role
from app.db.accounts import Tenant, User, UserSession


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create_tenant(self, name: str) -> Tenant:
        tenant = self._session.scalar(select(Tenant).where(Tenant.name == name))
        if tenant is None:
            tenant = Tenant(name=name)
            self._session.add(tenant)
            self._session.flush()
        return tenant

    def get_user(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self._session.scalar(select(User).where(User.username == username))

    def create_user(
        self, tenant_id: uuid.UUID, username: str, password_hash: str, role: Role
    ) -> User:
        user = User(tenant_id=tenant_id, username=username, password_hash=password_hash, role=role)
        self._session.add(user)
        self._session.commit()
        return user

    def list_users(self, tenant_id: uuid.UUID) -> list[User]:
        return list(
            self._session.scalars(
                select(User).where(User.tenant_id == tenant_id).order_by(User.username)
            )
        )

    def save(self) -> None:
        self._session.commit()

    def create_session(self, user_id: uuid.UUID, token_sha256: str, expires_at: datetime) -> None:
        self._session.add(
            UserSession(user_id=user_id, token_sha256=token_sha256, expires_at=expires_at)
        )
        self._session.commit()

    def get_session(self, token_sha256: str) -> UserSession | None:
        return self._session.scalar(
            select(UserSession).where(UserSession.token_sha256 == token_sha256)
        )

    def revoke_session(self, token_sha256: str, now: datetime) -> None:
        self._session.execute(
            update(UserSession)
            .where(UserSession.token_sha256 == token_sha256, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        self._session.commit()

    def revoke_all_sessions(self, user_id: uuid.UUID, now: datetime) -> None:
        self._session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        self._session.commit()

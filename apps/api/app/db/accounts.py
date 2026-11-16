"""Tenants, users and sign-in sessions (Phase 6, P6-M1, ADR-031).

A user belongs to one tenant and has one role. Usernames are unique across the
installation, so signing in needs no tenant name. A session stores only the
SHA-256 of its token; the token itself is shown once, at sign-in. Existing
tables keep their tenant_id columns without a foreign key to ``tenants`` for
now (rows created before Phase 6 have no tenant row).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.roles import Role
from app.db.base import Base
from app.db.documents import _allowed_values_check, _enum_column
from app.db.types import UtcDateTime, utc_now


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (_allowed_values_check("role", Role),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    # Lowercase letters, digits and . _ - (app.services.auth.USERNAME).
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum_column(Role, 20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Consecutive failed sign-ins; reset by a successful one.
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, onupdate=utc_now)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    # Absolute end; the idle limit is checked against last_seen_at.
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

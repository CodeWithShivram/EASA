import os
import secrets
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.passwords import hash_password
from app.core.roles import Role
from app.db.accounts import Tenant, User
from app.db.fts import create_keyword_index
from app.db.models import Base
from app.db.types import utc_now
from app.main import create_app
from app.repositories.accounts import AccountRepository
from app.services.auth import token_digest

# The default signed-in test user (synthetic).
DEV_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
TEST_PASSWORD = "synthetic-test-password"  # noqa: S105 - test data only
TEST_HASH_N = 2**10  # fast scrypt for tests


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's EASA_* variables and .env file out of tests."""
    for key in list(os.environ):
        if key.startswith("EASA_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": sqlite_url(tmp_path / "var" / "test.db"),
        "storage_dir": tmp_path / "var" / "uploads",
        # Deterministic, offline embedder; the real model has its own tests.
        "embedding_provider": "hashing",
        "password_hash_n": TEST_HASH_N,
        # Rate limits are tested on their own (test_hardening_api.py).
        "rate_limit_login_per_minute": 0,
        "rate_limit_model_per_minute": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def broken_db_client(tmp_path: Path) -> Iterator[TestClient]:
    # A directory is not a valid SQLite database file, so connecting fails.
    unusable = tmp_path / "not-a-database"
    unusable.mkdir()
    settings = make_settings(tmp_path, database_url=sqlite_url(unusable))
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def create_schema(engine: Engine) -> None:
    """Create all tables plus the SQLite keyword index (what migrations produce)."""
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        create_keyword_index(connection)


def add_user(
    app: FastAPI,
    *,
    user_id: uuid.UUID = DEV_USER_ID,
    tenant_id: uuid.UUID = DEV_TENANT_ID,
    username: str | None = None,
    role: Role = Role.EMPLOYEE,
    password: str = TEST_PASSWORD,
    active: bool = True,
) -> None:
    """Create the user (and its tenant) unless it exists. Tables must exist."""
    with app.state.session_factory() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, name=f"tenant-{tenant_id}"))
        if session.get(User, user_id) is None:
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    username=username or f"user-{user_id.hex[:12]}",
                    password_hash=hash_password(password, n=TEST_HASH_N),
                    role=role,
                    is_active=active,
                )
            )
        session.commit()


def sign_in(app: FastAPI, **user: object) -> dict[str, str]:
    """Headers of a fresh session for the user (created if needed), without the login route."""
    add_user(app, **user)  # type: ignore[arg-type]
    token = secrets.token_urlsafe(32)
    with app.state.session_factory() as session:
        AccountRepository(session).create_session(
            user.get("user_id", DEV_USER_ID),  # type: ignore[arg-type]
            token_digest(token),
            utc_now() + timedelta(hours=1),
        )
    return {"Authorization": f"Bearer {token}"}


def limit_permissions(app: FastAPI, *permissions: str) -> None:
    """Make every role grant exactly these permissions (for permission tests)."""
    app.state.role_permissions = dict.fromkeys(Role, frozenset(permissions))

import io
import logging
import re
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.core.passwords import DEFAULT_N
from app.core.roles import ROLE_PERMISSIONS, Role
from app.db.accounts import User, UserSession
from app.db.types import utc_now
from app.main import create_app
from app.services.auth import MAX_FAILED_LOGINS
from tests.conftest import (
    DEV_USER_ID,
    TEST_PASSWORD,
    add_user,
    create_schema,
    limit_permissions,
    make_settings,
    sign_in,
)
from tests.fixtures import TXT_BYTES

USERNAME = "alice"
WRONG_PASSWORD = "wrong password!"  # noqa: S105 - test data only


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path))
    create_schema(app.state.engine)
    add_user(app, username=USERNAME, role=Role.MANAGER)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str = USERNAME, password: str = TEST_PASSWORD):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sessions(app: FastAPI) -> list[UserSession]:
    with app.state.session_factory() as session:
        return list(session.scalars(select(UserSession)))


def update_user(app: FastAPI, **values: object) -> None:
    with app.state.session_factory() as session:
        user = session.get(User, DEV_USER_ID)
        assert user is not None
        for key, value in values.items():
            setattr(user, key, value)
        session.commit()


# --- sign-in ------------------------------------------------------------------


def test_login_returns_a_token_that_identifies_the_user(client: TestClient, app: FastAPI) -> None:
    response = login(client, "  ALICE ")  # usernames are case-insensitive

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"  # noqa: S105
    assert body["user"]["username"] == USERNAME
    assert body["user"]["role"] == "manager"
    assert body["user"]["permissions"] == sorted(ROLE_PERMISSIONS[Role.MANAGER])
    me = client.get("/api/v1/auth/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert me.json() == body["user"]
    # Only a digest of the token is stored.
    [stored] = sessions(app)
    assert stored.token_sha256 != body["token"]
    assert len(stored.token_sha256) == 64


@pytest.mark.parametrize(
    ("username", "password", "state"),
    [
        (USERNAME, WRONG_PASSWORD, {}),
        ("nobody", TEST_PASSWORD, {}),
        (USERNAME, TEST_PASSWORD, {"is_active": False}),
    ],
)
def test_every_failed_sign_in_looks_the_same(
    client: TestClient, app: FastAPI, username: str, password: str, state: dict[str, object]
) -> None:
    update_user(app, **state)

    response = login(client, username, password)

    assert response.status_code == 401
    error = response.json()["error"]
    assert (error["code"], error["message"]) == (
        "invalid_credentials",
        "Invalid username or password.",
    )
    assert sessions(app) == []


def test_repeated_failures_lock_the_account(client: TestClient, app: FastAPI) -> None:
    for _ in range(MAX_FAILED_LOGINS):
        assert login(client, password=WRONG_PASSWORD).status_code == 401

    # Locked: even the right password fails, with the same answer.
    assert login(client).status_code == 401

    update_user(app, locked_until=utc_now() - timedelta(seconds=1))
    assert login(client).status_code == 200


def test_a_successful_sign_in_resets_the_failure_count(client: TestClient, app: FastAPI) -> None:
    for _ in range(MAX_FAILED_LOGINS - 1):
        login(client, password=WRONG_PASSWORD)
    assert login(client).status_code == 200

    for _ in range(MAX_FAILED_LOGINS - 1):
        login(client, password=WRONG_PASSWORD)
    assert login(client).status_code == 200  # still not locked


@pytest.mark.parametrize(
    "payload",
    [{}, {"username": "alice"}, {"username": "alice", "password": "x" * 129}, {"user": "a"}],
)
def test_invalid_login_requests_are_rejected(client: TestClient, payload: dict[str, str]) -> None:
    assert client.post("/api/v1/auth/login", json=payload).status_code == 422


# --- sessions -----------------------------------------------------------------


def test_logout_ends_the_session(client: TestClient) -> None:
    token = login(client).json()["token"]

    assert client.post("/api/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    # Other sessions of the same user are unaffected.
    other = login(client).json()["token"]
    assert client.get("/api/v1/auth/me", headers=bearer(other)).status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"expires_at": timedelta(seconds=-1)},  # absolute lifetime over
        {"last_seen_at": timedelta(hours=-9)},  # idle for longer than 8 hours
        {"revoked_at": timedelta(0)},
    ],
)
def test_expired_idle_and_revoked_sessions_are_refused(
    client: TestClient, app: FastAPI, change: dict[str, timedelta]
) -> None:
    token = login(client).json()["token"]
    with app.state.session_factory() as session:
        stored = session.scalars(select(UserSession)).one()
        for key, offset in change.items():
            setattr(stored, key, utc_now() + offset)
        session.commit()

    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_disabling_a_user_ends_their_sessions(client: TestClient, app: FastAPI) -> None:
    token = login(client).json()["token"]
    update_user(app, is_active=False)

    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_a_role_change_applies_to_existing_sessions(client: TestClient, app: FastAPI) -> None:
    token = login(client).json()["token"]
    limit_permissions(app, "knowledge:search")

    assert client.get("/api/v1/auth/me", headers=bearer(token)).json()["permissions"] == [
        "knowledge:search"
    ]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
        {"Authorization": "Bearer " + "A" * 43},  # well-formed but unknown
        {"X-User-Id": str(DEV_USER_ID)},  # identity headers are ignored
    ],
)
def test_requests_without_a_valid_token_are_refused(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "not_authenticated"


def test_tokens_in_the_url_are_ignored(client: TestClient) -> None:
    token = login(client).json()["token"]

    assert client.get(f"/api/v1/auth/me?token={token}").status_code == 401
    assert client.get(f"/api/v1/auth/me?access_token={token}").status_code == 401


# --- every protected route ----------------------------------------------------

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/login"),
}


def protected_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every API route from the OpenAPI schema (it lists included routers too)."""
    routes = []
    for template, operations in app.openapi()["paths"].items():
        for method in operations:
            if (method.upper(), template) not in PUBLIC:
                path = re.sub(r"\{[a-z_]*id\}", str(uuid.uuid4()), template)
                routes.append((method.upper(), path.replace("{name}", "get_ticket")))
    return routes


@pytest.mark.parametrize("environment", ["development", "production"])
def test_every_route_except_health_and_login_requires_a_session(
    tmp_path: Path, environment: str
) -> None:
    settings = make_settings(tmp_path, environment=environment, password_hash_n=DEFAULT_N)
    app = create_app(settings)
    routes = protected_routes(app)
    with TestClient(app) as client:
        results = {(m, p): client.request(m, p).status_code for m, p in routes}
    app.state.engine.dispose()

    assert len(routes) == {"development": 25, "production": 23}[environment]
    assert {key: status for key, status in results.items() if status != 401} == {}


# --- isolation and logging ----------------------------------------------------


def test_users_see_only_their_own_tenants_documents(app: FastAPI) -> None:
    other_tenant, other_user = uuid.uuid4(), uuid.uuid4()
    with TestClient(app, headers=sign_in(app)) as mine:
        uploaded = mine.post(
            "/api/v1/documents", files={"file": ("policy.txt", TXT_BYTES, "text/plain")}
        ).json()
    other = sign_in(app, user_id=other_user, tenant_id=other_tenant, username="bob")
    with TestClient(app, headers=other) as theirs:
        listed = theirs.get("/api/v1/documents").json()["items"]
        fetched = theirs.get(f"/api/v1/documents/{uploaded['id']}")

    assert listed == []
    assert fetched.status_code == 404


def test_passwords_and_tokens_are_never_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        login(client, password=WRONG_PASSWORD)
        token = login(client).json()["token"]
        client.get("/api/v1/auth/me", headers=bearer(token))

    logged = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert WRONG_PASSWORD not in logged
    assert TEST_PASSWORD not in logged
    assert token not in logged
    assert "signed in" in caplog.text
    assert "sign-in failed" in caplog.text


# --- commands -----------------------------------------------------------------


def run_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str], stdin: str = ""
) -> int:
    monkeypatch.setenv("EASA_DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    monkeypatch.setenv("EASA_PASSWORD_HASH_N", "1024")
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(args)


def test_create_user_and_seed_tickets_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        make_settings(tmp_path, database_url=f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    )
    create_schema(app.state.engine)
    app.state.engine.dispose()
    args = ["create-user", "--tenant", "Larkspur", "--username", "Carol", "--role", "employee"]

    assert (
        run_cli(monkeypatch, tmp_path, [*args, "--password-stdin"], "a synthetic password\n") == 0
    )
    # Taken username, weak password, unknown user for seeding: refused.
    assert run_cli(monkeypatch, tmp_path, [*args, "--password-stdin"], "another password!\n") == 1
    weak = ["create-user", "--tenant", "Larkspur", "--username", "dave", "--role", "employee"]
    assert run_cli(monkeypatch, tmp_path, [*weak, "--password-stdin"], "short\n") == 1
    assert run_cli(monkeypatch, tmp_path, ["seed-tickets", "--username", "nobody"]) == 1
    assert run_cli(monkeypatch, tmp_path, ["seed-tickets", "--username", "carol"]) == 0

    with TestClient(app) as client:
        response = login(client, "carol", "a synthetic password")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "employee"

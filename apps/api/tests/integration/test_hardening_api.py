"""Security headers and rate limits (P8-M1)."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.passwords import DEFAULT_N
from app.core.roles import Role
from app.main import create_app
from tests.conftest import TEST_PASSWORD, add_user, create_schema, make_settings, sign_in


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(
        make_settings(
            tmp_path,
            model_provider="fake",
            rate_limit_login_per_minute=3,
            rate_limit_model_per_minute=2,
        )
    )
    create_schema(app.state.engine)
    add_user(app, username="alice", role=Role.MANAGER)
    yield app
    app.state.engine.dispose()


# --- headers -------------------------------------------------------------------


def test_api_responses_carry_defensive_headers(app: FastAPI) -> None:
    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/health"),
            client.get("/api/v1/auth/me"),
            client.get("/nope"),
        ]

    for response in responses:  # success, 401 and 404 alike
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert (
            response.headers["Content-Security-Policy"]
            == "default-src 'none'; frame-ancestors 'none'"
        )
        assert response.headers["Cache-Control"] == "no-store"
        assert "Strict-Transport-Security" not in response.headers  # not production


def test_the_docs_keep_their_own_scripts(app: FastAPI) -> None:
    with TestClient(app) as client:
        docs = client.get("/docs")

    assert docs.status_code == 200
    assert "Content-Security-Policy" not in docs.headers
    assert docs.headers["X-Content-Type-Options"] == "nosniff"


def test_production_adds_hsts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, environment="production", password_hash_n=DEFAULT_N)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


# --- rate limits ----------------------------------------------------------------


def login(client: TestClient, password: str = TEST_PASSWORD, forwarded: str | None = None) -> int:
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    response = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": password}, headers=headers
    )
    return response.status_code


def test_sign_in_attempts_are_limited_per_address(app: FastAPI) -> None:
    with TestClient(app) as client:
        statuses = [login(client, "wrong password!!") for _ in range(3)] + [login(client)]
        limited = client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": TEST_PASSWORD}
        )

    assert statuses == [401, 401, 401, 429]  # even the right password once the limit is reached
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= 60


def test_a_forged_forwarded_address_does_not_reset_the_limit(app: FastAPI) -> None:
    # The test client's peer is not a trusted proxy, so X-Forwarded-For is ignored.
    with TestClient(app) as client:
        statuses = [login(client, forwarded=f"198.51.100.{i}") for i in range(4)]

    assert statuses == [200, 200, 200, 429]


def test_behind_a_trusted_proxy_each_client_has_its_own_limit(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, rate_limit_login_per_minute=1))
    create_schema(app.state.engine)
    add_user(app, username="alice")
    # The test client's peer is named "testclient", not an IP address, so the settings
    # validator would refuse it; trust it by replacing the loaded settings.
    app.state.settings = app.state.settings.model_copy(update={"trusted_proxies": ["testclient"]})
    with TestClient(app) as client:
        first = [login(client, forwarded="198.51.100.1"), login(client, forwarded="198.51.100.1")]
        other = login(client, forwarded="198.51.100.2")
    app.state.engine.dispose()

    assert (first, other) == ([200, 429], 200)


def test_model_calls_are_limited_per_user(app: FastAPI) -> None:
    other = uuid.uuid4()
    with TestClient(app) as client:
        mine = sign_in(app)
        theirs = sign_in(app, user_id=other, username="bob")
        statuses = [
            client.post(
                "/api/v1/answers", json={"question": "Leave days?"}, headers=mine
            ).status_code
            for _ in range(3)
        ]
        agent = client.post("/api/v1/agent", json={"message": "Hi"}, headers=mine)
        someone_else = client.post(
            "/api/v1/answers", json={"question": "Leave days?"}, headers=theirs
        )

    assert statuses == [200, 200, 429]
    assert agent.status_code == 429  # the agent shares the user's model budget
    assert someone_else.status_code == 200


def test_reading_is_never_rate_limited(app: FastAPI) -> None:
    with TestClient(app, headers=sign_in(app)) as client:
        statuses = {client.get("/api/v1/documents").status_code for _ in range(10)}

    assert statuses == {200}

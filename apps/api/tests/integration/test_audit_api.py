"""GET /api/v1/audit (P6-M4): the tenant's audit log for administrators."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.roles import Role
from app.db.audit import AuditOutcome
from app.main import create_app
from app.repositories.audit import AuditRepository
from tests.conftest import DEV_TENANT_ID, add_user, create_schema, make_settings, sign_in

ADMIN_ID = uuid.UUID("00000000-0000-4000-8000-0000000000d1")
EMPLOYEE_ID = uuid.UUID("00000000-0000-4000-8000-0000000000d2")


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path))
    create_schema(app.state.engine)
    add_user(app, user_id=ADMIN_ID, username="auditor", role=Role.ADMINISTRATOR)
    add_user(app, user_id=EMPLOYEE_ID, username="worker", role=Role.EMPLOYEE)
    audit = AuditRepository(app.state.session_factory)
    for i in range(5):
        audit.record(
            tenant_id=DEV_TENANT_ID,
            user_id=EMPLOYEE_ID,
            action="tool.execute",
            target="get_ticket",
            outcome=AuditOutcome.SUCCEEDED if i % 2 else AuditOutcome.DENIED,
            arguments={"number": i},
        )
    audit.record(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        action="tool.execute",
        target="get_ticket",
        outcome=AuditOutcome.SUCCEEDED,
    )
    yield app
    app.state.engine.dispose()


@pytest.fixture
def admin(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=sign_in(app, user_id=ADMIN_ID)) as client:
        yield client


def test_administrators_read_their_tenants_records_newest_first(admin: TestClient) -> None:
    body = admin.get("/api/v1/audit").json()

    assert (body["limit"], body["offset"]) == (50, 0)
    assert len(body["items"]) == 5  # the other tenant's record is not shown
    times = [r["created_at"] for r in body["items"]]
    assert times == sorted(times, reverse=True)
    first = body["items"][0]
    assert set(first) == {
        "id",
        "created_at",
        "user_id",
        "action",
        "target",
        "outcome",
        "detail",
        "arguments_digest",
        "correlation_id",
        "duration_ms",
    }
    assert len(first["arguments_digest"]) == 64  # a digest, never the arguments


def test_filters_and_paging(admin: TestClient) -> None:
    denied = admin.get("/api/v1/audit", params={"outcome": "denied"}).json()["items"]
    by_user = admin.get("/api/v1/audit", params={"user_id": str(EMPLOYEE_ID)}).json()["items"]
    page = admin.get(
        "/api/v1/audit", params={"action": "tool.execute", "limit": 2, "offset": 2}
    ).json()

    assert [r["outcome"] for r in denied] == ["denied"] * 3
    assert len(by_user) == 5
    assert len(page["items"]) == 2


def test_reading_the_log_is_audited(admin: TestClient) -> None:
    admin.get("/api/v1/audit", params={"outcome": "denied"})

    reads = admin.get("/api/v1/audit", params={"action": "audit.read"}).json()["items"]

    # The current read is recorded after the list is fetched, so only the earlier one shows.
    assert [r["detail"] for r in reads] == ["outcome=denied"]
    assert all(r["user_id"] == str(ADMIN_ID) for r in reads)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"outcome": "maybe"},
        {"user_id": "not-a-uuid"},
        {"action": "tool.execute' OR 1=1 --"},
        {"action": "TOOL.EXECUTE"},
    ],
)
def test_invalid_filters_are_rejected(admin: TestClient, params: dict[str, object]) -> None:
    assert admin.get("/api/v1/audit", params=params).status_code == 422


def test_other_roles_cannot_read_the_log(app: FastAPI) -> None:
    with TestClient(app, headers=sign_in(app, user_id=EMPLOYEE_ID)) as client:
        response = client.get("/api/v1/audit")

    assert response.status_code == 403

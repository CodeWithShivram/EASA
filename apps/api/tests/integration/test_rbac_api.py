"""Roles, permissions, user administration and audit (P6-M2)."""

import logging
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.identity import Identity
from app.core.roles import ROLE_PERMISSIONS, Role
from app.db.audit import AuditLog, AuditOutcome
from app.main import create_app
from app.services.auth import NO_ID
from app.tools.seed import seed_tickets
from tests.conftest import (
    DEV_TENANT_ID,
    DEV_USER_ID,
    TEST_PASSWORD,
    add_user,
    create_schema,
    make_settings,
    sign_in,
)

ADMIN_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
EMPLOYEE_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a2")
OTHER_TENANT = uuid.UUID("00000000-0000-4000-8000-0000000000b1")
OTHER_ADMIN_ID = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
NEW_PASSWORD = "another synthetic password"  # noqa: S105 - test data only


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path))
    create_schema(app.state.engine)
    add_user(app, user_id=ADMIN_ID, username="admin", role=Role.ADMINISTRATOR)
    add_user(app, user_id=EMPLOYEE_ID, username="erin", role=Role.EMPLOYEE)
    add_user(
        app,
        user_id=OTHER_ADMIN_ID,
        tenant_id=OTHER_TENANT,
        username="other-admin",
        role=Role.ADMINISTRATOR,
    )
    yield app
    app.state.engine.dispose()


def client_as(app: FastAPI, user_id: uuid.UUID, **user: object) -> TestClient:
    return TestClient(app, headers=sign_in(app, user_id=user_id, **user))


def audit(app: FastAPI, action: str) -> list[AuditLog]:
    with app.state.session_factory() as session:
        return list(
            session.scalars(
                select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
            )
        )


def login(client: TestClient, username: str, password: str = TEST_PASSWORD) -> int:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return response.status_code


# --- the role table -------------------------------------------------------------

# Route (method, template) -> the permission it requires. Routes not listed here
# need only a session (they are checked per tool or concern the user's own session).
REQUIRED = {
    ("POST", "/api/v1/documents"): "documents:upload",
    ("GET", "/api/v1/documents"): "documents:read",
    ("GET", "/api/v1/documents/{document_id}"): "documents:read",
    ("PATCH", "/api/v1/documents/{document_id}"): "documents:upload",
    ("GET", "/api/v1/documents/{document_id}/chunks"): "documents:read",
    ("POST", "/api/v1/search"): "knowledge:search",
    ("POST", "/api/v1/answers"): "knowledge:search",
    ("POST", "/api/v1/conversations"): "knowledge:search",
    ("GET", "/api/v1/conversations"): "knowledge:search",
    ("GET", "/api/v1/conversations/{conversation_id}"): "knowledge:search",
    ("DELETE", "/api/v1/conversations/{conversation_id}"): "knowledge:search",
    ("POST", "/api/v1/conversations/{conversation_id}/messages"): "knowledge:search",
    ("GET", "/api/v1/users"): "users:manage",
    ("POST", "/api/v1/users"): "users:manage",
    ("PATCH", "/api/v1/users/{user_id}"): "users:manage",
    ("POST", "/api/v1/users/{user_id}/password"): "users:manage",
}
SESSION_ONLY = {
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/agent"),
    ("GET", "/api/v1/agent/actions/{action_id}"),
    ("POST", "/api/v1/agent/actions/{action_id}/confirm"),
    ("POST", "/api/v1/agent/actions/{action_id}/cancel"),
    ("GET", "/api/v1/tools"),
    ("POST", "/api/v1/tools/{name}/invoke"),
}


def test_every_route_has_a_permission_decision(app: FastAPI) -> None:
    templates = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    public = {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/health/ready"),
        ("POST", "/api/v1/auth/login"),
    }

    assert templates - public == set(REQUIRED) | SESSION_ONLY


def test_permissions_grow_with_the_role() -> None:
    employee, manager, admin = (ROLE_PERMISSIONS[r] for r in Role)

    assert employee < manager < admin
    assert "documents:upload" not in employee
    assert "users:manage" not in manager


@pytest.mark.parametrize("role", list(Role))
def test_each_role_is_refused_exactly_what_it_lacks(app: FastAPI, role: Role) -> None:
    user_id = uuid.uuid4()
    with client_as(app, user_id, username=f"r-{role.value}", role=role) as client:
        statuses = {}
        for method, template in REQUIRED:
            path = template.replace("{document_id}", str(uuid.uuid4()))
            path = path.replace("{conversation_id}", str(uuid.uuid4()))
            path = path.replace("{user_id}", str(uuid.uuid4()))
            statuses[(method, template)] = client.request(method, path).status_code

    refused = {key for key, status in statuses.items() if status == 403}
    lacking = {
        key for key, permission in REQUIRED.items() if permission not in ROLE_PERMISSIONS[role]
    }
    assert refused == lacking


def test_refusals_are_audited(app: FastAPI) -> None:
    with client_as(app, EMPLOYEE_ID) as client:
        response = client.post(
            "/api/v1/documents", files={"file": ("a.txt", b"Some text here.", "text/plain")}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    [record] = audit(app, "access.denied")
    assert (record.user_id, record.target, record.detail, record.outcome) == (
        EMPLOYEE_ID,
        "POST /api/v1/documents",
        "documents:upload",
        AuditOutcome.DENIED,
    )
    assert record.correlation_id == response.headers["X-Correlation-ID"]


# --- user administration --------------------------------------------------------


def test_administrators_see_only_their_tenants_users(app: FastAPI) -> None:
    with client_as(app, ADMIN_ID) as client:
        names = [u["username"] for u in client.get("/api/v1/users").json()["items"]]

    assert names == ["admin", "erin"]


def test_created_users_can_sign_in_and_are_audited(app: FastAPI) -> None:
    body = {"username": "Frank", "password": NEW_PASSWORD, "role": "manager"}
    with client_as(app, ADMIN_ID) as client:
        created = client.post("/api/v1/users", json=body)
        again = client.post("/api/v1/users", json=body)
        weak = client.post("/api/v1/users", json={**body, "username": "gina", "password": "short"})
        foreign = client.post("/api/v1/users", json={**body, "tenant_id": str(OTHER_TENANT)})
        signed_in = login(client, "frank", NEW_PASSWORD)

    assert created.status_code == 201
    user = created.json()
    assert (user["username"], user["role"], user["is_active"], user["locked"]) == (
        "frank",
        "manager",
        True,
        False,
    )
    assert again.json()["error"]["code"] == "username_taken"
    assert (weak.status_code, weak.json()["error"]["code"]) == (422, "invalid_account")
    assert foreign.status_code == 422  # no way to pick another tenant
    assert signed_in == 200
    [record] = audit(app, "user.create")
    assert (record.user_id, record.target, record.detail) == (
        ADMIN_ID,
        f"user:{user['id']}",
        "role=manager",
    )


def test_role_changes_apply_to_existing_sessions(app: FastAPI) -> None:
    with client_as(app, EMPLOYEE_ID) as employee, client_as(app, ADMIN_ID) as admin:
        assert employee.get("/api/v1/users").status_code == 403
        promoted = admin.patch(f"/api/v1/users/{EMPLOYEE_ID}", json={"role": "administrator"})
        after = employee.get("/api/v1/users").status_code

    assert promoted.json()["role"] == "administrator"
    assert after == 200
    [record] = audit(app, "user.update")
    assert record.detail == "role=employee->administrator"


def test_disabling_ends_sessions_and_sign_in_until_enabled(app: FastAPI) -> None:
    with client_as(app, EMPLOYEE_ID) as employee, client_as(app, ADMIN_ID) as admin:
        disabled = admin.patch(f"/api/v1/users/{EMPLOYEE_ID}", json={"is_active": False})
        session_after = employee.get("/api/v1/auth/me").status_code
        login_disabled = login(admin, "erin")
        admin.patch(f"/api/v1/users/{EMPLOYEE_ID}", json={"is_active": True})
        login_enabled = login(admin, "erin")

    assert disabled.json()["is_active"] is False
    assert (session_after, login_disabled, login_enabled) == (401, 401, 200)
    assert [r.detail for r in audit(app, "user.update")] == ["disabled", "enabled"]


def test_password_reset_ends_sessions_and_replaces_the_password(app: FastAPI) -> None:
    with client_as(app, EMPLOYEE_ID) as employee, client_as(app, ADMIN_ID) as admin:
        reset = admin.post(f"/api/v1/users/{EMPLOYEE_ID}/password", json={"password": NEW_PASSWORD})
        session_after = employee.get("/api/v1/auth/me").status_code
        old, new = login(admin, "erin"), login(admin, "erin", NEW_PASSWORD)

    assert (reset.status_code, session_after, old, new) == (204, 401, 401, 200)
    [record] = audit(app, "user.password_reset")
    assert record.detail is None


def test_administrators_cannot_change_themselves(app: FastAPI) -> None:
    with client_as(app, ADMIN_ID) as client:
        demote = client.patch(f"/api/v1/users/{ADMIN_ID}", json={"role": "employee"})
        disable = client.patch(f"/api/v1/users/{ADMIN_ID}", json={"is_active": False})

    assert {demote.json()["error"]["code"], disable.json()["error"]["code"]} == {
        "cannot_modify_self"
    }


def test_other_tenants_users_look_missing(app: FastAPI) -> None:
    with client_as(app, ADMIN_ID) as client:
        patched = client.patch(f"/api/v1/users/{OTHER_ADMIN_ID}", json={"is_active": False})
        reset = client.post(
            f"/api/v1/users/{OTHER_ADMIN_ID}/password", json={"password": NEW_PASSWORD}
        )
        missing = client.patch(f"/api/v1/users/{uuid.uuid4()}", json={"is_active": False})

    assert {r.json()["error"]["code"] for r in (patched, reset, missing)} == {"user_not_found"}
    with client_as(app, OTHER_ADMIN_ID) as other:
        assert other.get("/api/v1/auth/me").status_code == 200  # untouched


@pytest.mark.parametrize("body", [{}, {"role": "owner"}, {"is_active": "maybe"}, {"username": "x"}])
def test_invalid_updates_are_rejected(app: FastAPI, body: dict[str, object]) -> None:
    with client_as(app, ADMIN_ID) as client:
        assert client.patch(f"/api/v1/users/{EMPLOYEE_ID}", json=body).status_code == 422


# --- audit of sign-ins ----------------------------------------------------------


def test_sign_ins_are_audited_without_secrets(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(app) as client, caplog.at_level(logging.DEBUG):
        login(client, "erin", "wrong password!!")
        login(client, "nobody-here", TEST_PASSWORD)
        login(client, "erin")
        client.post("/api/v1/auth/logout", headers=sign_in(app, user_id=EMPLOYEE_ID))

    records = audit(app, "auth.login")
    assert [(r.outcome, r.detail) for r in records] == [
        (AuditOutcome.FAILED, "invalid_password"),
        (AuditOutcome.FAILED, "unknown_user"),
        (AuditOutcome.SUCCEEDED, None),
    ]
    assert (records[1].tenant_id, records[1].user_id, records[1].target) == (
        NO_ID,
        NO_ID,
        "unknown",
    )
    assert len(audit(app, "auth.logout")) == 1
    stored = " ".join(f"{r.target} {r.detail} {r.arguments_digest}" for r in records)
    assert "nobody-here" not in stored
    assert TEST_PASSWORD not in stored
    assert "wrong password!!" not in caplog.text


def test_locked_and_disabled_sign_ins_are_audited_as_denied(app: FastAPI) -> None:
    with TestClient(app) as client:
        for _ in range(5):
            login(client, "erin", "wrong password!!")
        login(client, "erin")

    records = audit(app, "auth.login")
    assert records[4].detail == "invalid_password lockout_started"
    assert (records[5].outcome, records[5].detail) == (AuditOutcome.DENIED, "locked")


# --- tickets: the support view ---------------------------------------------------


@pytest.mark.parametrize(
    ("role", "number", "found"),
    [
        (Role.EMPLOYEE, 1, True),
        (Role.EMPLOYEE, 6, False),  # a colleague's ticket
        (Role.MANAGER, 6, True),
        (Role.ADMINISTRATOR, 7, True),
        (Role.MANAGER, 999, False),
    ],
)
def test_managers_read_every_ticket_in_their_tenant(
    app: FastAPI, role: Role, number: int, found: bool
) -> None:
    with app.state.session_factory() as session:
        seed_tickets(session, DEV_TENANT_ID, DEV_USER_ID)
    identity = Identity(DEV_TENANT_ID, DEV_USER_ID, ROLE_PERMISSIONS[role], role)

    result = app.state.tool_executor.execute(identity, "get_ticket", {"number": number})

    assert (result.outcome is AuditOutcome.SUCCEEDED) is found


def test_managers_never_read_other_tenants_tickets(app: FastAPI) -> None:
    with app.state.session_factory() as session:
        seed_tickets(session, DEV_TENANT_ID, DEV_USER_ID)
    stranger = Identity(OTHER_TENANT, OTHER_ADMIN_ID, ROLE_PERMISSIONS[Role.ADMINISTRATOR])

    result = app.state.tool_executor.execute(stranger, "get_ticket", {"number": 1})

    assert result.outcome is AuditOutcome.FAILED

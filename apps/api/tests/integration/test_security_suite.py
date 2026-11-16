"""Phase 6 security suite (P6-M4): two tenants, three roles each, every crossing tried.

Horizontal escalation: a user reaching another user's or tenant's resources.
Vertical escalation: a user doing what only a higher role may do.
Plus mass assignment and session tampering. Nothing here relies on the
browser; every check is on the server.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.identity import Identity
from app.core.roles import ROLE_PERMISSIONS, Role
from app.db.documents import Document
from app.db.tickets import TicketPriority, TicketStatus
from app.main import create_app
from app.repositories.conversations import ConversationRepository
from app.repositories.pending_actions import PendingActionRepository
from app.repositories.tickets import TicketRepository
from app.services.documents import DocumentService
from app.tools.seed import seed_tickets
from tests.conftest import add_user, create_schema, make_settings, sign_in

TENANTS = {
    "a": uuid.UUID("00000000-0000-4000-8000-00000000a000"),
    "b": uuid.UUID("00000000-0000-4000-8000-00000000b000"),
}
ROLES = {"emp": Role.EMPLOYEE, "mgr": Role.MANAGER, "adm": Role.ADMINISTRATOR}
USERS = {
    f"{t}_{r}": uuid.UUID(f"00000000-0000-4000-8000-{i:012x}")
    for i, (t, r) in enumerate(((t, r) for t in TENANTS for r in ROLES), start=1)
}
DRAFT = {"title": "Broken chair", "description": "My office chair is broken.", "priority": "normal"}


def tenant_of(name: str) -> uuid.UUID:
    return TENANTS[name.split("_")[0]]


def identity_of(name: str) -> Identity:
    role = ROLES[name.split("_")[1]]
    return Identity(tenant_of(name), USERS[name], ROLE_PERMISSIONS[role], role.value)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[FastAPI, dict[str, dict[str, str]]]]:
    """Users, and per user a conversation and a pending action; documents and tickets per tenant."""
    app = create_app(make_settings(tmp_path, model_provider="fake"))
    create_schema(app.state.engine)
    resources: dict[str, dict[str, str]] = {}
    with app.state.session_factory() as session:
        for name, user_id in USERS.items():
            add_user(
                app,
                user_id=user_id,
                tenant_id=tenant_of(name),
                username=name.replace("_", "-"),
                role=ROLES[name.split("_")[1]],
            )
            conversation = ConversationRepository(session).create(tenant_of(name), user_id)
            action = PendingActionRepository(session).create(
                tenant_of(name), user_id, "create_draft_ticket", DRAFT, ttl=timedelta(minutes=10)
            )
            resources[name] = {"conversation": str(conversation.id), "action": str(action.id)}
        service = DocumentService(
            session, app.state.blob_store, max_upload_bytes=10_000_000, embedder=app.state.embedder
        )
        for tenant in TENANTS:
            admin = identity_of(f"{tenant}_adm")
            for level in Role:
                text = f"Tenant {tenant} {level.value} memo: the codeword is quartz.".encode()
                doc = service.upload(
                    admin, f"{tenant}-{level.value}.txt", text, min_role=level
                ).document
                resources[f"{tenant}_doc_{level.value}"] = {"id": str(doc.id)}
            seed_tickets(session, TENANTS[tenant], USERS[f"{tenant}_emp"])
    yield app, resources
    app.state.engine.dispose()


def clients(app: FastAPI) -> dict[str, dict[str, str]]:
    return {name: sign_in(app, user_id=user_id) for name, user_id in USERS.items()}


# --- horizontal: other users' and tenants' resources ---------------------------


def test_nobody_reaches_another_users_conversations_or_actions(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, resources = world
    headers = clients(app)
    leaks = []
    with TestClient(app) as client:
        for attacker, auth in headers.items():
            for victim in USERS:
                if victim == attacker:
                    continue
                conversation = resources[victim]["conversation"]
                action = resources[victim]["action"]
                attempts = {
                    "get conversation": client.get(
                        f"/api/v1/conversations/{conversation}", headers=auth
                    ),
                    "ask in conversation": client.post(
                        f"/api/v1/conversations/{conversation}/messages",
                        headers=auth,
                        json={"question": "Codeword?"},
                    ),
                    "delete conversation": client.delete(
                        f"/api/v1/conversations/{conversation}", headers=auth
                    ),
                    "get action": client.get(f"/api/v1/agent/actions/{action}", headers=auth),
                    "confirm action": client.post(
                        f"/api/v1/agent/actions/{action}/confirm", headers=auth
                    ),
                    "cancel action": client.post(
                        f"/api/v1/agent/actions/{action}/cancel", headers=auth
                    ),
                }
                leaks += [
                    (attacker, victim, what, r.status_code)
                    for what, r in attempts.items()
                    if r.status_code != 404
                ]
        # The owners still have everything, untouched.
        owner = client.get(
            f"/api/v1/agent/actions/{resources['a_emp']['action']}", headers=headers["a_emp"]
        )

    assert leaks == []
    assert owner.json()["status"] == "pending"


def test_no_tenant_sees_another_tenants_documents(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, resources = world
    headers = clients(app)
    with TestClient(app) as client:
        b_admin = headers["b_adm"]
        listed = {
            d["filename"] for d in client.get("/api/v1/documents", headers=b_admin).json()["items"]
        }
        direct = [
            client.get(
                f"/api/v1/documents/{resources[f'a_doc_{lvl.value}']['id']}", headers=b_admin
            ).status_code
            for lvl in Role
        ]
        hits = client.post(
            "/api/v1/search",
            headers=b_admin,
            json={"query": "tenant a codeword quartz memo", "top_k": 10},
        ).json()["results"]
        patched = client.patch(
            f"/api/v1/documents/{resources['a_doc_employee']['id']}",
            headers=b_admin,
            json={"min_role": "administrator"},
        )

    assert all(name.startswith("b-") for name in listed)
    assert direct == [404, 404, 404]
    assert {h["citation"]["filename"][0] for h in hits} == {"b"}
    assert patched.status_code == 404


def test_tickets_stay_in_their_tenant_and_with_their_reporter(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, _ = world
    tool = app.state.tool_executor

    def found(name: str, number: int) -> bool:
        return tool.execute(identity_of(name), "get_ticket", {"number": number}).output is not None

    # A ticket that exists only in tenant B (number 8 there).
    with app.state.session_factory() as session:
        TicketRepository(session).create(
            TENANTS["b"],
            USERS["b_emp"],
            title="Only in tenant B",
            description="This ticket exists in tenant B only.",
            status=TicketStatus.OPEN,
            priority=TicketPriority.LOW,
        )

    assert found("a_emp", 1)  # own ticket
    assert not found("a_emp", 6)  # a colleague's
    assert found("a_mgr", 6)  # support view in the own tenant
    assert found("b_mgr", 8)
    assert not found("a_adm", 8)  # never another tenant's, whatever the role


def test_administrators_manage_and_audit_only_their_own_tenant(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, _ = world
    headers = clients(app)
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/login", json={"username": "b-emp", "password": "wrong password!!"}
        )
        client.get("/api/v1/audit", headers=headers["b_emp"])  # refused: audited in tenant B
        client.get("/api/v1/audit", headers=headers["a_emp"])  # refused: audited in tenant A
        patched = client.patch(
            f"/api/v1/users/{USERS['a_emp']}", headers=headers["b_adm"], json={"is_active": False}
        )
        reset = client.post(
            f"/api/v1/users/{USERS['a_emp']}/password",
            headers=headers["b_adm"],
            json={"password": "x" * 20},
        )
        listed = {
            u["username"]
            for u in client.get("/api/v1/users", headers=headers["b_adm"]).json()["items"]
        }
        records = client.get(
            "/api/v1/audit", headers=headers["a_adm"], params={"limit": 200}
        ).json()["items"]

    assert (patched.status_code, reset.status_code) == (404, 404)
    assert listed == {"b-emp", "b-mgr", "b-adm"}
    a_users = {str(USERS[n]) for n in USERS if n.startswith("a_")}
    assert [(r["action"], r["detail"]) for r in records] == [("access.denied", "audit:read")]
    assert all(r["user_id"] in a_users for r in records)  # nothing of tenant B


# --- vertical: actions above the role ------------------------------------------

ABOVE = [
    (
        "emp",
        "POST",
        "/api/v1/users",
        {"json": {"username": "evil", "password": "x" * 20, "role": "administrator"}},
    ),
    ("emp", "GET", "/api/v1/audit", {}),
    (
        "emp",
        "POST",
        "/api/v1/documents",
        {"files": {"file": ("e.txt", b"Employee upload text.", "text/plain")}},
    ),
    ("emp", "PATCH", "/api/v1/documents/{doc}", {"json": {"min_role": "employee"}}),
    (
        "mgr",
        "POST",
        "/api/v1/users",
        {"json": {"username": "evil", "password": "x" * 20, "role": "administrator"}},
    ),
    ("mgr", "PATCH", "/api/v1/users/{self}", {"json": {"role": "administrator"}}),
    ("mgr", "GET", "/api/v1/audit", {}),
]


@pytest.mark.parametrize(("role", "method", "path", "kwargs"), ABOVE)
def test_actions_above_the_role_are_refused(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
    role: str,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    app, resources = world
    name = f"a_{role}"
    url = path.format(doc=resources["a_doc_employee"]["id"], self=USERS[name])
    with TestClient(app) as client:
        response = client.request(method, url, headers=sign_in(app, user_id=USERS[name]), **kwargs)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_managers_cannot_raise_documents_above_themselves(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, resources = world
    with TestClient(app, headers=sign_in(app, user_id=USERS["a_mgr"])) as client:
        upload = client.post(
            "/api/v1/documents",
            files={"file": ("m.txt", b"Manager memo text.", "text/plain")},
            data={"min_role": "administrator"},
        )
        patch = client.patch(
            f"/api/v1/documents/{resources['a_doc_employee']['id']}",
            json={"min_role": "administrator"},
        )
        admin_doc = client.get(f"/api/v1/documents/{resources['a_doc_administrator']['id']}")

    assert {upload.json()["error"]["code"], patch.json()["error"]["code"]} == {
        "min_role_not_allowed"
    }
    assert admin_doc.status_code == 404


# --- mass assignment: fields the client must not set ----------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "POST",
            "/api/v1/users",
            {"username": "mallory", "password": "x" * 20, "role": "employee", "tenant_id": "{b}"},
        ),
        (
            "POST",
            "/api/v1/users",
            {"username": "mallory", "password": "x" * 20, "role": "employee", "is_active": True},
        ),
        ("PATCH", "/api/v1/users/{emp}", {"username": "renamed"}),
        ("PATCH", "/api/v1/users/{emp}", {"password_hash": "scrypt$1$1$1$AA==$AA=="}),
        ("PATCH", "/api/v1/users/{emp}", {"tenant_id": "{b}"}),
        ("PATCH", "/api/v1/documents/{doc}", {"min_role": "employee", "tenant_id": "{b}"}),
        (
            "POST",
            "/api/v1/auth/login",
            {"username": "a-emp", "password": "x" * 20, "role": "administrator"},
        ),
    ],
)
def test_unknown_fields_are_rejected(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
    method: str,
    path: str,
    body: dict[str, object],
) -> None:
    app, resources = world
    values = {
        "b": str(TENANTS["b"]),
        "emp": str(USERS["a_emp"]),
        "doc": resources["a_doc_employee"]["id"],
    }
    url = path.format(**values)
    payload = {k: v.format(**values) if isinstance(v, str) else v for k, v in body.items()}
    with TestClient(app, headers=sign_in(app, user_id=USERS["a_adm"])) as client:
        assert client.request(method, url, json=payload).status_code == 422


def test_upload_form_fields_cannot_choose_owner_or_tenant(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, _ = world
    with TestClient(app, headers=sign_in(app, user_id=USERS["a_mgr"])) as client:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("own.txt", b"A note of my own.", "text/plain")},
            data={"owner_id": str(USERS["a_adm"]), "tenant_id": str(TENANTS["b"])},
        ).json()
    with app.state.session_factory() as session:
        document = session.scalars(
            select(Document).where(Document.id == uuid.UUID(created["id"]))
        ).one()

    assert (document.owner_id, document.tenant_id) == (USERS["a_mgr"], TENANTS["a"])


# --- sessions --------------------------------------------------------------------


@pytest.mark.parametrize(
    "tamper",
    [
        lambda t: t[:-1] + ("A" if t[-1] != "A" else "B"),  # one character changed
        lambda t: t + "A",
        lambda t: t.upper(),
        lambda t: f"{t}, Bearer {t}",  # two credentials in one header
        lambda t: "A" * 8000,  # oversized
    ],
)
def test_tampered_tokens_are_refused(
    world: tuple[FastAPI, dict[str, dict[str, str]]], tamper
) -> None:  # type: ignore[no-untyped-def]
    app, _ = world
    token = sign_in(app, user_id=USERS["a_adm"])["Authorization"].removeprefix("Bearer ")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tamper(token)}"}
        )

    assert response.status_code == 401


def test_tokens_are_accepted_only_in_the_authorization_header(
    world: tuple[FastAPI, dict[str, dict[str, str]]],
) -> None:
    app, _ = world
    token = sign_in(app, user_id=USERS["a_emp"])["Authorization"].removeprefix("Bearer ")
    with TestClient(app) as client:
        lowercase = client.get("/api/v1/auth/me", headers={"Authorization": f"bearer {token}"})
        client.cookies.set("token", token)
        cookie = client.get("/api/v1/auth/me")
        other_header = client.get("/api/v1/auth/me", headers={"X-Auth-Token": token})

    assert lowercase.status_code == 200  # the scheme name is case-insensitive (RFC 7235)
    assert (cookie.status_code, other_header.status_code) == (401, 401)

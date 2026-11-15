import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cli
from app.core.identity import Identity
from app.db.audit import AuditLog, AuditOutcome
from app.db.tickets import SupportTicket, TicketPriority, TicketStatus
from app.main import create_app
from app.services.documents import DocumentService
from app.tools.executor import ToolExecutor
from app.tools.seed import OTHER_REPORTER, seed_tickets
from tests.conftest import create_schema, make_settings, sqlite_url
from tests.fixtures import DOCX_BYTES

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path))
    create_schema(app.state.engine)
    settings = app.state.settings
    with app.state.session_factory() as session:
        assert seed_tickets(session, settings.dev_tenant_id, settings.dev_user_id) == 7
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/documents", files={"file": ("handbook.docx", DOCX_BYTES, DOCX_TYPE)}
        )
        assert response.status_code == 201
        yield test_client


def me(app: FastAPI, *permissions: str) -> Identity:
    settings = app.state.settings
    granted = frozenset(permissions) if permissions else frozenset(settings.dev_permissions)
    return Identity(settings.dev_tenant_id, settings.dev_user_id, granted)


def executor(app: FastAPI) -> ToolExecutor:
    tools: ToolExecutor = app.state.tool_executor
    return tools


def ticket_count(app: FastAPI) -> int:
    with app.state.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(SupportTicket)) or 0)


# --- tools through the executor ----------------------------------------------


def test_knowledge_search_returns_tenant_documents(client: TestClient, app: FastAPI) -> None:
    with app.state.session_factory() as session:
        DocumentService(
            session, app.state.blob_store, max_upload_bytes=10_000_000, embedder=app.state.embedder
        ).upload(Identity(uuid.uuid4(), uuid.uuid4()), "falcon.txt", b"Secret falcon merger plan.")

    result = executor(app).execute(me(app), "search_knowledge_base", {"query": "falcon merger"})

    assert result.outcome is AuditOutcome.SUCCEEDED
    assert result.output is not None
    assert result.output["results"]
    assert all(hit["filename"] == "handbook.docx" for hit in result.output["results"])


def test_own_tickets_can_be_read(client: TestClient, app: FastAPI) -> None:
    ticket = executor(app).execute(me(app), "get_ticket", {"number": 1})
    status = executor(app).execute(me(app), "get_ticket_status", {"number": 1})

    assert ticket.outcome is AuditOutcome.SUCCEEDED
    assert ticket.output is not None
    assert ticket.output["title"] == "Laptop will not connect to VPN"
    assert ticket.output["status"] == "open"
    assert status.output is not None
    assert (status.output["number"], status.output["status"]) == (1, "open")


@pytest.mark.parametrize("number", [6, 7, 999])
def test_other_peoples_and_missing_tickets_look_the_same(
    client: TestClient, app: FastAPI, number: int
) -> None:
    # Tickets 6 and 7 belong to another reporter in the same tenant.
    result = executor(app).execute(me(app), "get_ticket", {"number": number})

    assert (result.outcome, result.detail) == (AuditOutcome.FAILED, "ticket_not_found")
    assert result.message == f"Ticket {number} was not found."
    assert result.output is None


def test_another_tenant_cannot_read_tickets(client: TestClient, app: FastAPI) -> None:
    stranger = Identity(uuid.uuid4(), app.state.settings.dev_user_id, frozenset({"tickets:read"}))

    result = executor(app).execute(stranger, "get_ticket", {"number": 1})

    assert result.detail == "ticket_not_found"


def test_draft_tickets_need_confirmation(client: TestClient, app: FastAPI) -> None:
    arguments = {"title": "Printer \u200bjammed", "description": "The second-floor printer jams."}

    pending = executor(app).execute(me(app), "create_draft_ticket", arguments)

    assert pending.outcome is AuditOutcome.CONFIRMATION_REQUIRED
    assert pending.arguments == {**arguments, "priority": "normal"}
    assert ticket_count(app) == 7

    done = executor(app).execute(me(app), "create_draft_ticket", arguments, confirmed=True)

    assert done.outcome is AuditOutcome.SUCCEEDED
    assert done.output == {"number": 8, "status": "draft", "title": "Printer jammed"}
    with app.state.session_factory() as session:
        created = session.scalars(select(SupportTicket).where(SupportTicket.number == 8)).one()
    assert created.reporter_id == app.state.settings.dev_user_id
    assert (created.status, created.priority) == (TicketStatus.DRAFT, TicketPriority.NORMAL)


@pytest.mark.parametrize(
    "arguments",
    [
        {"title": "Hi", "description": "Too short a title here."},
        {"title": "Valid title", "description": "short"},
        {"title": "Valid title", "description": "A valid description.", "reporter_id": "x"},
        {"title": "Valid title", "description": "A valid description.", "priority": "urgent"},
    ],
)
def test_invalid_drafts_are_rejected(
    client: TestClient, app: FastAPI, arguments: dict[str, object]
) -> None:
    result = executor(app).execute(me(app), "create_draft_ticket", arguments, confirmed=True)

    assert result.outcome is AuditOutcome.INVALID_ARGUMENTS
    assert ticket_count(app) == 7


def test_missing_permissions_are_denied(client: TestClient, app: FastAPI) -> None:
    reader = me(app, "tickets:read")

    result = executor(app).execute(
        reader,
        "create_draft_ticket",
        {"title": "Valid title", "description": "Valid text."},
        confirmed=True,
    )

    assert (result.outcome, result.detail) == (AuditOutcome.DENIED, "tickets:create")
    assert ticket_count(app) == 7


# --- development endpoints ---------------------------------------------------


def test_list_tools_shows_permitted_tools(client: TestClient) -> None:
    items = client.get("/api/v1/tools").json()["items"]

    assert [i["name"] for i in items] == [
        "create_draft_ticket",
        "get_ticket",
        "get_ticket_status",
        "search_knowledge_base",
    ]
    assert next(i for i in items if i["name"] == "create_draft_ticket")["consequential"] is True


def test_list_tools_follows_configured_permissions(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, dev_permissions=["tickets:read"]))
    with TestClient(app) as client:
        names = [i["name"] for i in client.get("/api/v1/tools").json()["items"]]
    app.state.engine.dispose()

    assert names == ["get_ticket", "get_ticket_status"]


def test_invoke_reports_outcomes_and_is_audited(client: TestClient, app: FastAPI) -> None:
    ok = client.post("/api/v1/tools/get_ticket/invoke", json={"arguments": {"number": 2}})
    pending = client.post(
        "/api/v1/tools/create_draft_ticket/invoke",
        json={"arguments": {"title": "New laptop", "description": "My laptop is very slow."}},
    )
    unknown = client.post("/api/v1/tools/drop_tables/invoke", json={"arguments": {}})

    assert [r.status_code for r in (ok, pending, unknown)] == [200, 200, 200]
    assert ok.json()["outcome"] == "succeeded"
    assert ok.json()["output"]["title"] == "Request a second monitor"
    assert pending.json()["outcome"] == "confirmation_required"
    assert unknown.json()["outcome"] == "unknown_tool"
    assert ticket_count(app) == 7
    with app.state.session_factory() as session:
        outcomes = list(session.scalars(select(AuditLog.outcome).order_by(AuditLog.created_at)))
    assert outcomes[-3:] == [
        AuditOutcome.SUCCEEDED,
        AuditOutcome.CONFIRMATION_REQUIRED,
        AuditOutcome.UNKNOWN_TOOL,
    ]


def test_malformed_invocations_are_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/tools/get_ticket/invoke", json={"args": {}}).status_code == 422
    assert client.post("/api/v1/tools/get_ticket/invoke", json={"arguments": []}).status_code == 422


def test_tools_are_not_mounted_in_production(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, environment="production"))) as client:
        assert client.get("/api/v1/tools").status_code == 404


# --- seeding -----------------------------------------------------------------


def test_seeding_runs_once_and_separates_reporters(app: FastAPI) -> None:
    settings = app.state.settings
    with app.state.session_factory() as session:
        assert seed_tickets(session, settings.dev_tenant_id, settings.dev_user_id) == 0
        reporters = list(session.scalars(select(SupportTicket.reporter_id)))
    assert reporters.count(settings.dev_user_id) == 5
    assert reporters.count(OTHER_REPORTER) == 2


def test_seed_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = sqlite_url(tmp_path / "var" / "seed.db")
    app = create_app(make_settings(tmp_path, database_url=url))
    create_schema(app.state.engine)
    app.state.engine.dispose()
    monkeypatch.setenv("EASA_DATABASE_URL", url)

    assert cli.main(["seed-tickets"]) == 0
    assert cli.main(["seed-tickets"]) == 0  # idempotent

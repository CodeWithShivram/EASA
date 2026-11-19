"""Document-level permissions (P6-M3): a minimum role per document, everywhere."""

import json
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
from app.db.documents import Document
from app.embeddings.hashing import HashingEmbedder
from app.llm.base import ChatMessage
from app.llm.fake import FakeChatModel, extractive_reply
from app.main import create_app
from app.retrieval.brute_force import BruteForceVectorIndex
from app.retrieval.keyword import SqliteKeywordIndex
from app.services.documents import DocumentService
from tests.conftest import DEV_TENANT_ID, add_user, create_schema, make_settings, sign_in

EMPLOYEE_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
MANAGER_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c2")
ADMIN_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c3")
PUBLIC_TEXT = b"Annual leave policy: every employee receives 25 days of paid leave per year."
MANAGERS_TEXT = b"Manager handbook: performance review calibration happens every March."
SECRET_TEXT = b"Board minutes: the falcon acquisition budget is confidential."


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path, model_provider="fake"))
    create_schema(app.state.engine)
    for user_id, role in (
        (EMPLOYEE_ID, Role.EMPLOYEE),
        (MANAGER_ID, Role.MANAGER),
        (ADMIN_ID, Role.ADMINISTRATOR),
    ):
        add_user(app, user_id=user_id, username=role.value, role=role)
    yield app
    app.state.engine.dispose()


def client_as(app: FastAPI, user_id: uuid.UUID) -> TestClient:
    return TestClient(app, headers=sign_in(app, user_id=user_id))


def upload(client: TestClient, name: str, data: bytes, min_role: str | None = None):  # type: ignore[no-untyped-def]
    form = {"min_role": min_role} if min_role else None
    return client.post("/api/v1/documents", files={"file": (name, data, "text/plain")}, data=form)


@pytest.fixture
def documents(app: FastAPI) -> dict[str, str]:
    """One document per level, uploaded by the administrator (without a client:
    each TestClient context shuts the app's tool pool down when it ends)."""
    admin = Identity(DEV_TENANT_ID, ADMIN_ID, ROLE_PERMISSIONS[Role.ADMINISTRATOR], "administrator")
    ids = {}
    with app.state.session_factory() as session:
        service = DocumentService(
            session, app.state.blob_store, max_upload_bytes=10_000_000, embedder=app.state.embedder
        )
        for level, name, data in (
            (Role.EMPLOYEE, "leave.txt", PUBLIC_TEXT),
            (Role.MANAGER, "handbook.txt", MANAGERS_TEXT),
            (Role.ADMINISTRATOR, "board.txt", SECRET_TEXT),
        ):
            ids[level.value] = str(service.upload(admin, name, data, min_role=level).document.id)
    return ids


VISIBLE = {
    EMPLOYEE_ID: {"employee"},
    MANAGER_ID: {"employee", "manager"},
    ADMIN_ID: {"employee", "manager", "administrator"},
}


# --- document endpoints -------------------------------------------------------


@pytest.mark.parametrize("user_id", list(VISIBLE))
def test_documents_above_the_role_are_invisible(
    app: FastAPI, documents: dict[str, str], user_id: uuid.UUID
) -> None:
    with client_as(app, user_id) as client:
        listed = {d["id"] for d in client.get("/api/v1/documents").json()["items"]}
        got = {
            lvl: client.get(f"/api/v1/documents/{i}").status_code for lvl, i in documents.items()
        }
        chunks = {
            lvl: client.get(f"/api/v1/documents/{i}/chunks").status_code
            for lvl, i in documents.items()
        }

    allowed = VISIBLE[user_id]
    assert listed == {documents[level] for level in allowed}
    assert got == {lvl: 200 if lvl in allowed else 404 for lvl in documents}
    assert chunks == got  # hidden documents look exactly like missing ones


@pytest.mark.parametrize("mode", ["semantic", "keyword", "hybrid"])
@pytest.mark.parametrize("user_id", list(VISIBLE))
def test_search_never_returns_hidden_documents(
    app: FastAPI, documents: dict[str, str], user_id: uuid.UUID, mode: str
) -> None:
    query = "falcon acquisition budget performance review leave"
    with client_as(app, user_id) as client:
        hits = client.post(
            "/api/v1/search", json={"query": query, "top_k": 10, "mode": mode}
        ).json()["results"]

    found = {h["citation"]["document_id"] for h in hits}
    assert found <= {documents[level] for level in VISIBLE[user_id]}
    assert found  # the visible documents still match


def test_answers_and_conversations_cite_only_visible_documents(
    app: FastAPI, documents: dict[str, str]
) -> None:
    question = {"question": "What is the falcon acquisition budget?"}
    with client_as(app, EMPLOYEE_ID) as client:
        answer = client.post("/api/v1/answers", json=question).json()
        conversation = client.post("/api/v1/conversations").json()["id"]
        turn = client.post(f"/api/v1/conversations/{conversation}/messages", json=question).json()

    cited = [s["citation"]["document_id"] for s in answer["sources"]]
    cited += [s["citation"]["document_id"] for s in turn["answer"]["sources"]]
    assert documents["administrator"] not in cited
    assert "falcon" not in json.dumps([answer, turn]).lower()


def test_the_agent_search_tool_respects_the_role(app: FastAPI, documents: dict[str, str]) -> None:
    def search_then_echo(messages: list[ChatMessage]) -> str:
        if "can use tools" not in messages[0].content:
            return extractive_reply(messages)  # the grounded answer (P8-M2) quotes its source
        if len(messages) == 2:
            return json.dumps(
                {"action": "search_knowledge_base", "arguments": {"query": "falcon board minutes"}}
            )
        return json.dumps({"action": "final_answer", "answer": messages[-1].content[:900]})

    app.state.chat_model = FakeChatModel(search_then_echo)
    results = {}
    with TestClient(app) as client:  # one client: the tool pool lives as long as it does
        for user_id in (EMPLOYEE_ID, ADMIN_ID):
            headers = sign_in(app, user_id=user_id)
            body = client.post("/api/v1/agent", json={"message": "Board minutes?"}, headers=headers)
            results[user_id] = body.json()["answer"].lower()

    assert "falcon" not in results[EMPLOYEE_ID]
    assert "falcon" in results[ADMIN_ID]


# --- setting the minimum role -------------------------------------------------


def test_uploaders_cannot_restrict_above_their_own_role(app: FastAPI) -> None:
    with client_as(app, MANAGER_ID) as manager:
        too_high = upload(manager, "a.txt", b"Some manager text here.", "administrator")
        invalid = upload(manager, "b.txt", b"Other manager text here.", "owner")
        own_level = upload(manager, "c.txt", b"Third manager text here.", "manager")

    assert (too_high.status_code, too_high.json()["error"]["code"]) == (403, "min_role_not_allowed")
    assert invalid.status_code == 422
    assert (own_level.status_code, own_level.json()["min_role"]) == (201, "manager")


def test_identical_content_of_a_hidden_document_is_refused_without_details(
    app: FastAPI, documents: dict[str, str]
) -> None:
    with client_as(app, MANAGER_ID) as manager:
        hidden = upload(manager, "copy.txt", SECRET_TEXT)
        visible = upload(manager, "copy2.txt", MANAGERS_TEXT)

    assert hidden.status_code == 409
    assert hidden.json()["error"]["code"] == "document_exists"
    assert documents["administrator"] not in hidden.text
    assert (visible.status_code, visible.json()["id"]) == (200, documents["manager"])


def test_changing_the_minimum_role_is_limited_and_audited(
    app: FastAPI, documents: dict[str, str]
) -> None:
    public = documents["employee"]
    with client_as(app, MANAGER_ID) as manager, client_as(app, EMPLOYEE_ID) as employee:
        uploaded = upload(manager, "own.txt", b"A note any employee may read.").json()
        restricted = manager.patch(f"/api/v1/documents/{public}", json={"min_role": "manager"})
        employee_view = employee.get(f"/api/v1/documents/{public}").status_code
        too_high = manager.patch(f"/api/v1/documents/{public}", json={"min_role": "administrator"})
        hidden = manager.patch(
            f"/api/v1/documents/{documents['administrator']}", json={"min_role": "employee"}
        )
        by_employee = employee.patch(f"/api/v1/documents/{public}", json={"min_role": "employee"})

    assert restricted.json()["min_role"] == "manager"
    assert employee_view == 404
    assert too_high.json()["error"]["code"] == "min_role_not_allowed"
    assert hidden.status_code == 404  # cannot touch what one cannot see
    assert by_employee.status_code == 403
    with app.state.session_factory() as session:
        records = list(session.scalars(select(AuditLog).where(AuditLog.action.like("document.%"))))
    details = [(r.action, r.detail) for r in records]
    assert ("document.update", "min_role=employee->manager") in details
    assert (
        "document.upload",
        "min_role=employee created=true",
    ) in details
    assert uploaded["min_role"] == "employee"
    assert all(r.outcome is AuditOutcome.SUCCEEDED for r in records)


# --- the indexes filter before scoring -----------------------------------------


def test_indexes_filter_by_level_before_ranking(app: FastAPI, documents: dict[str, str]) -> None:
    embedder: HashingEmbedder = app.state.embedder
    query = "falcon acquisition budget confidential board minutes"
    with app.state.session_factory() as session:
        chunk_document = {
            c.id: c.document_id for d in session.scalars(select(Document)) for c in d.chunks
        }
        vector = embedder.embed_query(query)
        semantic = BruteForceVectorIndex(session).search(
            DEV_TENANT_ID, embedder.model_id, vector, 1
        )
        default_keyword = SqliteKeywordIndex(session).search(DEV_TENANT_ID, query, 1)
        admin_keyword = SqliteKeywordIndex(session).search(
            DEV_TENANT_ID, query, 1, levels=("employee", "manager", "administrator")
        )

    # With top_k=1 the best match (the board minutes) is filtered out first, so
    # a visible document takes its place instead of an empty or hidden result.
    secret = uuid.UUID(documents["administrator"])
    assert chunk_document[semantic[0].chunk_id] != secret
    assert default_keyword == [] or chunk_document[default_keyword[0].chunk_id] != secret
    assert chunk_document[admin_keyword[0].chunk_id] == secret


def test_identities_without_a_role_see_only_employee_documents(
    app: FastAPI, documents: dict[str, str]
) -> None:
    internal = Identity(DEV_TENANT_ID, uuid.uuid4(), ROLE_PERMISSIONS[Role.ADMINISTRATOR])

    result = app.state.tool_executor.execute(
        internal, "search_knowledge_base", {"query": "falcon board"}
    )

    assert result.outcome is AuditOutcome.SUCCEEDED
    assert "falcon" not in json.dumps(result.output).lower()

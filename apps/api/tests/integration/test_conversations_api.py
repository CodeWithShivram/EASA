import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.conversations import ConversationMessage
from app.llm.fake import FakeChatModel
from app.main import create_app
from app.repositories.conversations import ConversationRepository
from app.services import conversations as conversation_service
from tests.conftest import DEV_TENANT_ID, DEV_USER_ID, create_schema, make_settings, sign_in
from tests.fixtures import DOCX_BYTES, PDF_BYTES

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BASE = "/api/v1/conversations"


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    # The "fake" provider quotes the first retrieved source with its citation.
    app = create_app(make_settings(tmp_path, model_provider="fake"))
    create_schema(app.state.engine)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=sign_in(app)) as test_client:
        for name, content, media_type in (
            ("handbook.docx", DOCX_BYTES, DOCX_TYPE),
            ("travel.pdf", PDF_BYTES, "application/pdf"),
        ):
            response = test_client.post(
                "/api/v1/documents", files={"file": (name, content, media_type)}
            )
            assert response.status_code == 201
        yield test_client


def new_conversation(client: TestClient) -> str:
    response = client.post(BASE)
    assert response.status_code == 201
    return str(response.json()["id"])


def ask(client: TestClient, conversation_id: str, question: str) -> dict[str, object]:
    response = client.post(f"{BASE}/{conversation_id}/messages", json={"question": question})
    assert response.status_code == 200, response.json()
    body: dict[str, object] = response.json()
    return body


def message_count(app: FastAPI) -> int:
    with app.state.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(ConversationMessage)) or 0)


def test_a_conversation_stores_questions_and_cited_answers(client: TestClient) -> None:
    conversation_id = new_conversation(client)

    body = ask(client, conversation_id, "How many days of annual leave do employees get?")

    assert body["conversation_id"] == conversation_id
    assert body["turn"] == 1
    answer = body["answer"]
    assert isinstance(answer, dict)
    assert answer["status"] == "answered"
    assert answer["sources"][0]["text"]  # the live response includes the source text

    detail = client.get(f"{BASE}/{conversation_id}").json()
    question, reply = detail["messages"]
    assert (question["position"], question["role"]) == (0, "user")
    assert question["content"] == "How many days of annual leave do employees get?"
    assert (reply["position"], reply["role"], reply["status"]) == (1, "assistant", "answered")
    assert reply["content"] == answer["answer"]
    assert reply["model_id"] == "fake-chat-v1"
    (source,) = reply["sources"]
    assert set(source) == {"label", "citation"}  # stored without chunk text
    assert source["citation"] == answer["sources"][0]["citation"]


def test_follow_ups_see_the_previous_turn(client: TestClient, app: FastAPI) -> None:
    conversation_id = new_conversation(client)
    ask(client, conversation_id, "How many days of annual leave do employees get?")
    model = FakeChatModel("Unused days follow the leave rules [S1].")
    app.state.chat_model = model

    body = ask(client, conversation_id, "And can unused ones be carried over?")

    assert body["turn"] == 2
    prompt = model.calls[0][1].content
    history = prompt.split("</history>")[0]
    assert "<history>" in history
    assert "User: How many days of annual leave do employees get?" in history
    assert "Assistant: " in history


def test_list_shows_only_the_users_own_conversations(client: TestClient, app: FastAPI) -> None:
    mine = new_conversation(client)
    ask(client, mine, "annual leave")
    with app.state.session_factory() as session:
        ConversationRepository(session).create(DEV_TENANT_ID, uuid.uuid4())
        ConversationRepository(session).create(uuid.uuid4(), DEV_USER_ID)
        session.commit()

    items = client.get(BASE).json()["items"]

    assert [(item["id"], item["messages"]) for item in items] == [(mine, 2)]


@pytest.mark.parametrize("owner", ["other_user", "other_tenant"])
def test_other_owners_conversations_look_missing(
    client: TestClient, app: FastAPI, owner: str
) -> None:
    tenant = DEV_TENANT_ID if owner == "other_user" else uuid.uuid4()
    user = uuid.uuid4() if owner == "other_user" else DEV_USER_ID
    with app.state.session_factory() as session:
        foreign = ConversationRepository(session).create(tenant, user)
        session.commit()
        foreign_id = str(foreign.id)

    responses = [
        client.get(f"{BASE}/{foreign_id}"),
        client.post(f"{BASE}/{foreign_id}/messages", json={"question": "annual leave"}),
        client.delete(f"{BASE}/{foreign_id}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert {r.json()["error"]["code"] for r in responses} == {"conversation_not_found"}
    assert message_count(app) == 0


def test_delete_removes_the_conversation_and_its_messages(client: TestClient, app: FastAPI) -> None:
    conversation_id = new_conversation(client)
    ask(client, conversation_id, "annual leave")

    assert client.delete(f"{BASE}/{conversation_id}").status_code == 204
    assert client.get(f"{BASE}/{conversation_id}").status_code == 404
    assert message_count(app) == 0


def test_model_failures_store_nothing(client: TestClient, app: FastAPI) -> None:
    conversation_id = new_conversation(client)
    app.state.chat_model = FakeChatModel(available=False)

    response = client.post(f"{BASE}/{conversation_id}/messages", json={"question": "annual leave"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert message_count(app) == 0


def test_conversations_have_a_turn_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversation_service, "MAX_TURNS", 1)
    conversation_id = new_conversation(client)
    ask(client, conversation_id, "annual leave")

    response = client.post(f"{BASE}/{conversation_id}/messages", json={"question": "travel"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_full"


@pytest.mark.parametrize(
    "payload",
    [{"question": ""}, {"question": "x" * 1001}, {"question": "q", "top_k": 11}, {"q": "x"}],
)
def test_invalid_questions_are_rejected(client: TestClient, payload: dict[str, object]) -> None:
    conversation_id = new_conversation(client)

    response = client.post(f"{BASE}/{conversation_id}/messages", json=payload)

    assert response.status_code == 422


def test_invalid_ids_and_limits_are_rejected(client: TestClient) -> None:
    assert client.get(f"{BASE}/not-a-uuid").status_code == 422
    assert client.get(BASE, params={"limit": 0}).status_code == 422
    assert client.get(BASE, params={"limit": 101}).status_code == 422


def test_conversation_content_is_not_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    conversation_id = new_conversation(client)

    ask(client, conversation_id, "very specific confidential question about leave")

    assert any(r.getMessage() == "conversation turn stored" for r in caplog.records)
    assert "very specific confidential question" not in caplog.text

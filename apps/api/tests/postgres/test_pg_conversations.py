"""Conversations on PostgreSQL: native UUIDs, JSON sources and cascading deletes."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings
from tests.fixtures import DOCX_BYTES

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client(tmp_path: Path, pg_url: str, clean_tables: None) -> Iterator[TestClient]:
    app: FastAPI = create_app(make_settings(tmp_path, database_url=pg_url, model_provider="fake"))
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/documents", files={"file": ("handbook.docx", DOCX_BYTES, DOCX_TYPE)}
        )
        assert response.status_code == 201
        yield test_client
    app.state.engine.dispose()


def test_conversation_round_trip_on_postgres(client: TestClient) -> None:
    conversation_id = client.post("/api/v1/conversations").json()["id"]
    for question in ("How many days of annual leave?", "And for part-time staff?"):
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages", json={"question": question}
        )
        assert response.status_code == 200

    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()

    assert [m["position"] for m in detail["messages"]] == [0, 1, 2, 3]
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
    assert detail["messages"][1]["sources"][0]["citation"]["filename"] == "handbook.docx"
    assert client.get("/api/v1/conversations").json()["items"][0]["messages"] == 4

    assert client.delete(f"/api/v1/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404

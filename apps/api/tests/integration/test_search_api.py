import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.identity import Identity
from app.db.models import Base
from app.main import create_app
from app.services.documents import DocumentService
from tests.conftest import make_settings
from tests.fixtures import DOCX_BYTES, PDF_BYTES, make_encrypted_pdf

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OTHER_TENANT = Identity(
    tenant_id=uuid.UUID("00000000-0000-4000-8000-0000000000bb"), user_id=uuid.uuid4()
)


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path))
    Base.metadata.create_all(app.state.engine)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        test_client.post(
            "/api/v1/documents", files={"file": ("handbook.docx", DOCX_BYTES, DOCX_TYPE)}
        )
        test_client.post(
            "/api/v1/documents", files={"file": ("travel.pdf", PDF_BYTES, "application/pdf")}
        )
        yield test_client


def search(client: TestClient, query: str, **extra: object) -> httpx2.Response:
    return client.post("/api/v1/search", json={"query": query, **extra})


def test_search_returns_ranked_results_with_citations(client: TestClient) -> None:
    response = search(client, "annual leave days", top_k=3)

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "hashing-v1-384"
    assert len(body["results"]) == 3
    top = body["results"][0]
    assert "annual leave" in top["text"]
    assert top["citation"]["filename"] == "handbook.docx"
    assert top["citation"]["section"] == "Leave"
    assert top["citation"]["page_number"] is None
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)


def test_pdf_results_cite_pages(client: TestClient) -> None:
    top = search(client, "submit receipts after travel").json()["results"][0]

    assert top["citation"]["filename"] == "travel.pdf"
    assert top["citation"]["page_number"] == 2
    citation = top["citation"]
    assert citation["char_end"] - citation["char_start"] == len(top["text"])


def test_top_k_limits_results(client: TestClient) -> None:
    assert len(search(client, "policy", top_k=1).json()["results"]) == 1


def test_other_tenants_documents_never_appear(client: TestClient, app: FastAPI) -> None:
    with app.state.session_factory() as session:
        DocumentService(
            session,
            app.state.blob_store,
            max_upload_bytes=10_000_000,
            embedder=app.state.embedder,
        ).upload(OTHER_TENANT, "merger.txt", b"Confidential merger plan for project falcon.")

    results = search(client, "confidential merger plan project falcon", top_k=50).json()

    assert all(r["citation"]["filename"] != "merger.txt" for r in results["results"])
    assert all("falcon" not in r["text"] for r in results["results"])


def test_failed_documents_are_not_searchable(client: TestClient) -> None:
    client.post(
        "/api/v1/documents",
        files={"file": ("locked.pdf", make_encrypted_pdf(), "application/pdf")},
    )

    results = search(client, "travel policy", top_k=50).json()["results"]

    assert all(r["citation"]["filename"] != "locked.pdf" for r in results)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"query": ""}, "validation_error"),
        ({"query": "x" * 1001}, "validation_error"),
        ({"query": "leave", "top_k": 0}, "validation_error"),
        ({"query": "leave", "top_k": 51}, "validation_error"),
        ({"query": "leave", "tenant_id": "someone-else"}, "validation_error"),
        ({"query": " \u200b\n "}, "empty_query"),
    ],
)
def test_invalid_requests_are_rejected(
    client: TestClient, payload: dict[str, object], code: str
) -> None:
    response = client.post("/api/v1/search", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_query_text_is_not_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    search(client, "very specific confidential phrase")

    assert any(r.getMessage() == "search completed" for r in caplog.records)
    assert "very specific confidential phrase" not in caplog.text


def test_search_without_the_embedding_model_is_unavailable(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, embedding_provider="onnx", embedding_model_dir=tmp_path / "no-models"
    )

    with TestClient(create_app(settings)) as client:
        response = search(client, "annual leave")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "embeddings_unavailable"


def test_search_is_not_mounted_in_production(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, environment="production"))) as client:
        assert search(client, "annual leave").status_code == 404

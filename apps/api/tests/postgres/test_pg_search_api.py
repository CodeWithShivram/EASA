"""The full application on PostgreSQL: upload, processing, embedding and search."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.identity import Identity
from app.main import create_app
from app.services.documents import DocumentService
from tests.conftest import make_settings
from tests.fixtures import DOCX_BYTES, PDF_BYTES

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OTHER_TENANT = Identity(
    tenant_id=uuid.UUID("00000000-0000-4000-8000-0000000000bb"), user_id=uuid.uuid4()
)


@pytest.fixture
def app(tmp_path: Path, pg_url: str, clean_tables: None) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path, database_url=pg_url))
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        for name, content, media_type in (
            ("handbook.docx", DOCX_BYTES, DOCX_TYPE),
            ("travel.pdf", PDF_BYTES, "application/pdf"),
        ):
            response = test_client.post(
                "/api/v1/documents", files={"file": (name, content, media_type)}
            )
            assert response.status_code == 201
            assert response.json()["status"] == "processed"
        yield test_client


def search(client: TestClient, query: str, **extra: object) -> httpx2.Response:
    return client.post("/api/v1/search", json={"query": query, **extra})


def test_readiness_on_postgres(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "embeddings": "ok"}


def test_uploads_store_pgvector_embeddings(client: TestClient, app: FastAPI) -> None:
    with app.state.engine.connect() as connection:
        chunks = connection.execute(text("SELECT count(*) FROM document_chunks")).scalar_one()
        vectors = connection.execute(
            text("SELECT count(*), min(vector_dims(vector)) FROM chunk_embeddings")
        ).one()

    assert chunks > 0
    assert tuple(vectors) == (chunks, 384)


def test_semantic_mode(client: TestClient) -> None:
    body = search(client, "annual leave days", top_k=3).json()

    assert body["mode"] == "semantic"
    assert body["model_id"] == "hashing-v1-384"
    top = body["results"][0]
    assert top["citation"]["filename"] == "handbook.docx"
    assert top["citation"]["section"] == "Leave"
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)


def test_keyword_mode(client: TestClient) -> None:
    body = search(client, "receipts", mode="keyword", top_k=3).json()

    assert body["mode"] == "keyword"
    assert body["model_id"] is None
    top = body["results"][0]
    assert top["citation"]["filename"] == "travel.pdf"
    assert top["citation"]["page_number"] == 2


def test_hybrid_mode(client: TestClient) -> None:
    body = search(client, "annual leave days", mode="hybrid", top_k=3).json()

    assert body["mode"] == "hybrid"
    assert body["results"][0]["citation"]["section"] == "Leave"
    assert all(0 < r["score"] <= 2 / 61 + 1e-6 for r in body["results"])


@pytest.mark.parametrize("mode", ["semantic", "keyword", "hybrid"])
def test_other_tenants_never_appear(client: TestClient, app: FastAPI, mode: str) -> None:
    with app.state.session_factory() as session:
        DocumentService(
            session,
            app.state.blob_store,
            max_upload_bytes=10_000_000,
            embedder=app.state.embedder,
        ).upload(OTHER_TENANT, "merger.txt", b"Confidential merger plan for project falcon.")

    results = search(client, "falcon merger plan", mode=mode, top_k=50).json()["results"]

    assert all("falcon" not in r["text"] for r in results)

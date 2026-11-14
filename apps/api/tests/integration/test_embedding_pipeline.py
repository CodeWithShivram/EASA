import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cli
from app.core.config import Settings
from app.db.embeddings import ChunkEmbedding
from app.db.models import Base
from app.embeddings.base import EmbeddingUnavailableError
from app.main import create_app
from app.repositories.embeddings import EmbeddingRepository
from app.services.embedding_service import EmbeddingService
from tests.conftest import make_settings, sqlite_url
from tests.fixtures import DOCX_BYTES, PDF_BYTES, make_encrypted_pdf

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
HASHING_MODEL = "hashing-v1-384"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    yield app
    # Queries after the client closes reopen pooled connections; close them.
    app.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def embedding_count(app: FastAPI) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(ChunkEmbedding)) or 0


def upload(client: TestClient, name: str, data: bytes, content_type: str) -> dict:
    return client.post("/api/v1/documents", files={"file": (name, data, content_type)}).json()


def test_processed_upload_stores_one_vector_per_chunk(
    client: TestClient, app: FastAPI, settings: Settings
) -> None:
    document = upload(client, "handbook.docx", DOCX_BYTES, DOCX_TYPE)
    chunks = client.get(f"/api/v1/documents/{document['id']}/chunks").json()

    with app.state.session_factory() as session:
        vectors = EmbeddingRepository(session).vectors_for_document(
            settings.dev_tenant_id, uuid.UUID(document["id"]), HASHING_MODEL
        )

    assert document["status"] == "processed"
    assert len(vectors) == chunks["total"] == 3
    for _, vector in vectors:
        assert vector.shape == (384,)
        assert np.isclose(np.linalg.norm(vector), 1.0)


def test_failed_documents_are_not_embedded(client: TestClient, app: FastAPI) -> None:
    document = upload(client, "locked.pdf", make_encrypted_pdf(), "application/pdf")

    assert document["status"] == "failed"
    assert embedding_count(app) == 0


def test_embedding_failure_keeps_the_document_and_backfill_recovers(
    client: TestClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    embedder = app.state.embedder
    real_embed = embedder.embed

    def unavailable(texts: list[str]) -> np.ndarray:
        raise EmbeddingUnavailableError("model files missing")

    monkeypatch.setattr(embedder, "embed", unavailable)
    document = upload(client, "travel.pdf", PDF_BYTES, "application/pdf")

    assert document["status"] == "processed"
    assert embedding_count(app) == 0
    assert any(r.getMessage() == "document embedding skipped" for r in caplog.records)

    monkeypatch.setattr(embedder, "embed", real_embed)
    with app.state.session_factory() as session:
        stored = EmbeddingService(session, embedder).embed_missing(limit=100)
    assert stored == 2
    assert embedding_count(app) == 2

    # Running it again finds nothing left to do.
    with app.state.session_factory() as session:
        assert EmbeddingService(session, embedder).embed_missing(limit=100) == 0


def test_vectors_are_deleted_with_their_chunks(client: TestClient, app: FastAPI) -> None:
    document = upload(client, "travel.pdf", PDF_BYTES, "application/pdf")
    assert embedding_count(app) == 2

    with app.state.session_factory() as session:
        from app.repositories.documents import DocumentRepository

        repository = DocumentRepository(session)
        stored = repository.list_for_tenant(app.state.settings.dev_tenant_id)[0]
        assert str(stored.id) == document["id"]
        repository.replace_chunks(stored, [])
        session.commit()

    assert embedding_count(app) == 0


def test_readiness_reports_a_missing_embedding_model(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, embedding_provider="onnx", embedding_model_dir=tmp_path / "no-models"
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "embeddings": "unavailable"},
    }


def test_cli_embed_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    monkeypatch.setattr(app.state.embedder, "embed", _raise_unavailable)
    with TestClient(app) as client:
        upload(client, "travel.pdf", PDF_BYTES, "application/pdf")
    assert embedding_count(app) == 0

    monkeypatch.setenv("EASA_DATABASE_URL", sqlite_url(tmp_path / "var" / "test.db"))
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")

    try:
        assert cli.main(["embed-missing"]) == 0
        assert embedding_count(app) == 2
    finally:
        app.state.engine.dispose()


def test_cli_embed_missing_without_model_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EASA_DATABASE_URL", sqlite_url(tmp_path / "cli.db"))
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "onnx")
    monkeypatch.setenv("EASA_EMBEDDING_MODEL_DIR", str(tmp_path / "no-models"))

    assert cli.main(["embed-missing"]) == 1


def _raise_unavailable(texts: list[str]) -> np.ndarray:
    raise EmbeddingUnavailableError("model files missing")

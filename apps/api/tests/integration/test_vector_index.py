import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentChunk, DocumentMediaType, DocumentStatus
from app.db.engine import create_db_engine
from app.db.models import Base
from app.db.session import create_session_factory
from app.embeddings.hashing import HashingEmbedder
from app.repositories.documents import DocumentRepository
from app.repositories.embeddings import EmbeddingRepository
from app.retrieval.brute_force import BruteForceVectorIndex
from tests.conftest import sqlite_url

# Synthetic identifiers for tests only.
TENANT_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
TENANT_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
EMBEDDER = HashingEmbedder(64)
MODEL = EMBEDDER.model_id


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(sqlite_url(tmp_path / "var" / "index.db"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


def add_document(
    session: Session,
    tenant_id: uuid.UUID,
    texts: list[str],
    *,
    status: DocumentStatus = DocumentStatus.PROCESSED,
    model_id: str = MODEL,
) -> list[DocumentChunk]:
    repository = DocumentRepository(session)
    document = repository.add(
        Document(
            tenant_id=tenant_id,
            owner_id=uuid.uuid4(),
            filename="doc.txt",
            media_type=DocumentMediaType.TXT,
            size_bytes=1,
            sha256=hashlib.sha256(repr((tenant_id, texts)).encode()).hexdigest(),
            status=status,
        )
    )
    chunks = [
        DocumentChunk(chunk_index=i, text=t, char_start=0, char_end=len(t))
        for i, t in enumerate(texts)
    ]
    repository.replace_chunks(document, chunks)
    EmbeddingRepository(session).add(chunks, model_id, EMBEDDER.embed(texts))
    session.commit()
    return chunks


def search(session: Session, query: str, top_k: int = 5, **kwargs: int) -> list[str]:
    index = BruteForceVectorIndex(session, **kwargs)
    hits = index.search(TENANT_A, MODEL, EMBEDDER.embed_query(query), top_k)
    texts = {c.id: c.text for c in session.query(DocumentChunk)}
    return [texts[h.chunk_id] for h in hits]


def test_results_are_ordered_by_similarity_and_limited(session: Session) -> None:
    add_document(
        session,
        TENANT_A,
        ["annual leave days policy", "travel receipts policy", "parking rules", "annual leave"],
    )

    results = search(session, "annual leave", top_k=2)

    assert results == ["annual leave", "annual leave days policy"]


def test_batching_gives_identical_results(session: Session) -> None:
    texts = [f"document {i} about topic {i % 7}" for i in range(23)]
    add_document(session, TENANT_A, texts)

    assert search(session, "topic 3", top_k=6, batch_size=4) == search(
        session, "topic 3", top_k=6, batch_size=1000
    )


def test_ties_are_broken_deterministically(session: Session) -> None:
    add_document(session, TENANT_A, ["same words", "same words", "same words"])

    first = BruteForceVectorIndex(session).search(
        TENANT_A, MODEL, EMBEDDER.embed_query("same words"), 3
    )
    second = BruteForceVectorIndex(session, batch_size=1).search(
        TENANT_A, MODEL, EMBEDDER.embed_query("same words"), 3
    )

    assert [h.chunk_id for h in first] == [h.chunk_id for h in second]
    assert [str(h.chunk_id) for h in first] == sorted(str(h.chunk_id) for h in first)


def test_other_tenants_are_never_scored(session: Session) -> None:
    add_document(session, TENANT_A, ["unrelated cafeteria menu"])
    add_document(session, TENANT_B, ["secret merger plan"])

    assert search(session, "secret merger plan") == ["unrelated cafeteria menu"]


@pytest.mark.parametrize(
    "status", [DocumentStatus.FAILED, DocumentStatus.PROCESSING, DocumentStatus.UPLOADED]
)
def test_only_processed_documents_are_searched(session: Session, status: DocumentStatus) -> None:
    add_document(session, TENANT_A, ["annual leave policy"], status=status)

    assert search(session, "annual leave") == []


def test_vectors_of_other_models_are_ignored(session: Session) -> None:
    add_document(session, TENANT_A, ["annual leave policy"], model_id="other-model@v2")

    assert search(session, "annual leave") == []


def test_empty_index_returns_nothing(session: Session) -> None:
    assert search(session, "anything") == []


def test_top_k_must_be_positive(session: Session) -> None:
    with pytest.raises(ValueError, match="top_k"):
        BruteForceVectorIndex(session).search(TENANT_A, MODEL, np.zeros(64, np.float32), 0)

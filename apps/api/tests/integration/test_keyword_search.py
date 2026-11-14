import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import cli
from app.core.errors import AppError
from app.db.documents import Document, DocumentChunk, DocumentMediaType, DocumentStatus
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.repositories.documents import DocumentRepository
from app.retrieval.brute_force import BruteForceVectorIndex
from app.retrieval.factory import build_indexes
from app.retrieval.keyword import PostgresKeywordIndex, SqliteKeywordIndex
from tests.conftest import create_schema, sqlite_url

# Synthetic identifiers for tests only.
TENANT_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
TENANT_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(sqlite_url(tmp_path / "var" / "keyword.db"))
    create_schema(engine)
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
) -> Document:
    repository = DocumentRepository(session)
    document = repository.add(
        Document(
            tenant_id=tenant_id,
            owner_id=uuid.uuid4(),
            filename="doc.txt",
            media_type=DocumentMediaType.TXT,
            size_bytes=1,
            sha256=hashlib.sha256(repr((tenant_id, texts, status)).encode()).hexdigest(),
            status=status,
        )
    )
    repository.replace_chunks(
        document,
        [
            DocumentChunk(chunk_index=i, text=t, char_start=0, char_end=len(t))
            for i, t in enumerate(texts)
        ],
    )
    session.commit()
    return document


def search(session: Session, query: str, tenant: uuid.UUID = TENANT_A, top_k: int = 5) -> list[str]:
    hits = SqliteKeywordIndex(session).search(tenant, query, top_k)
    texts = {c.id: c.text for c in session.query(DocumentChunk)}
    return [texts[h.chunk_id] for h in hits]


def integrity_ok(session: Session) -> bool:
    session.execute(text("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')"))
    return True


def test_exact_terms_rank_highest(session: Session) -> None:
    add_document(
        session,
        TENANT_A,
        ["Expense code EXP-4471 applies to client dinners.", "General travel guidance.", "Leave."],
    )

    assert search(session, "EXP-4471", top_k=1) == [
        "Expense code EXP-4471 applies to client dinners."
    ]


def test_stemming_matches_word_forms(session: Session) -> None:
    add_document(session, TENANT_A, ["Employees receive annual leaves."])

    assert search(session, "leave") == ["Employees receive annual leaves."]


def test_more_matching_terms_rank_higher(session: Session) -> None:
    add_document(session, TENANT_A, ["annual leave policy", "leave", "unrelated text"])

    assert search(session, "annual leave policy")[0] == "annual leave policy"


@pytest.mark.parametrize(
    "hostile",
    ["NEAR(leave policy)", '"unbalanced', "text:leave", "* OR", "AND NOT", "leave)", "^leave"],
)
def test_fts_syntax_in_queries_is_harmless(session: Session, hostile: str) -> None:
    add_document(session, TENANT_A, ["leave policy text"])

    search(session, hostile)  # must not raise


def test_query_without_words_returns_nothing(session: Session) -> None:
    add_document(session, TENANT_A, ["leave policy"])

    assert search(session, "!!! ???") == []


def test_other_tenants_are_never_returned(session: Session) -> None:
    add_document(session, TENANT_A, ["cafeteria menu"])
    add_document(session, TENANT_B, ["secret merger plan falcon"])

    assert search(session, "secret merger plan falcon", top_k=50) == []


@pytest.mark.parametrize(
    "status", [DocumentStatus.FAILED, DocumentStatus.PROCESSING, DocumentStatus.UPLOADED]
)
def test_only_processed_documents_are_searched(session: Session, status: DocumentStatus) -> None:
    add_document(session, TENANT_A, ["annual leave policy"], status=status)

    assert search(session, "leave") == []


def test_index_follows_chunk_replacement(session: Session) -> None:
    document = add_document(session, TENANT_A, ["old wording about parking"])
    DocumentRepository(session).replace_chunks(
        document,
        [DocumentChunk(chunk_index=0, text="new wording about bicycles", char_start=0, char_end=5)],
    )
    session.commit()

    assert search(session, "parking") == []
    assert search(session, "bicycles") == ["new wording about bicycles"]
    assert integrity_ok(session)


def test_index_follows_cascade_deletes(session: Session) -> None:
    add_document(session, TENANT_A, ["temporary notice about elevators"])

    session.execute(text("DELETE FROM documents"))
    session.commit()

    assert search(session, "elevators") == []
    assert integrity_ok(session)


def test_index_follows_text_updates(session: Session) -> None:
    add_document(session, TENANT_A, ["draft wording"])

    session.execute(text("UPDATE document_chunks SET text = 'final wording'"))
    session.commit()

    assert search(session, "draft") == []
    assert search(session, "final") == ["final wording"]


def test_rebuild_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    add_document(session, TENANT_A, ["rebuild me"])
    monkeypatch.setenv("EASA_DATABASE_URL", sqlite_url(tmp_path / "var" / "keyword.db"))

    assert cli.main(["rebuild-keyword-index"]) == 0
    assert search(session, "rebuild") == ["rebuild me"]


def test_top_k_must_be_positive(session: Session) -> None:
    with pytest.raises(ValueError, match="top_k"):
        SqliteKeywordIndex(session).search(TENANT_A, "leave", 0)


def test_factory_selects_sqlite_implementations(session: Session) -> None:
    vector_index, keyword_index = build_indexes(session)

    assert isinstance(vector_index, BruteForceVectorIndex)
    assert isinstance(keyword_index, SqliteKeywordIndex)


def test_postgres_keyword_index_refuses_sqlite(session: Session) -> None:
    with pytest.raises(AppError) as error:
        PostgresKeywordIndex(session).search(TENANT_A, "leave", 5)

    assert error.value.code == "keyword_search_unavailable"

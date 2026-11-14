import uuid

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.documents import DocumentChunk, DocumentStatus
from app.db.fts import POSTGRES_FTS_INDEX
from app.embeddings.hashing import HashingEmbedder
from app.repositories.embeddings import EmbeddingRepository
from app.retrieval.base import ScoredChunk
from app.retrieval.brute_force import BruteForceVectorIndex
from app.retrieval.factory import build_indexes
from app.retrieval.keyword import (
    POSTGRES_KEYWORD_SQL,
    PostgresKeywordIndex,
    SqliteKeywordIndex,
    build_tsquery,
)
from app.retrieval.pgvector_index import PgvectorIndex
from tests.postgres.conftest import add_document

# Synthetic identifiers for tests only.
TENANT_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
TENANT_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
EMBEDDER = HashingEmbedder(64)
MODEL = EMBEDDER.model_id


def texts_by_id(session: Session) -> dict[uuid.UUID, str]:
    return {c.id: c.text for c in session.query(DocumentChunk)}


def vector_search(session: Session, query: str, top_k: int = 5) -> list[str]:
    hits = PgvectorIndex(session).search(TENANT_A, MODEL, EMBEDDER.embed_query(query), top_k)
    texts = texts_by_id(session)
    return [texts[h.chunk_id] for h in hits]


def tie_groups(hits: list[ScoredChunk]) -> list[tuple[float, frozenset[uuid.UUID]]]:
    """Ranking as (score, chunk IDs with that score) groups, best first.

    NumPy (float32) and pgvector compute equal scores with rounding differences
    of about 1e-8, so the order inside a group of tied scores may differ.
    """
    groups: dict[float, set[uuid.UUID]] = {}
    for hit in hits:
        groups.setdefault(round(hit.score, 5), set()).add(hit.chunk_id)
    return [(score, frozenset(ids)) for score, ids in groups.items()]


def keyword_search(session: Session, query: str, top_k: int = 5) -> list[str]:
    hits = PostgresKeywordIndex(session).search(TENANT_A, query, top_k)
    texts = texts_by_id(session)
    return [texts[h.chunk_id] for h in hits]


# --- storage -----------------------------------------------------------------


def test_vectors_are_stored_as_pgvector_and_round_trip(pg_session: Session) -> None:
    texts = ["annual leave policy", "travel receipts"]
    chunks = add_document(pg_session, TENANT_A, texts, embedder=EMBEDDER)

    stored = EmbeddingRepository(pg_session).vectors_for_document(
        TENANT_A, chunks[0].document_id, MODEL
    )

    assert [chunk_id for chunk_id, _ in stored] == [c.id for c in chunks]
    np.testing.assert_array_equal(np.vstack([v for _, v in stored]), EMBEDDER.embed(texts))
    column_type = pg_session.execute(
        text("SELECT DISTINCT pg_typeof(vector)::text FROM chunk_embeddings")
    ).scalar_one()
    assert column_type == "vector"


def test_factory_selects_postgres_implementations(pg_session: Session) -> None:
    vector_index, keyword_index = build_indexes(pg_session)

    assert isinstance(vector_index, PgvectorIndex)
    assert isinstance(keyword_index, PostgresKeywordIndex)


# --- vector search -----------------------------------------------------------


def test_pgvector_matches_brute_force(pg_session: Session) -> None:
    topics = ["leave", "travel", "parking", "payroll", "security", "laptops", "training"]
    for tenant in (TENANT_A, TENANT_B):
        texts = [
            f"{topics[i % 7]} rules section {i} for {topics[(i * 3) % 7]} and item{i}"
            for i in range(30)
        ]
        add_document(pg_session, tenant, texts, embedder=EMBEDDER)

    for query in ("leave rules", "travel and parking", "item7 payroll", "security training"):
        vector = EMBEDDER.embed_query(query)
        # top_k above the tenant's 30 chunks: compare complete rankings, so no
        # cut-off falls inside a group of tied scores.
        exact = BruteForceVectorIndex(pg_session).search(TENANT_A, MODEL, vector, 50)
        in_database = PgvectorIndex(pg_session).search(TENANT_A, MODEL, vector, 50)

        assert len(in_database) == 30
        assert tie_groups(in_database) == tie_groups(exact)
        assert [h.score for h in in_database] == pytest.approx([h.score for h in exact], abs=1e-5)


def test_results_are_ordered_by_similarity_and_limited(pg_session: Session) -> None:
    add_document(
        pg_session,
        TENANT_A,
        ["annual leave days policy", "travel receipts policy", "parking rules", "annual leave"],
        embedder=EMBEDDER,
    )

    assert vector_search(pg_session, "annual leave", top_k=2) == [
        "annual leave",
        "annual leave days policy",
    ]


def test_ties_are_broken_by_chunk_id(pg_session: Session) -> None:
    add_document(pg_session, TENANT_A, ["same words"] * 3, embedder=EMBEDDER)

    hits = PgvectorIndex(pg_session).search(TENANT_A, MODEL, EMBEDDER.embed_query("same words"), 3)

    assert [str(h.chunk_id) for h in hits] == sorted(str(h.chunk_id) for h in hits)


def test_other_tenants_are_never_returned_by_vector_search(pg_session: Session) -> None:
    add_document(pg_session, TENANT_A, ["unrelated cafeteria menu"], embedder=EMBEDDER)
    add_document(pg_session, TENANT_B, ["secret merger plan"], embedder=EMBEDDER)

    assert vector_search(pg_session, "secret merger plan", top_k=50) == ["unrelated cafeteria menu"]


@pytest.mark.parametrize(
    "status", [DocumentStatus.FAILED, DocumentStatus.PROCESSING, DocumentStatus.UPLOADED]
)
def test_only_processed_documents_are_vector_searched(
    pg_session: Session, status: DocumentStatus
) -> None:
    add_document(pg_session, TENANT_A, ["annual leave policy"], embedder=EMBEDDER, status=status)

    assert vector_search(pg_session, "annual leave") == []


def test_vectors_of_other_models_are_ignored(pg_session: Session) -> None:
    add_document(
        pg_session, TENANT_A, ["annual leave policy"], embedder=EMBEDDER, model_id="other@v2"
    )

    assert vector_search(pg_session, "annual leave") == []


def test_vectors_of_other_dimensions_are_ignored(pg_session: Session) -> None:
    # Same model ID but 32 dimensions: pgvector would reject comparing them.
    add_document(
        pg_session, TENANT_A, ["annual leave policy"], embedder=HashingEmbedder(32), model_id=MODEL
    )
    add_document(pg_session, TENANT_A, ["parking rules"], embedder=EMBEDDER)

    assert vector_search(pg_session, "annual leave") == ["parking rules"]


def test_vector_top_k_must_be_positive(pg_session: Session) -> None:
    with pytest.raises(ValueError, match="top_k"):
        PgvectorIndex(pg_session).search(TENANT_A, MODEL, np.zeros(64, np.float32), 0)


# --- keyword search ----------------------------------------------------------


def test_stemming_matches_word_forms(pg_session: Session) -> None:
    add_document(pg_session, TENANT_A, ["Employees receive annual leaves."])

    assert keyword_search(pg_session, "leave") == ["Employees receive annual leaves."]


def test_more_matching_terms_rank_higher(pg_session: Session) -> None:
    add_document(pg_session, TENANT_A, ["leave", "annual leave policy", "unrelated text"])

    assert keyword_search(pg_session, "annual leave policy") == ["annual leave policy", "leave"]


def test_exact_codes_are_found(pg_session: Session) -> None:
    add_document(
        pg_session,
        TENANT_A,
        ["Expense code EXP-4471 applies to client dinners.", "General travel guidance."],
    )

    assert keyword_search(pg_session, "EXP-4471", top_k=1) == [
        "Expense code EXP-4471 applies to client dinners."
    ]


@pytest.mark.parametrize(
    "hostile",
    [
        "leave' | 'x",
        "leave & !policy",
        "(leave",
        "leave:*",
        "leave <-> policy",
        "leave:A",
        "\\'; DROP TABLE documents; --",
        "NEAR(leave policy)",
    ],
)
def test_tsquery_syntax_in_queries_is_harmless(pg_session: Session, hostile: str) -> None:
    add_document(pg_session, TENANT_A, ["leave policy text"])

    keyword_search(pg_session, hostile)  # must not raise

    assert pg_session.execute(text("SELECT count(*) FROM documents")).scalar_one() == 1


@pytest.mark.parametrize("query", ["!!! ???", "the and of"])
def test_queries_without_searchable_words_return_nothing(pg_session: Session, query: str) -> None:
    add_document(pg_session, TENANT_A, ["the leave policy"])

    assert keyword_search(pg_session, query) == []


def test_other_tenants_are_never_returned_by_keyword_search(pg_session: Session) -> None:
    add_document(pg_session, TENANT_A, ["cafeteria menu"])
    add_document(pg_session, TENANT_B, ["secret merger plan falcon"])

    assert keyword_search(pg_session, "secret merger plan falcon", top_k=50) == []


@pytest.mark.parametrize(
    "status", [DocumentStatus.FAILED, DocumentStatus.PROCESSING, DocumentStatus.UPLOADED]
)
def test_only_processed_documents_are_keyword_searched(
    pg_session: Session, status: DocumentStatus
) -> None:
    add_document(pg_session, TENANT_A, ["annual leave policy"], status=status)

    assert keyword_search(pg_session, "leave") == []


def test_keyword_query_uses_the_gin_index(pg_session: Session) -> None:
    # With realistic statistics (many chunks, one rare term) the planner should
    # choose the GIN index for the exact SQL the application runs.
    texts = [f"routine policy paragraph number {i}" for i in range(2_000)]
    texts[1234] = "the zeppelin allowance policy"
    add_document(pg_session, TENANT_A, texts)
    pg_session.execute(text("ANALYZE document_chunks"))
    pg_session.execute(text("ANALYZE documents"))

    plan = pg_session.execute(
        text("EXPLAIN " + POSTGRES_KEYWORD_SQL.text),
        {
            "match": build_tsquery("zeppelin"),
            "tenant": TENANT_A,
            "status": "processed",
            "limit": 5,
        },
    ).scalars()

    assert POSTGRES_FTS_INDEX in "\n".join(plan)


def test_keyword_top_k_must_be_positive(pg_session: Session) -> None:
    with pytest.raises(ValueError, match="top_k"):
        PostgresKeywordIndex(pg_session).search(TENANT_A, "leave", 0)


def test_sqlite_keyword_index_refuses_postgres(pg_session: Session) -> None:
    with pytest.raises(AppError) as error:
        SqliteKeywordIndex(pg_session).search(TENANT_A, "leave", 5)

    assert error.value.code == "keyword_search_unavailable"

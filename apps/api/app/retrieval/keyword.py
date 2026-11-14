"""Keyword search over chunks: SQLite FTS5 (BM25) and PostgreSQL full-text search."""

import re
import uuid
from http import HTTPStatus

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.documents import DocumentStatus
from app.retrieval.base import ScoredChunk

_TOKEN = re.compile(r"\w+")
MAX_QUERY_TERMS = 32

# The to_tsvector expression must match the GIN index created by migration
# "add postgres search" (app/db/fts.py), or PostgreSQL cannot use the index.
POSTGRES_KEYWORD_SQL = text(
    "SELECT dc.id AS chunk_id, "
    "ts_rank_cd(to_tsvector('english', dc.text), q.query) AS rank "
    "FROM document_chunks dc "
    "JOIN documents d ON d.id = dc.document_id "
    "CROSS JOIN to_tsquery('english', :match) AS q(query) "
    "WHERE to_tsvector('english', dc.text) @@ q.query "
    "AND dc.tenant_id = :tenant AND d.tenant_id = :tenant "
    "AND d.status = :status "
    "ORDER BY rank DESC, dc.id "
    "LIMIT :limit"
)


def query_terms(query: str) -> list[str]:
    """Distinct lower-cased word tokens, at most MAX_QUERY_TERMS, in query order.

    Tokens contain only word characters, so they can never carry quotes or
    operators into a full-text query language.
    """
    terms: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        if token not in terms:
            terms.append(token)
        if len(terms) == MAX_QUERY_TERMS:
            break
    return terms


def build_match_query(query: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted word tokens joined by OR.

    User input never reaches FTS5's query syntax directly, so operators such
    as NEAR, AND, column filters or unbalanced quotes cannot be injected.
    """
    return " OR ".join(f'"{term}"' for term in query_terms(query)) or None


def build_tsquery(query: str) -> str | None:
    """Turn free text into a safe PostgreSQL ``to_tsquery`` input: quoted tokens joined by |."""
    return " | ".join(f"'{term}'" for term in query_terms(query)) or None


def _check_top_k(top_k: int) -> None:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")


def _unavailable() -> AppError:
    return AppError(
        "Keyword search is not available on this database.",
        code="keyword_search_unavailable",
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
    )


class SqliteKeywordIndex:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, tenant_id: uuid.UUID, query: str, top_k: int) -> list[ScoredChunk]:
        _check_top_k(top_k)
        if self._session.get_bind().dialect.name != "sqlite":
            raise _unavailable()
        match = build_match_query(query)
        if match is None:
            return []
        # Tenant and status filters are part of the query; bm25() is lower-is-better.
        rows = self._session.execute(
            text(
                "SELECT dc.id AS chunk_id, bm25(chunk_fts) AS rank "
                "FROM chunk_fts "
                "JOIN document_chunks dc ON dc.rowid = chunk_fts.rowid "
                "JOIN documents d ON d.id = dc.document_id "
                "WHERE chunk_fts MATCH :match "
                "AND dc.tenant_id = :tenant AND d.tenant_id = :tenant "
                "AND d.status = :status "
                "ORDER BY rank, dc.id "
                "LIMIT :limit"
            ),
            {
                "match": match,
                "tenant": tenant_id.hex,
                "status": DocumentStatus.PROCESSED.value,
                "limit": top_k,
            },
        )
        return [ScoredChunk(uuid.UUID(row.chunk_id), -float(row.rank)) for row in rows]


class PostgresKeywordIndex:
    """PostgreSQL full-text search (English configuration: stemming, stop words).

    Ranked with ``ts_rank_cd``, which uses only the matched chunk's own text (no
    corpus-wide statistics), so other tenants' text cannot influence scores.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, tenant_id: uuid.UUID, query: str, top_k: int) -> list[ScoredChunk]:
        _check_top_k(top_k)
        if self._session.get_bind().dialect.name != "postgresql":
            raise _unavailable()
        tsquery = build_tsquery(query)
        if tsquery is None:
            return []
        rows = self._session.execute(
            POSTGRES_KEYWORD_SQL,
            {
                "match": tsquery,
                "tenant": tenant_id,
                "status": DocumentStatus.PROCESSED.value,
                "limit": top_k,
            },
        )
        return [ScoredChunk(row.chunk_id, float(row.rank)) for row in rows]

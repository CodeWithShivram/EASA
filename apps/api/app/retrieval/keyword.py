"""Keyword (BM25) search over chunks using SQLite FTS5."""

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


def build_match_query(query: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted word tokens joined by OR.

    User input never reaches FTS5's query syntax directly, so operators such
    as NEAR, AND, column filters or unbalanced quotes cannot be injected.
    """
    terms: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        if token not in terms:
            terms.append(token)
        if len(terms) == MAX_QUERY_TERMS:
            break
    return " OR ".join(f'"{term}"' for term in terms) or None


class SqliteKeywordIndex:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, tenant_id: uuid.UUID, query: str, top_k: int) -> list[ScoredChunk]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if self._session.get_bind().dialect.name != "sqlite":
            raise AppError(
                "Keyword search is not available on this database.",
                code="keyword_search_unavailable",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
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

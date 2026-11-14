"""Semantic search over the current tenant's processed documents."""

import logging
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity import Identity
from app.embeddings.base import Embedder
from app.repositories.documents import DocumentRepository
from app.retrieval.base import VectorIndex
from app.services.normalization import normalize_text

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 1000
MAX_TOP_K = 50


@dataclass(frozen=True)
class SearchHit:
    score: float
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    text: str
    page_number: int | None
    section: str | None
    char_start: int
    char_end: int


@dataclass(frozen=True)
class SearchResult:
    model_id: str
    hits: list[SearchHit]


class SearchService:
    def __init__(self, session: Session, embedder: Embedder, index: VectorIndex) -> None:
        self._embedder = embedder
        self._index = index
        self._documents = DocumentRepository(session)

    def search(self, identity: Identity, query: str, *, top_k: int) -> SearchResult:
        started = time.perf_counter()
        # Queries are normalized like chunk text, so invisible characters and
        # whitespace variants do not change results.
        normalized = normalize_text(query)
        if not normalized:
            raise AppError(
                "The query must contain text.",
                code="empty_query",
                status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            )
        if len(normalized) > MAX_QUERY_CHARS or not 1 <= top_k <= MAX_TOP_K:
            raise AppError(
                "The query or result count is out of range.",
                code="invalid_search_request",
                status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            )
        if not self._embedder.is_available():
            raise AppError(
                "Search is temporarily unavailable.",
                code="embeddings_unavailable",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        vector = self._embedder.embed_query(normalized)
        scored = self._index.search(identity.tenant_id, self._embedder.model_id, vector, top_k)
        details = self._documents.chunks_with_documents(
            identity.tenant_id, [item.chunk_id for item in scored]
        )
        hits = []
        for item in scored:
            found = details.get(item.chunk_id)
            if found is None:  # deleted between the two queries
                continue
            chunk, document = found
            hits.append(
                SearchHit(
                    score=round(item.score, 6),
                    document_id=document.id,
                    filename=document.filename,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                )
            )

        # Metadata only: the query text can be sensitive and is never logged.
        logger.info(
            "search completed",
            extra={
                "model_id": self._embedder.model_id,
                "top_k": top_k,
                "result_count": len(hits),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return SearchResult(model_id=self._embedder.model_id, hits=hits)

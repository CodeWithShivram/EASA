"""Retrieval interfaces (the ports used by the search service)."""

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.embeddings.base import Vectors


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: uuid.UUID
    # Higher is better. Vector indexes: cosine similarity (vectors are
    # L2-normalized). Keyword indexes: a backend-specific relevance score.
    score: float


class VectorIndex(Protocol):
    def search(
        self, tenant_id: uuid.UUID, model_id: str, query: Vectors, top_k: int
    ) -> list[ScoredChunk]:
        """Top-k chunks of the tenant's processed documents for one model.

        Implementations must apply the tenant, document-status and model
        filters before scoring, so other tenants' content is never scored.
        """
        ...


class KeywordIndex(Protocol):
    def search(self, tenant_id: uuid.UUID, query: str, top_k: int) -> list[ScoredChunk]:
        """Top-k chunks of the tenant's processed documents matching the query's words.

        Implementations must apply the tenant and document-status filters in
        the same query and must never pass user text to the database's query
        syntax unescaped.
        """
        ...

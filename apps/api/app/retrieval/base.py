"""Vector index interface (the port used by the search service)."""

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.embeddings.base import Vectors


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: uuid.UUID
    # Cosine similarity (vectors are L2-normalized), higher is better.
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

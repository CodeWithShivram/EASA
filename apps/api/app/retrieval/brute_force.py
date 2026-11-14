"""Exact vector search by brute force over stored vectors (any SQL backend).

Vectors are streamed from the database in batches, so memory stays bounded by
the batch size, and a running top-k is kept. Exact and simple; used on SQLite.
On PostgreSQL, PgvectorIndex computes the same results inside the database.
"""

import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentChunk, DocumentStatus
from app.db.embeddings import ChunkEmbedding
from app.embeddings.base import Vectors
from app.repositories.embeddings import decode_vector
from app.retrieval.base import ScoredChunk

DEFAULT_BATCH_SIZE = 5_000


class BruteForceVectorIndex:
    def __init__(self, session: Session, *, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self._session = session
        self._batch_size = batch_size

    def search(
        self, tenant_id: uuid.UUID, model_id: str, query: Vectors, top_k: int
    ) -> list[ScoredChunk]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        query = np.asarray(query, dtype=np.float32)
        # Authorization and consistency filters are part of the query itself:
        # only this tenant's vectors, for this model, of processed documents.
        statement = (
            select(ChunkEmbedding.chunk_id, ChunkEmbedding.vector, ChunkEmbedding.dimensions)
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                ChunkEmbedding.model_id == model_id,
                ChunkEmbedding.tenant_id == tenant_id,
                Document.tenant_id == tenant_id,
                Document.status == DocumentStatus.PROCESSED,
            )
        )
        result = self._session.execute(statement, execution_options={"yield_per": self._batch_size})
        best: list[ScoredChunk] = []
        for rows in result.partitions():
            ids = [row.chunk_id for row in rows]
            matrix = np.vstack([decode_vector(row.vector, row.dimensions) for row in rows])
            scores = matrix @ query
            candidates = best + [
                ScoredChunk(chunk_id, float(score))
                for chunk_id, score in zip(ids, scores, strict=True)
            ]
            best = _top(candidates, top_k)
        return best


def _top(candidates: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
    # Ties are broken by chunk ID so results are deterministic.
    return sorted(candidates, key=lambda c: (-c.score, str(c.chunk_id)))[:top_k]

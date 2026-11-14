"""Exact vector search inside PostgreSQL with pgvector.

The database computes cosine distances (``<=>``) and returns only the top-k
rows, so vectors never travel to the application. There is no approximate
(HNSW/IVFFlat) index yet: PostgreSQL scans the tenant's vectors for one model,
which is exact and returns the same results as BruteForceVectorIndex.
Approximate indexes are evaluated in P3-M5.
"""

import uuid

import numpy as np
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Float, bindparam, cast, select
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentChunk, DocumentStatus
from app.db.embeddings import ChunkEmbedding
from app.db.types import VECTOR_DTYPE
from app.embeddings.base import Vectors
from app.retrieval.base import ScoredChunk


class PgvectorIndex:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(
        self, tenant_id: uuid.UUID, model_id: str, query: Vectors, top_k: int
    ) -> list[ScoredChunk]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        vector = np.asarray(query, dtype=VECTOR_DTYPE)
        target = cast(bindparam("query_vector", vector, type_=VECTOR()), VECTOR())
        distance = ChunkEmbedding.vector.op("<=>", return_type=Float)(target)
        # Authorization and consistency filters are part of the query itself:
        # only this tenant's vectors, for this model, of processed documents.
        # The dimension filter keeps pgvector from comparing mismatched vectors.
        statement = (
            select(ChunkEmbedding.chunk_id, distance.label("distance"))
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                ChunkEmbedding.model_id == model_id,
                ChunkEmbedding.tenant_id == tenant_id,
                ChunkEmbedding.dimensions == int(vector.shape[0]),
                Document.tenant_id == tenant_id,
                Document.status == DocumentStatus.PROCESSED,
            )
            # Ties are broken by chunk ID, as in BruteForceVectorIndex.
            .order_by(distance, ChunkEmbedding.chunk_id)
            .limit(top_k)
        )
        return [
            ScoredChunk(row.chunk_id, 1.0 - float(row.distance))
            for row in self._session.execute(statement)
        ]

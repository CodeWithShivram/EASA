"""Data access for chunk embeddings."""

import uuid
from collections.abc import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentChunk, DocumentStatus
from app.db.embeddings import ChunkEmbedding
from app.embeddings.base import Vectors

_DTYPE = np.dtype("<f4")


def encode_vector(vector: Vectors) -> bytes:
    return np.asarray(vector, dtype=_DTYPE).tobytes()


def decode_vector(blob: bytes, dimensions: int) -> Vectors:
    vector = np.frombuffer(blob, dtype=_DTYPE)
    if vector.shape != (dimensions,):
        raise ValueError("stored vector does not match its declared dimensions")
    return vector


class EmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, chunks: Sequence[DocumentChunk], model_id: str, vectors: Vectors) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk is required")
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._session.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    model_id=model_id,
                    tenant_id=chunk.tenant_id,
                    dimensions=int(vector.shape[0]),
                    vector=encode_vector(vector),
                )
            )
        self._session.flush()

    def chunks_without_embedding(self, model_id: str, *, limit: int) -> list[DocumentChunk]:
        """Chunks of processed documents (all tenants) lacking a vector for this model.

        Used by the server-side backfill command, not by request handlers.
        """
        embedded = select(ChunkEmbedding.chunk_id).where(ChunkEmbedding.model_id == model_id)
        statement = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.status == DocumentStatus.PROCESSED,
                DocumentChunk.id.not_in(embedded),
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .limit(limit)
        )
        return list(self._session.scalars(statement))

    def vectors_for_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID, model_id: str
    ) -> list[tuple[uuid.UUID, Vectors]]:
        statement = (
            select(ChunkEmbedding)
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .where(
                ChunkEmbedding.model_id == model_id,
                ChunkEmbedding.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
        return [
            (row.chunk_id, decode_vector(row.vector, row.dimensions))
            for row in self._session.scalars(statement)
        ]

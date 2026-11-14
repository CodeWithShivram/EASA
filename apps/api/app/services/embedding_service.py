"""Embedding of stored chunks."""

import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db.documents import DocumentChunk
from app.embeddings.base import Embedder
from app.repositories.embeddings import EmbeddingRepository

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, session: Session, embedder: Embedder, *, batch_size: int = 32) -> None:
        self._session = session
        self._embedder = embedder
        self._repository = EmbeddingRepository(session)
        self._batch_size = batch_size

    def embed_chunks(self, chunks: Sequence[DocumentChunk]) -> int:
        """Embed and store vectors for the given chunks, then commit."""
        stored = 0
        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start : start + self._batch_size]
            vectors = self._embedder.embed([chunk.text for chunk in batch])
            if vectors.shape != (len(batch), self._embedder.dimensions):
                raise ValueError("embedder returned vectors of an unexpected shape")
            self._repository.add(batch, self._embedder.model_id, vectors)
            stored += len(batch)
        self._session.commit()
        return stored

    def embed_missing(self, *, limit: int) -> int:
        """Backfill: embed chunks of processed documents that lack a vector."""
        chunks = self._repository.chunks_without_embedding(self._embedder.model_id, limit=limit)
        stored = self.embed_chunks(chunks) if chunks else 0
        logger.info(
            "embedding backfill finished",
            extra={"model_id": self._embedder.model_id, "embedded_chunks": stored},
        )
        return stored

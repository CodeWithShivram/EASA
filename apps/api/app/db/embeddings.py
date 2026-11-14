"""ORM model for chunk embeddings.

One row per (chunk, model). ``model_id`` includes the model revision, so
vectors from different models never share a search space; changing the model
means embedding again under a new ``model_id``.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import EmbeddingVector, UtcDateTime, utc_now


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        CheckConstraint("dimensions > 0", name="dimensions_positive"),
        # Search loads one model's vectors for one tenant.
        Index("ix_chunk_embeddings_model_id_tenant_id", "model_id", "tenant_id"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    model_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    # Copied from the chunk so retrieval can filter by tenant before scoring.
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    dimensions: Mapped[int]
    # float32 little-endian, L2-normalized; length = dimensions * 4 bytes.
    # A blob on SQLite, a pgvector `vector` on PostgreSQL.
    vector: Mapped[bytes] = mapped_column(EmbeddingVector)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

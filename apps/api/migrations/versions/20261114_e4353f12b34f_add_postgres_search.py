"""add postgres search

Phase 3 (P3-M4). PostgreSQL only; a no-op on SQLite, which keeps float32 blobs
and the FTS5 index. Written by hand:
- enables the pgvector extension;
- turns chunk_embeddings.vector from bytea into a pgvector ``vector`` (no fixed
  dimension, so one table can hold several models). Vectors are derived data:
  existing rows are deleted and recreated with ``python -m app.cli embed-missing``;
- adds a GIN full-text index on document_chunks.text. Its name and expression
  must match app/db/fts.py (POSTGRES_FTS_INDEX, POSTGRES_TSVECTOR).

Revision ID: e4353f12b34f
Revises: 6d544dac46b3
Create Date: 2026-11-14 21:11:06.640947

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4353f12b34f"
down_revision: str | Sequence[str] | None = "6d544dac46b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable pgvector, store vectors as ``vector`` and index chunk text (PostgreSQL only)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("DELETE FROM chunk_embeddings")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN vector")
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN vector vector NOT NULL")
    op.execute(
        "CREATE INDEX ix_document_chunks_text_tsv ON document_chunks "
        "USING gin (to_tsvector('english', text))"
    )


def downgrade() -> None:
    """Restore bytea vectors (deleting derived rows) and drop the full-text index."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_text_tsv")
    op.execute("DELETE FROM chunk_embeddings")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN vector")
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN vector bytea NOT NULL")
    op.execute("DROP EXTENSION IF EXISTS vector")

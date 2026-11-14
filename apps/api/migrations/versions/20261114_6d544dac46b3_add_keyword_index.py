"""add keyword index

Phase 3 (P3-M3). SQLite FTS5 external-content index over document_chunks.text,
kept in sync by triggers, then populated from existing chunks. Written by hand:
Alembic does not model virtual tables or triggers. The statements must match
app/db/fts.py (a test compares the resulting schema objects). PostgreSQL
keyword search is added separately in P3-M4, so this is a no-op there.

Revision ID: 6d544dac46b3
Revises: 29b0c28209aa
Create Date: 2026-11-14 20:29:08.308071

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6d544dac46b3"
down_revision: str | Sequence[str] | None = "29b0c28209aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    "CREATE VIRTUAL TABLE chunk_fts USING fts5("
    "text, content='document_chunks', content_rowid='rowid', "
    "tokenize='porter unicode61 remove_diacritics 2')",
    "CREATE TRIGGER chunk_fts_ai AFTER INSERT ON document_chunks BEGIN "
    "INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text); END",
    "CREATE TRIGGER chunk_fts_ad AFTER DELETE ON document_chunks BEGIN "
    "INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text); END",
    "CREATE TRIGGER chunk_fts_au AFTER UPDATE OF text ON document_chunks BEGIN "
    "INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text); "
    "INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text); END",
)


def upgrade() -> None:
    """Create the FTS5 index and triggers (SQLite only), then index existing chunks."""
    if op.get_bind().dialect.name != "sqlite":
        return
    for statement in STATEMENTS:
        op.execute(statement)
    op.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')")


def downgrade() -> None:
    """Drop the triggers and the FTS5 index."""
    if op.get_bind().dialect.name != "sqlite":
        return
    for trigger in ("chunk_fts_au", "chunk_fts_ad", "chunk_fts_ai"):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS chunk_fts")

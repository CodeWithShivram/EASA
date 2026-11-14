"""SQLite FTS5 keyword index over document chunks.

An external-content FTS5 table: it indexes ``document_chunks.text`` without
storing a second copy and is kept in sync by triggers (which also fire for
foreign-key cascade deletes). It is keyed on the chunk table's implicit
``rowid``; if a VACUUM ever renumbers rowids, run
``python -m app.cli rebuild-keyword-index``.

The same statements are in migration ``add keyword index``; a test checks that
a migrated database and this module produce identical schema objects.
PostgreSQL keyword search is a separate implementation (Phase 3, P3-M4).
"""

from sqlalchemy import Connection, text

FTS_TABLE = "chunk_fts"

KEYWORD_INDEX_DDL = (
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


def create_keyword_index(connection: Connection) -> None:
    """Create the FTS table and triggers, then index existing chunks."""
    for statement in KEYWORD_INDEX_DDL:
        connection.execute(text(statement))
    rebuild_keyword_index(connection)


def rebuild_keyword_index(connection: Connection) -> None:
    connection.execute(text("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')"))


def is_keyword_index_object(name: str | None) -> bool:
    """FTS5 tables and their shadow tables (chunk_fts_data, ...); not ORM-managed."""
    return bool(name) and (name == FTS_TABLE or name.startswith(f"{FTS_TABLE}_"))

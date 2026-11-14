"""Keyword (full-text) index over document chunks, per database backend.

SQLite: an external-content FTS5 table: it indexes ``document_chunks.text`` without
storing a second copy and is kept in sync by triggers (which also fire for
foreign-key cascade deletes). It is keyed on the chunk table's implicit
``rowid``; if a VACUUM ever renumbers rowids, run
``python -m app.cli rebuild-keyword-index``.

The same statements are in migration ``add keyword index``; a test checks that
a migrated database and this module produce identical schema objects.

PostgreSQL: a GIN expression index on ``to_tsvector('english', text)``, created
by migration ``add postgres search``. Queries must use the same expression
(``POSTGRES_TSVECTOR``) for the index to apply.
"""

from sqlalchemy import Connection, text

FTS_TABLE = "chunk_fts"

POSTGRES_FTS_INDEX = "ix_document_chunks_text_tsv"
POSTGRES_TS_CONFIG = "english"

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
    """Hand-made keyword index objects that the ORM does not manage.

    The FTS5 table and its shadow tables (chunk_fts_data, ...) on SQLite, and the
    GIN full-text index on PostgreSQL.
    """
    if not name:
        return False
    return name in (FTS_TABLE, POSTGRES_FTS_INDEX) or name.startswith(f"{FTS_TABLE}_")

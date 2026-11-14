"""Fixtures for PostgreSQL integration tests (Phase 3, P3-M4).

These tests run only when EASA_TEST_POSTGRES_URL is set to a PostgreSQL URL
whose user may create databases, for example the Compose service (see
docs/DEVELOPMENT_GUIDE.md). Otherwise they are skipped. Each test session
creates throwaway databases, migrates them with Alembic and drops them
afterwards; the database named in the URL itself is never written to.
"""

import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import API_ROOT
from app.db.documents import Document, DocumentChunk, DocumentMediaType, DocumentStatus
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.embeddings.base import Embedder
from app.repositories.documents import DocumentRepository
from app.repositories.embeddings import EmbeddingRepository

# Read at import time: the autouse fixture in tests/conftest.py removes EASA_*
# variables before each test.
ADMIN_URL = os.environ.get("EASA_TEST_POSTGRES_URL")


@contextmanager
def throwaway_database() -> Iterator[str]:
    if not ADMIN_URL:
        pytest.skip("EASA_TEST_POSTGRES_URL is not set")
    name = f"easa_test_{uuid.uuid4().hex[:12]}"  # generated, never user input
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def run_alembic(url: str, action: Callable[..., Any], *args: str) -> None:
    """Run an Alembic command; env.py reads the URL from settings, as in production."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("EASA_DATABASE_URL", url)
        action(Config(str(API_ROOT / "alembic.ini")), *args)


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """A migrated database shared by the session; tables are emptied after each test."""
    with throwaway_database() as url:
        run_alembic(url, command.upgrade, "head")
        yield url


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Iterator[Engine]:
    engine = create_db_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_tables(pg_engine: Engine) -> Iterator[None]:
    yield
    with pg_engine.begin() as connection:
        connection.execute(text("TRUNCATE documents CASCADE"))


@pytest.fixture
def pg_session(pg_engine: Engine, clean_tables: None) -> Iterator[Session]:
    with create_session_factory(pg_engine)() as session:
        yield session


def add_document(
    session: Session,
    tenant_id: uuid.UUID,
    texts: list[str],
    *,
    embedder: Embedder | None = None,
    status: DocumentStatus = DocumentStatus.PROCESSED,
    model_id: str | None = None,
) -> list[DocumentChunk]:
    """Store a synthetic document with chunks and, given an embedder, their vectors."""
    repository = DocumentRepository(session)
    document = repository.add(
        Document(
            tenant_id=tenant_id,
            owner_id=uuid.uuid4(),
            filename="doc.txt",
            media_type=DocumentMediaType.TXT,
            size_bytes=1,
            sha256=hashlib.sha256(repr((tenant_id, texts, status, model_id)).encode()).hexdigest(),
            status=status,
        )
    )
    chunks = [
        DocumentChunk(chunk_index=i, text=t, char_start=0, char_end=len(t))
        for i, t in enumerate(texts)
    ]
    repository.replace_chunks(document, chunks)
    if embedder is not None:
        EmbeddingRepository(session).add(
            chunks, model_id or embedder.model_id, embedder.embed(texts)
        )
    session.commit()
    return chunks

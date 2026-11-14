import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentChunk, DocumentMediaType, DocumentStatus
from app.db.engine import create_db_engine
from app.db.models import Base
from app.db.session import create_session_factory
from app.db.types import utc_now
from app.repositories.documents import DocumentRepository
from tests.conftest import sqlite_url

# Synthetic identifiers for tests only.
TENANT_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
TENANT_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
OWNER = uuid.UUID("00000000-0000-4000-8000-0000000000f1")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(sqlite_url(tmp_path / "var" / "repo.db"))
    # Schema equality with the migrations is covered by test_migrations.
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


def make_document(tenant_id: uuid.UUID = TENANT_A, content: bytes = b"policy") -> Document:
    return Document(
        tenant_id=tenant_id,
        owner_id=OWNER,
        filename="leave-policy.txt",
        media_type=DocumentMediaType.TXT,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_add_sets_defaults(session: Session) -> None:
    document = DocumentRepository(session).add(make_document())

    assert isinstance(document.id, uuid.UUID)
    assert document.status is DocumentStatus.UPLOADED
    assert document.created_at.tzinfo is UTC
    assert document.updated_at.tzinfo is UTC


def test_get_is_scoped_to_the_tenant(session: Session) -> None:
    repo = DocumentRepository(session)
    document = repo.add(make_document(TENANT_A))
    session.commit()

    assert repo.get(TENANT_A, document.id) is document
    # Another tenant cannot read it, even with the correct document ID.
    assert repo.get(TENANT_B, document.id) is None
    assert repo.list_chunks(TENANT_B, document.id) == []


def test_get_by_sha256_is_scoped_to_the_tenant(session: Session) -> None:
    repo = DocumentRepository(session)
    document = repo.add(make_document(TENANT_A, b"same content"))

    assert repo.get_by_sha256(TENANT_A, document.sha256) is document
    assert repo.get_by_sha256(TENANT_B, document.sha256) is None


def test_same_content_twice_in_one_tenant_is_rejected(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.add(make_document(TENANT_A, b"duplicate"))

    with pytest.raises(IntegrityError):
        repo.add(make_document(TENANT_A, b"duplicate"))


def test_same_content_in_two_tenants_is_allowed(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.add(make_document(TENANT_A, b"shared"))
    repo.add(make_document(TENANT_B, b"shared"))
    session.commit()

    assert len(repo.list_for_tenant(TENANT_A)) == 1
    assert len(repo.list_for_tenant(TENANT_B)) == 1


def test_list_is_newest_first_and_paginated(session: Session) -> None:
    repo = DocumentRepository(session)
    base = utc_now()
    for i in range(3):
        document = make_document(TENANT_A, f"doc {i}".encode())
        document.created_at = base + timedelta(seconds=i)
        repo.add(document)
    repo.add(make_document(TENANT_B, b"other tenant"))

    names = [d.sha256 for d in repo.list_for_tenant(TENANT_A)]
    expected = [hashlib.sha256(f"doc {i}".encode()).hexdigest() for i in (2, 1, 0)]
    assert names == expected
    assert len(repo.list_for_tenant(TENANT_A, limit=2)) == 2
    assert len(repo.list_for_tenant(TENANT_A, limit=2, offset=2)) == 1


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (201, 0), (10, -1)])
def test_list_rejects_invalid_pagination(session: Session, limit: int, offset: int) -> None:
    with pytest.raises(ValueError, match=r"limit|offset"):
        DocumentRepository(session).list_for_tenant(TENANT_A, limit=limit, offset=offset)


def _chunk(index: int, text_value: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_index=index,
        text=text_value,
        page_number=1,
        section="Leave",
        char_start=index * 10,
        char_end=index * 10 + len(text_value),
    )


def test_replace_chunks_copies_document_and_tenant_ids(session: Session) -> None:
    repo = DocumentRepository(session)
    document = repo.add(make_document())

    repo.replace_chunks(document, [_chunk(0, "first"), _chunk(1, "second")])
    repo.replace_chunks(document, [_chunk(0, "reprocessed")])
    session.commit()

    chunks = repo.list_chunks(TENANT_A, document.id)
    assert [c.text for c in chunks] == ["reprocessed"]
    assert chunks[0].document_id == document.id
    assert chunks[0].tenant_id == TENANT_A
    assert [c.text for c in document.chunks] == ["reprocessed"]


def test_duplicate_chunk_index_is_rejected(session: Session) -> None:
    repo = DocumentRepository(session)
    document = repo.add(make_document())

    with pytest.raises(IntegrityError):
        repo.replace_chunks(document, [_chunk(0, "a"), _chunk(0, "b")])


def test_deleting_a_document_cascades_to_chunks(session: Session) -> None:
    repo = DocumentRepository(session)
    document = repo.add(make_document())
    repo.replace_chunks(document, [_chunk(0, "only")])
    session.commit()

    # Raw SQL delete exercises the database-level ON DELETE CASCADE (foreign keys on).
    session.execute(text("DELETE FROM documents"))
    session.commit()

    assert session.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar_one() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("size_bytes", 0), ("page_count", -1)],
)
def test_check_constraints_reject_invalid_values(session: Session, field: str, value: int) -> None:
    document = make_document()
    setattr(document, field, value)

    with pytest.raises(IntegrityError):
        DocumentRepository(session).add(document)


def test_status_check_constraint_rejects_unknown_values(session: Session) -> None:
    document = DocumentRepository(session).add(make_document())
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE documents SET status = 'deleted' WHERE id = :id"),
            {"id": document.id.hex},
        )

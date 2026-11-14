"""Data access for documents and chunks.

Every method takes ``tenant_id`` and filters by it, so callers cannot read
another tenant's data by passing a foreign document ID. Methods flush but
never commit; services own transactions.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentChunk

MAX_PAGE_SIZE = 200
MAX_CHUNK_PAGE_SIZE = 500


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, document: Document) -> Document:
        self._session.add(document)
        self._session.flush()
        return document

    def get(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        statement = select(Document).where(
            Document.id == document_id, Document.tenant_id == tenant_id
        )
        return self._session.scalars(statement).one_or_none()

    def get_by_sha256(self, tenant_id: uuid.UUID, sha256: str) -> Document | None:
        statement = select(Document).where(
            Document.tenant_id == tenant_id, Document.sha256 == sha256
        )
        return self._session.scalars(statement).one_or_none()

    def list_for_tenant(
        self, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Document]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset must not be negative")
        statement = (
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc(), Document.id)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def list_chunks(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[DocumentChunk]:
        if limit is not None and not 1 <= limit <= MAX_CHUNK_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_CHUNK_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset must not be negative")
        statement = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id, DocumentChunk.tenant_id == tenant_id)
            .order_by(DocumentChunk.chunk_index)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement))

    def count_chunks(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> int:
        statement = select(func.count()).where(
            DocumentChunk.document_id == document_id, DocumentChunk.tenant_id == tenant_id
        )
        return self._session.scalar(statement) or 0

    def replace_chunks(self, document: Document, chunks: Sequence[DocumentChunk]) -> None:
        """Replace all chunks of a document (used when a document is reprocessed)."""
        self._session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.tenant_id == document.tenant_id,
            )
        )
        for chunk in chunks:
            chunk.document_id = document.id
            chunk.tenant_id = document.tenant_id
            self._session.add(chunk)
        self._session.flush()
        self._session.expire(document, ["chunks"])

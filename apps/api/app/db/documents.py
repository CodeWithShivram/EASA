"""ORM models for uploaded documents and their chunks.

``tenant_id`` and ``owner_id`` are UUIDs without foreign keys until users and
tenants exist (Phase 6). Every query must filter by ``tenant_id``; the
repository layer enforces this.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UtcDateTime, utc_now


class DocumentMediaType(StrEnum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    TXT = "text/plain"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


def _allowed_values_check(column: str, enum_cls: type[StrEnum]) -> CheckConstraint:
    # Explicit CHECK (instead of Enum(create_constraint=True)) so the constraint
    # name follows the naming convention in migrations as well as in the model.
    values = ", ".join(f"'{value}'" for value in _enum_values(enum_cls))
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_allowed")


def _enum_column(enum_cls: type[StrEnum], length: int) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        values_callable=_enum_values,
        length=length,
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # One stored copy per tenant and content (idempotent uploads).
        UniqueConstraint("tenant_id", "sha256"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="page_count_non_negative"),
        _allowed_values_check("media_type", DocumentMediaType),
        _allowed_values_check("status", DocumentStatus),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # Sanitized original name, for display only; never used as a storage path.
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[DocumentMediaType] = mapped_column(_enum_column(DocumentMediaType, 100))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[DocumentStatus] = mapped_column(
        _enum_column(DocumentStatus, 20), default=DocumentStatus.UPLOADED
    )
    # Machine-readable failure reason when status is FAILED; never raw exception text.
    error_code: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, onupdate=utc_now)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.chunk_index",
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="index_non_negative"),
        CheckConstraint("char_start >= 0 AND char_end >= char_start", name="offsets_valid"),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="page_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    # Copied from the document so retrieval can filter chunks by tenant directly.
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    chunk_index: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    # 1-based page number; None for formats without pages (DOCX, TXT).
    page_number: Mapped[int | None]
    section: Mapped[str | None] = mapped_column(String(500))
    # Character offsets into the document's normalized text.
    char_start: Mapped[int]
    char_end: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    document: Mapped[Document] = relationship(back_populates="chunks")

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.documents import DocumentMediaType, DocumentStatus


class DocumentResponse(BaseModel):
    """Public view of a document. Tenant and owner IDs are deliberately omitted."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    media_type: DocumentMediaType
    size_bytes: int
    sha256: str
    status: DocumentStatus
    error_code: str | None
    page_count: int | None
    chunking_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    limit: int
    offset: int


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_index: int
    text: str
    page_number: int | None
    section: str | None
    char_start: int
    char_end: int


class ChunkListResponse(BaseModel):
    document_id: uuid.UUID
    items: list[ChunkResponse]
    total: int
    limit: int
    offset: int

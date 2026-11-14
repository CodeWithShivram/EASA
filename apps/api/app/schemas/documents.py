import uuid
from datetime import datetime

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
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    limit: int
    offset: int

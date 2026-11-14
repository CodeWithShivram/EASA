"""Document use cases: upload, list and get."""

import hashlib
import uuid
from dataclasses import dataclass
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity import Identity
from app.db.documents import Document
from app.repositories.documents import DocumentRepository
from app.services.uploads import DocxLimits, validate_upload
from app.storage.blob_store import BlobStore


@dataclass(frozen=True)
class UploadResult:
    document: Document
    created: bool


class DocumentNotFoundError(AppError):
    def __init__(self) -> None:
        # Same answer whether the document is missing or belongs to another
        # tenant, so its existence is not revealed.
        super().__init__(
            "Document not found.", code="document_not_found", status_code=HTTPStatus.NOT_FOUND
        )


class DocumentService:
    def __init__(
        self,
        session: Session,
        blob_store: BlobStore,
        *,
        max_upload_bytes: int,
        docx_limits: DocxLimits | None = None,
    ) -> None:
        self._session = session
        self._repository = DocumentRepository(session)
        self._blob_store = blob_store
        self._max_upload_bytes = max_upload_bytes
        self._docx_limits = docx_limits

    def upload(self, identity: Identity, raw_filename: str | None, data: bytes) -> UploadResult:
        validated = validate_upload(
            raw_filename, data, max_bytes=self._max_upload_bytes, docx_limits=self._docx_limits
        )
        sha256 = hashlib.sha256(data).hexdigest()

        existing = self._repository.get_by_sha256(identity.tenant_id, sha256)
        if existing is not None:
            return UploadResult(document=existing, created=False)

        # Store the bytes first: an orphaned blob (if the insert fails) is harmless
        # and deduplicated, whereas a row without its blob would be broken.
        self._blob_store.put(data)
        document = Document(
            tenant_id=identity.tenant_id,
            owner_id=identity.user_id,
            filename=validated.filename,
            media_type=validated.media_type,
            size_bytes=len(data),
            sha256=sha256,
        )
        try:
            self._repository.add(document)
            self._session.commit()
        except IntegrityError:
            # A concurrent upload of the same content won the race.
            self._session.rollback()
            existing = self._repository.get_by_sha256(identity.tenant_id, sha256)
            if existing is None:
                raise
            return UploadResult(document=existing, created=False)
        return UploadResult(document=document, created=True)

    def list(self, identity: Identity, *, limit: int, offset: int) -> list[Document]:
        return self._repository.list_for_tenant(identity.tenant_id, limit=limit, offset=offset)

    def get(self, identity: Identity, document_id: uuid.UUID) -> Document:
        document = self._repository.get(identity.tenant_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

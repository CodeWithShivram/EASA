"""Document use cases: upload (with in-request processing), list and get."""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity import Identity
from app.db.documents import Document, DocumentStatus
from app.repositories.documents import DocumentRepository
from app.services.extraction import ExtractionError, ExtractionResult, extract_document
from app.services.uploads import DocxLimits, validate_upload
from app.storage.blob_store import BlobStore

logger = logging.getLogger(__name__)


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
        max_pdf_pages: int = 500,
        docx_limits: DocxLimits | None = None,
    ) -> None:
        self._session = session
        self._repository = DocumentRepository(session)
        self._blob_store = blob_store
        self._max_upload_bytes = max_upload_bytes
        self._max_pdf_pages = max_pdf_pages
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

        self._process(document, data)
        return UploadResult(document=document, created=True)

    def _process(self, document: Document, data: bytes) -> ExtractionResult | None:
        """Extract text in the request and record the outcome on the document.

        The document always ends in PROCESSED or FAILED; it is never left in
        PROCESSING, even if a parser fails unexpectedly on hostile input.
        """
        document.status = DocumentStatus.PROCESSING
        self._session.commit()

        result: ExtractionResult | None = None
        try:
            result = extract_document(document.media_type, data, max_pdf_pages=self._max_pdf_pages)
        except ExtractionError as exc:
            document.status = DocumentStatus.FAILED
            document.error_code = exc.code
        except Exception:
            # Unexpected parser failure: log server-side (no document text) and
            # fail the document with a generic code instead of a 500.
            logger.exception("document processing crashed", extra={"document_id": str(document.id)})
            document.status = DocumentStatus.FAILED
            document.error_code = "processing_error"
        else:
            document.status = DocumentStatus.PROCESSED
            document.error_code = None
            document.page_count = result.page_count
        self._session.commit()

        # Metadata only: document text is never logged.
        logger.info(
            "document processed",
            extra={
                "document_id": str(document.id),
                "status": document.status.value,
                "error_code": document.error_code,
                "page_count": document.page_count,
                "block_count": len(result.blocks) if result else 0,
            },
        )
        return result

    def list(self, identity: Identity, *, limit: int, offset: int) -> list[Document]:
        return self._repository.list_for_tenant(identity.tenant_id, limit=limit, offset=offset)

    def get(self, identity: Identity, document_id: uuid.UUID) -> Document:
        document = self._repository.get(identity.tenant_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

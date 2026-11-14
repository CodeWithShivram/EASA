"""Document use cases: upload (with in-request processing and chunking), list, get, chunks."""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity import Identity
from app.db.documents import Document, DocumentChunk, DocumentStatus
from app.db.types import utc_now
from app.embeddings.base import Embedder
from app.repositories.documents import DocumentRepository
from app.services.chunking import ChunkingConfig, chunk_document
from app.services.embedding_service import EmbeddingService
from app.services.extraction import ExtractionError, ExtractionResult, extract_document
from app.services.uploads import DocxLimits, validate_upload
from app.storage.blob_store import BlobStore

logger = logging.getLogger(__name__)

# A document still "uploaded" or "processing" after this long was interrupted
# (process killed, final commit failed); an identical re-upload reprocesses it.
STALE_PROCESSING_AFTER = timedelta(minutes=10)


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
        chunking: ChunkingConfig | None = None,
        embedder: Embedder | None = None,
        embedding_batch_size: int = 32,
        docx_limits: DocxLimits | None = None,
    ) -> None:
        self._session = session
        self._repository = DocumentRepository(session)
        self._blob_store = blob_store
        self._max_upload_bytes = max_upload_bytes
        self._max_pdf_pages = max_pdf_pages
        self._chunking = chunking or ChunkingConfig()
        self._embedder = embedder
        self._embedding_batch_size = embedding_batch_size
        self._docx_limits = docx_limits

    def upload(self, identity: Identity, raw_filename: str | None, data: bytes) -> UploadResult:
        validated = validate_upload(
            raw_filename, data, max_bytes=self._max_upload_bytes, docx_limits=self._docx_limits
        )
        sha256 = hashlib.sha256(data).hexdigest()

        existing = self._repository.get_by_sha256(identity.tenant_id, sha256)
        if existing is not None:
            if self._is_interrupted(existing):
                logger.warning(
                    "reprocessing interrupted document",
                    extra={"document_id": str(existing.id), "status": existing.status.value},
                )
                self._process(existing, data)
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

    @staticmethod
    def _is_interrupted(document: Document) -> bool:
        return (
            document.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING)
            and utc_now() - document.updated_at > STALE_PROCESSING_AFTER
        )

    def _process(self, document: Document, data: bytes) -> ExtractionResult | None:
        """Extract and chunk text in the request; record the outcome on the document.

        The document ends in PROCESSED or FAILED, even if a parser fails
        unexpectedly on hostile input. If the process dies mid-way it stays in
        PROCESSING until an identical re-upload finds it stale and reprocesses it.
        """
        document.status = DocumentStatus.PROCESSING
        self._session.commit()

        result: ExtractionResult | None = None
        chunk_count = 0
        try:
            result = extract_document(document.media_type, data, max_pdf_pages=self._max_pdf_pages)
            chunks = chunk_document(result, self._chunking)
            self._repository.replace_chunks(
                document,
                [
                    DocumentChunk(
                        chunk_index=chunk.index,
                        text=chunk.text,
                        page_number=chunk.page_number,
                        section=chunk.section,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                    )
                    for chunk in chunks
                ],
            )
            chunk_count = len(chunks)
        except ExtractionError as exc:
            document.status = DocumentStatus.FAILED
            document.error_code = exc.code
        except Exception as exc:
            # Unexpected failure in parsing or chunking: discard any partial chunks,
            # log server-side (no document text) and fail the document with a
            # generic code instead of a 500.
            self._session.rollback()
            # Only the exception type at ERROR: messages and tracebacks can quote
            # file content. The full traceback is available at DEBUG.
            logger.error(
                "document processing crashed",
                extra={"document_id": str(document.id), "error_type": type(exc).__name__},
            )
            logger.debug("document processing traceback", exc_info=True)
            result = None
            document.status = DocumentStatus.FAILED
            document.error_code = "processing_error"
        else:
            document.status = DocumentStatus.PROCESSED
            document.error_code = None
            document.page_count = result.page_count
            document.chunking_config = self._chunking.as_record()
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
                "chunk_count": chunk_count,
            },
        )
        if document.status is DocumentStatus.PROCESSED:
            self._embed(document)
        return result

    def _embed(self, document: Document) -> None:
        """Embed a processed document's chunks as a separate unit of work.

        A failure (e.g. model files not downloaded) does not fail the document:
        its text and chunks are stored, and the backfill command embeds them later.
        """
        if self._embedder is None:
            return
        try:
            stored = EmbeddingService(
                self._session, self._embedder, batch_size=self._embedding_batch_size
            ).embed_chunks(document.chunks)
        except Exception as exc:
            self._session.rollback()
            logger.warning(
                "document embedding skipped",
                extra={
                    "document_id": str(document.id),
                    "model_id": self._embedder.model_id,
                    "error_type": type(exc).__name__,
                },
            )
            return
        logger.info(
            "document embedded",
            extra={
                "document_id": str(document.id),
                "model_id": self._embedder.model_id,
                "embedded_chunks": stored,
            },
        )

    def list(self, identity: Identity, *, limit: int, offset: int) -> list[Document]:
        return self._repository.list_for_tenant(identity.tenant_id, limit=limit, offset=offset)

    def get(self, identity: Identity, document_id: uuid.UUID) -> Document:
        document = self._repository.get(identity.tenant_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

    def list_chunks(
        self, identity: Identity, document_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[DocumentChunk], int]:
        """Chunks of one of the tenant's documents, plus the total chunk count."""
        document = self.get(identity, document_id)
        chunks = self._repository.list_chunks(
            identity.tenant_id, document.id, limit=limit, offset=offset
        )
        return chunks, self._repository.count_chunks(identity.tenant_id, document.id)

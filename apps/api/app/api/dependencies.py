from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.identity import Identity
from app.db.probe import SqlAlchemyDatabaseProbe
from app.db.session import iter_session
from app.retrieval.brute_force import BruteForceVectorIndex
from app.retrieval.keyword import SqliteKeywordIndex
from app.services.chunking import ChunkingConfig, ChunkingStrategy
from app.services.documents import DocumentService
from app.services.health import HealthService
from app.services.search import SearchService


def get_db_session(request: Request) -> Iterator[Session]:
    yield from iter_session(request.app.state.session_factory)


def get_health_service(request: Request) -> HealthService:
    return HealthService(
        database=SqlAlchemyDatabaseProbe(request.app.state.engine),
        embeddings=request.app.state.embedder,
    )


def get_identity(request: Request) -> Identity:
    # Development-only identity from server configuration (ADR-014). Nothing in
    # the request influences it. Replaced by real authentication in Phase 6.
    settings = request.app.state.settings
    return Identity(tenant_id=settings.dev_tenant_id, user_id=settings.dev_user_id)


def get_document_service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> DocumentService:
    settings = request.app.state.settings
    return DocumentService(
        session,
        request.app.state.blob_store,
        max_upload_bytes=settings.max_upload_bytes,
        max_pdf_pages=settings.max_pdf_pages,
        chunking=ChunkingConfig(
            strategy=ChunkingStrategy(settings.chunk_strategy),
            max_chars=settings.chunk_max_chars,
            overlap_chars=settings.chunk_overlap_chars,
        ),
        embedder=request.app.state.embedder,
        embedding_batch_size=settings.embedding_batch_size,
    )


def get_search_service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> SearchService:
    return SearchService(
        session,
        request.app.state.embedder,
        BruteForceVectorIndex(session),
        SqliteKeywordIndex(session),
    )

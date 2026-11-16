from collections.abc import Callable, Iterator
from datetime import timedelta
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.correlation import get_correlation_id
from app.core.errors import AppError
from app.core.identity import Identity
from app.db.audit import AuditOutcome
from app.db.probe import SqlAlchemyDatabaseProbe
from app.db.session import iter_session
from app.repositories.audit import AuditRepository
from app.retrieval.factory import build_indexes
from app.services.answers import AnswerService
from app.services.auth import AuthService, SessionPolicy, not_authenticated
from app.services.chunking import ChunkingConfig, ChunkingStrategy
from app.services.conversations import ConversationService
from app.services.documents import DocumentService
from app.services.health import HealthService
from app.services.search import SearchService


def get_db_session(request: Request) -> Iterator[Session]:
    yield from iter_session(request.app.state.session_factory)


def get_health_service(request: Request) -> HealthService:
    return HealthService(
        database=SqlAlchemyDatabaseProbe(request.app.state.engine),
        embeddings=request.app.state.embedder,
        model=request.app.state.chat_model,
    )


# Only the Authorization header is read; tokens in URLs or bodies are ignored.
_bearer = HTTPBearer(auto_error=False, description="Session token from POST /api/v1/auth/login")


def session_policy(settings: Settings) -> SessionPolicy:
    return SessionPolicy(
        idle=timedelta(minutes=settings.session_idle_minutes),
        lifetime=timedelta(hours=settings.session_lifetime_hours),
        password_hash_n=settings.password_hash_n,
    )


def get_auth_service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> AuthService:
    state = request.app.state
    return AuthService(
        session,
        session_policy(state.settings),
        state.role_permissions,
        AuditRepository(state.session_factory),
    )


def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise not_authenticated()
    return credentials.credentials


def get_identity(request: Request, token: Annotated[str, Depends(get_bearer_token)]) -> Identity:
    """The signed-in user (ADR-031); 401 without a valid session token."""
    # Its own short session: the sign-in check may update last_seen_at.
    with request.app.state.session_factory() as session:
        service = AuthService(
            session, session_policy(request.app.state.settings), request.app.state.role_permissions
        )
        return service.authenticate(token)


def require(permission: str) -> Callable[..., Identity]:
    """Dependency: the signed-in user if their role grants the permission; 403 otherwise.

    Refusals are audited (action ``access.denied``, the route and the missing
    permission), so escalation attempts are visible to administrators.
    """

    def dependency(
        request: Request, identity: Annotated[Identity, Depends(get_identity)]
    ) -> Identity:
        if identity.can(permission):
            return identity
        AuditRepository(request.app.state.session_factory).record(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            action="access.denied",
            # The requested path (IDs included; the query string is never recorded).
            target=f"{request.method} {request.url.path}",
            outcome=AuditOutcome.DENIED,
            detail=permission,
            correlation_id=get_correlation_id(),
        )
        raise AppError(
            "You do not have permission for this action.",
            code="forbidden",
            status_code=HTTPStatus.FORBIDDEN,
        )

    return dependency


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
    # pgvector and PostgreSQL full-text search on PostgreSQL; brute force and FTS5 on SQLite.
    vector_index, keyword_index = build_indexes(session)
    return SearchService(session, request.app.state.embedder, vector_index, keyword_index)


def get_answer_service(
    request: Request, search: Annotated[SearchService, Depends(get_search_service)]
) -> AnswerService:
    settings = request.app.state.settings
    return AnswerService(
        search,
        request.app.state.chat_model,
        max_output_tokens=settings.model_max_output_tokens,
        temperature=settings.model_temperature,
        support_check=settings.answer_support_check,
    )


def get_conversation_service(
    session: Annotated[Session, Depends(get_db_session)],
    answers: Annotated[AnswerService, Depends(get_answer_service)],
) -> ConversationService:
    return ConversationService(session, answers)

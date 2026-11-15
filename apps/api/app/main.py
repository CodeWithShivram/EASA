"""Application factory.

Run with: ``uv run uvicorn app.main:create_app --factory``
"""

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.api.v1.routes import agent, answers, conversations, documents, search, tools
from app.core.config import Settings, load_settings
from app.core.correlation import CORRELATION_ID_HEADER
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    CorrelationIdMiddleware,
    UnhandledErrorMiddleware,
)
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.embeddings.factory import build_embedder
from app.llm.factory import build_chat_model
from app.repositories.audit import AuditRepository
from app.storage.blob_store import LocalBlobStore
from app.tools.executor import ToolExecutor
from app.tools.support import build_tool_registry

# Allowance for multipart boundaries and headers on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url.get_secret_value())

    # None when answer generation is disabled (model_provider = "none").
    chat_model = build_chat_model(settings)
    # Tools run in worker threads so each call can time out (app.tools.executor).
    tool_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="easa-tool")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        tool_pool.shutdown(wait=False, cancel_futures=True)
        engine.dispose()
        # HTTP-based models hold a connection pool.
        close = getattr(chat_model, "close", None)
        if close is not None:
            close()

    # Interactive API docs are disabled in production.
    app = FastAPI(
        title="EASA API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.blob_store = LocalBlobStore(settings.storage_dir)
    # The ONNX model loads lazily on first use, so startup stays fast.
    app.state.embedder = build_embedder(settings)
    app.state.chat_model = chat_model
    app.state.tool_executor = ToolExecutor(
        build_tool_registry(app.state.embedder),
        AuditRepository(app.state.session_factory),
        app.state.session_factory,
        pool=tool_pool,
    )

    register_exception_handlers(app)
    app.include_router(api_router)
    if not settings.is_production:
        # Uses the development-only identity (ADR-014), so never in production.
        app.include_router(documents.router, prefix="/api/v1")
        app.include_router(search.router, prefix="/api/v1")
        app.include_router(answers.router, prefix="/api/v1")
        app.include_router(conversations.router, prefix="/api/v1")
        app.include_router(tools.router, prefix="/api/v1")
        app.include_router(agent.router, prefix="/api/v1")

    # Starlette wraps middleware in reverse order: the last one added is outermost.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
        expose_headers=[CORRELATION_ID_HEADER],
    )
    app.add_middleware(CorrelationIdMiddleware)

    return app

"""Application factory.

Run with: ``uv run uvicorn app.main:create_app --factory``
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, load_settings
from app.core.correlation import CORRELATION_ID_HEADER
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, UnhandledErrorMiddleware
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.storage.blob_store import LocalBlobStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

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

    register_exception_handlers(app)
    app.include_router(api_router)

    # Starlette wraps middleware in reverse order: the last one added is outermost.
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

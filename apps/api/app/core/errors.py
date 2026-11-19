"""Standardized error responses.

Every error returned to a client has the shape::

    {"error": {"code": "...", "message": "...", "correlation_id": "...", "details": [...]}}

Stack traces and internal exception messages are never returned to clients.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import get_correlation_id

logger = logging.getLogger(__name__)
# Seconds a client should wait before retrying while the database is unreachable.
DATABASE_RETRY_AFTER = "5"


class ValidationIssue(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    correlation_id: str | None
    details: list[ValidationIssue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Expected application error with a client-safe message."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[ValidationIssue] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            correlation_id=get_correlation_id(),
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


def _code_for_status(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "http_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return error_response(
            exc.status_code,
            _code_for_status(exc.status_code),
            message,
            headers=exc.headers,
        )

    # The database cannot be reached (stopped, restarting, network) or the connection
    # pool is exhausted: a temporary condition, not a bug (P8-M5 failure tests).
    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeoutError)
    async def handle_database_unavailable(_: Request, exc: Exception) -> JSONResponse:
        # The error type only: driver messages can contain host names and SQL.
        logger.warning("database unavailable", extra={"error_type": type(exc).__name__})
        return error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "database_unavailable",
            "The database is temporarily unavailable. Try again shortly.",
            headers={"Retry-After": DATABASE_RETRY_AFTER},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Submitted input values are deliberately omitted from the response.
        details = [
            ValidationIssue(location=list(err["loc"]), message=err["msg"], type=err["type"])
            for err in exc.errors()
        ]
        return error_response(
            HTTPStatus.UNPROCESSABLE_CONTENT,
            "validation_error",
            "Request validation failed.",
            details=details,
        )

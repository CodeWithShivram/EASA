"""Pure ASGI middleware for correlation IDs, request logging and unhandled errors.

Order (outermost first), as installed by ``create_app``:

1. ``CorrelationIdMiddleware``: assigns the ID, adds the response header and
   logs each request, so every response, including CORS preflights and 500s,
   carries an ID.
2. ``CORSMiddleware``.
3. ``UnhandledErrorMiddleware``: converts unexpected exceptions into the
   standard 500 error body, which then still receives CORS and ID headers.
4. ``BodySizeLimitMiddleware``: rejects request bodies over the limit with 413.
"""

import logging
import time
from http import HTTPStatus

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.correlation import (
    CORRELATION_ID_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.core.errors import error_response

logger = logging.getLogger("app.request")


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = new_correlation_id()
        token = set_correlation_id(correlation_id)
        status_code = 500
        started = time.perf_counter()

        async def send_with_header(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[CORRELATION_ID_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            # The query string is deliberately not logged; it may carry sensitive values.
            logger.info(
                "request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            reset_correlation_id(token)


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("unhandled exception while processing request")
            if response_started:
                raise
            response = error_response(500, "internal_error", "An unexpected error occurred.")
            await response(scope, receive, send)


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_body_bytes`` with 413.

    A declared ``Content-Length`` over the limit is rejected before the body is
    read. Bodies without a usable length (e.g. chunked) are counted as they
    arrive. When the limit is crossed mid-stream, whatever response the app
    would have sent (FastAPI turns body-read errors into a 400) is replaced by
    the 413 error body.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            if not declared.isdigit():
                await error_response(
                    HTTPStatus.BAD_REQUEST, "invalid_content_length", "Invalid Content-Length."
                )(scope, receive, send)
                return
            if int(declared) > self.max_body_bytes:
                await self._too_large()(scope, receive, send)
                return

        received = 0
        exceeded = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if exceeded and not response_started:
                return  # Suppress the app's response to an oversized body.
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not (exceeded and not response_started):
                raise
        if exceeded and not response_started:
            await self._too_large()(scope, receive, send)

    def _too_large(self) -> JSONResponse:
        return error_response(
            HTTPStatus.CONTENT_TOO_LARGE, "request_too_large", "The request body is too large."
        )

"""Structured JSON logging with the current request's correlation ID."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.correlation import get_correlation_id

# Attributes present on every LogRecord; anything else was passed via `extra=`.
# "color_message" is uvicorn's ANSI-colored duplicate of the message.
_EXCLUDED_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
    | {"message", "asctime", "color_message"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _EXCLUDED_RECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Route all application and server logs through a single JSON handler."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_easa_handler", False)]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler._easa_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn installs its own plain-text handlers; send its logs through ours.
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    # Per-request logging is done by CorrelationIdMiddleware.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

import json
import logging

from app.core.correlation import reset_correlation_id, set_correlation_id
from app.core.logging import JsonFormatter


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    record.__dict__.update(extra)
    return record


def test_formats_record_as_json_with_correlation_id() -> None:
    token = set_correlation_id("abc123")
    try:
        output = JsonFormatter().format(_record("hello", path="/api/v1/health"))
    finally:
        reset_correlation_id(token)

    payload = json.loads(output)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["correlation_id"] == "abc123"
    assert payload["path"] == "/api/v1/health"
    assert payload["timestamp"].endswith("+00:00")


def test_correlation_id_is_null_outside_a_request() -> None:
    payload = json.loads(JsonFormatter().format(_record("startup")))

    assert payload["correlation_id"] is None


def test_drops_uvicorn_color_message() -> None:
    payload = json.loads(JsonFormatter().format(_record("started", color_message="[36mstarted")))

    assert "color_message" not in payload

import io
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.main import create_app
from tests.conftest import make_settings

CORRELATION_ID = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def app_with_test_routes(tmp_path: Path) -> FastAPI:
    app = create_app(make_settings(tmp_path))

    # Test-only routes used to exercise error handling.
    @app.get("/test/items/{item_id}")
    def get_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError("internal detail that must not leak")

    return app


@pytest.fixture
def test_client(app_with_test_routes: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_with_test_routes) as client:
        yield client


def test_every_response_has_a_server_generated_correlation_id(test_client: TestClient) -> None:
    first = test_client.get("/api/v1/health")
    second = test_client.get("/api/v1/health")

    first_id = first.headers["X-Correlation-ID"]
    second_id = second.headers["X-Correlation-ID"]
    assert CORRELATION_ID.match(first_id)
    assert CORRELATION_ID.match(second_id)
    assert first_id != second_id


def test_client_supplied_correlation_id_is_ignored(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/health", headers={"X-Correlation-ID": "attacker-chosen"})

    assert response.headers["X-Correlation-ID"] != "attacker-chosen"
    assert CORRELATION_ID.match(response.headers["X-Correlation-ID"])


def test_not_found_uses_standard_error_body(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "correlation_id": response.headers["X-Correlation-ID"],
        }
    }


def test_method_not_allowed_uses_standard_error_body(test_client: TestClient) -> None:
    response = test_client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["Allow"] == "GET"


def test_validation_error_omits_submitted_input(test_client: TestClient) -> None:
    response = test_client.get("/test/items/secret-value")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]
    assert error["details"][0]["location"] == ["path", "item_id"]
    assert "secret-value" not in response.text


def test_unhandled_exception_returns_safe_500(test_client: TestClient) -> None:
    response = test_client.get("/test/crash", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "correlation_id": response.headers["X-Correlation-ID"],
        }
    }
    assert "must not leak" not in response.text
    assert "Traceback" not in response.text
    # Error responses still carry CORS headers so the browser can read them.
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"


def test_cors_rejects_unlisted_origin(test_client: TestClient) -> None:
    response = test_client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers
    assert CORRELATION_ID.match(response.headers["X-Correlation-ID"])


def test_cors_exposes_correlation_header_to_allowed_origin(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "X-Correlation-ID" in response.headers["Access-Control-Expose-Headers"]


def test_request_log_is_json_with_matching_correlation_id(test_client: TestClient) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    request_logger = logging.getLogger("app.request")
    request_logger.addHandler(handler)
    try:
        response = test_client.get("/api/v1/health?token=should-not-be-logged")
    finally:
        request_logger.removeHandler(handler)

    entries = [json.loads(line) for line in stream.getvalue().splitlines()]
    request_entry = next(e for e in entries if e["message"] == "request completed")
    assert request_entry["correlation_id"] == response.headers["X-Correlation-ID"]
    assert request_entry["method"] == "GET"
    assert request_entry["path"] == "/api/v1/health"
    assert request_entry["status_code"] == 200
    assert isinstance(request_entry["duration_ms"], float)
    assert "should-not-be-logged" not in stream.getvalue()

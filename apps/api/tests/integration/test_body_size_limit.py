from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.middleware import BodySizeLimitMiddleware, CorrelationIdMiddleware

LIMIT = 100


@pytest.fixture
def client() -> Iterator[TestClient]:
    # A minimal app: only the middleware under test plus correlation IDs.
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"received": len(await request.body())}

    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=LIMIT)
    app.add_middleware(CorrelationIdMiddleware)
    with TestClient(app) as test_client:
        yield test_client


def test_body_within_the_limit_passes(client: TestClient) -> None:
    response = client.post("/echo", content=b"x" * LIMIT)

    assert response.status_code == 200
    assert response.json() == {"received": LIMIT}


def test_declared_length_over_the_limit_is_rejected_before_reading(client: TestClient) -> None:
    response = client.post("/echo", content=b"x" * (LIMIT + 1))

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "request_too_large"
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]


def test_streamed_body_over_the_limit_is_rejected(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        # No Content-Length: the body is sent chunked and counted as it arrives.
        for _ in range(5):
            yield b"x" * 40

    response = client.post("/echo", content=chunks())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_invalid_content_length_is_rejected(client: TestClient) -> None:
    response = client.post("/echo", content=b"abc", headers={"Content-Length": "-5"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_content_length"

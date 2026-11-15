import socket
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def unused_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_readiness_with_the_fake_model(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, model_provider="fake"))) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["model"] == "ok"


def test_unreachable_ollama_makes_the_api_not_ready(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        model_provider="ollama",
        model_name="tiny:1b",
        ollama_base_url=f"http://127.0.0.1:{unused_local_port()}",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": "ok",
        "embeddings": "ok",
        "model": "unavailable",
    }

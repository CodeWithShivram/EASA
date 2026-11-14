import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's EASA_* variables and .env file out of tests."""
    for key in list(os.environ):
        if key.startswith("EASA_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": sqlite_url(tmp_path / "var" / "test.db"),
        "storage_dir": tmp_path / "var" / "uploads",
        # Deterministic, offline embedder; the real model has its own tests.
        "embedding_provider": "hashing",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def broken_db_client(tmp_path: Path) -> Iterator[TestClient]:
    # A directory is not a valid SQLite database file, so connecting fails.
    unusable = tmp_path / "not-a-database"
    unusable.mkdir()
    settings = make_settings(tmp_path, database_url=sqlite_url(unusable))
    with TestClient(create_app(settings)) as test_client:
        yield test_client

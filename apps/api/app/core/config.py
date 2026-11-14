"""Centralized, strictly validated application configuration.

All settings come from environment variables prefixed with ``EASA_`` or from
an optional ``.env`` file in the working directory. Invalid or unknown values
fail application startup instead of being silently ignored.
"""

import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

API_ROOT = Path(__file__).resolve().parents[2]

# Database drivers the application is designed and tested for.
ALLOWED_DATABASE_DRIVERS = frozenset({"sqlite", "sqlite+pysqlite", "postgresql+psycopg"})


def _default_database_url() -> SecretStr:
    # Local SQLite file under apps/api/var/, which is git-ignored.
    return SecretStr(f"sqlite:///{(API_ROOT / 'var' / 'easa.db').as_posix()}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EASA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
        # Never echo raw input (e.g. a database URL with a password) in errors.
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = Field(default_factory=_default_database_url)
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Uploaded file contents (content-addressed). Never served directly; git-ignored.
    storage_dir: Path = Field(default_factory=lambda: API_ROOT / "var" / "uploads")
    # Largest accepted uploaded file. The whole request body may exceed this by
    # a small multipart overhead (see app.core.middleware.BodySizeLimitMiddleware).
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    # PDFs with more pages are rejected during processing (bounds parsing work).
    max_pdf_pages: int = Field(default=500, ge=1, le=5000)
    # Chunking (P2-M4). See app.services.chunking for the strategies.
    chunk_strategy: Literal["fixed", "structured"] = "structured"
    chunk_max_chars: int = Field(default=1200, ge=100, le=20000)
    chunk_overlap_chars: int = Field(default=150, ge=0)
    # Embeddings (Phase 3). "onnx" = pinned local bge-small-en-v1.5 (run the
    # download command first); "hashing" = deterministic, non-semantic test embedder.
    embedding_provider: Literal["onnx", "hashing"] = "onnx"
    embedding_model_dir: Path = Field(default_factory=lambda: API_ROOT / "var" / "models")
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    # Development-only identity (ADR-014). Synthetic values; never taken from
    # requests. Document endpoints are not mounted in production.
    dev_tenant_id: uuid.UUID = uuid.UUID("00000000-0000-4000-8000-000000000001")
    dev_user_id: uuid.UUID = uuid.UUID("00000000-0000-4000-8000-000000000002")

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("database_url is not a valid database URL") from None
        if url.drivername not in ALLOWED_DATABASE_DRIVERS:
            allowed = ", ".join(sorted(ALLOWED_DATABASE_DRIVERS))
            raise ValueError(f"database_url driver must be one of: {allowed}")
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_cors_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            parts = urlsplit(origin)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or "*" in origin
                or parts.path not in {"", "/"}
                or parts.query
                or parts.fragment
            ):
                raise ValueError(
                    "each CORS origin must be an explicit http(s)://host[:port] "
                    "without wildcards, paths, queries or fragments"
                )
        return [origin.rstrip("/") for origin in origins]

    @model_validator(mode="after")
    def _validate_chunking(self) -> Settings:
        if self.chunk_overlap_chars >= self.chunk_max_chars // 2:
            raise ValueError("chunk_overlap_chars must be less than half of chunk_max_chars")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    return Settings()

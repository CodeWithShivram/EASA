"""Portable column types."""

from datetime import UTC, datetime
from typing import Any

import numpy as np
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, LargeBinary
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine

# Vectors are float32 little-endian in Python and in SQLite blobs.
VECTOR_DTYPE = np.dtype("<f4")


def utc_now() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC timestamps on every backend.

    PostgreSQL stores ``timestamptz``; SQLite has no time zones, so values are
    stored as UTC and returned with ``tzinfo=UTC``. Naive datetimes are rejected.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EmbeddingVector(TypeDecorator[bytes]):
    """An embedding as float32 little-endian bytes in Python, on every backend.

    SQLite stores the bytes as a blob. PostgreSQL stores a pgvector ``vector``
    (without a fixed dimension, so one table holds vectors of several models),
    which lets the database compute distances. Callers always see bytes.
    """

    impl = LargeBinary
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(VECTOR())
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value: bytes | None, dialect: Dialect) -> Any:
        if value is None or dialect.name != "postgresql":
            return value
        return np.frombuffer(value, dtype=VECTOR_DTYPE)

    def process_result_value(self, value: Any, dialect: Dialect) -> bytes | None:
        if value is None or dialect.name != "postgresql":
            return value
        return np.asarray(value, dtype=VECTOR_DTYPE).tobytes()

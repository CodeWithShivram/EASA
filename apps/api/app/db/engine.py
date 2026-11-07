"""SQLAlchemy engine construction.

The engine is the only place that knows which database backend is in use.
Callers depend on the engine or on higher-level abstractions, never on a
specific driver.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url


def create_db_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    connect_args: dict[str, Any] = {}

    if url.get_backend_name() == "sqlite":
        # FastAPI runs sync handlers in a thread pool.
        connect_args["check_same_thread"] = False
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)

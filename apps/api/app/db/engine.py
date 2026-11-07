"""SQLAlchemy engine construction.

The engine is the only place that knows which database backend is in use.
Callers depend on the engine or on higher-level abstractions, never on a
specific driver.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    # SQLite does not enforce foreign keys unless enabled per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    connect_args: dict[str, Any] = {}
    is_sqlite = url.get_backend_name() == "sqlite"

    if is_sqlite:
        # FastAPI runs sync handlers in a thread pool.
        connect_args["check_same_thread"] = False
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine

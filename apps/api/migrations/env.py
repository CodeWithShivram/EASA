"""Alembic migration environment.

The database URL comes from the application's validated settings, never from
alembic.ini, so migrations and the running API always target the same database.
"""

from typing import Any

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy.engine import make_url

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.db.engine import create_db_engine
from app.db.fts import is_keyword_index_object
from app.db.models import Base
from app.db.types import UtcDateTime

settings = load_settings()
configure_logging(settings.log_level)

database_url = settings.database_url.get_secret_value()
target_metadata = Base.metadata
# SQLite cannot ALTER most constraints; batch mode recreates tables instead.
render_as_batch = make_url(database_url).get_backend_name() == "sqlite"


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    # The FTS5 keyword index (and its shadow tables) is managed by hand-written
    # migrations, not by the ORM, so autogenerate and `alembic check` ignore it.
    return not (type_ == "table" and is_keyword_index_object(name))


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    # Render app-specific column types as their portable storage type, so
    # migrations never import application code.
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade head --sql``)."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=render_as_batch,
        render_item=render_item,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(database_url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=render_as_batch,
                render_item=render_item,
                include_name=include_name,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

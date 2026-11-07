"""Alembic migration environment.

The database URL comes from the application's validated settings, never from
alembic.ini, so migrations and the running API always target the same database.
"""

from alembic import context
from sqlalchemy.engine import make_url

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.db.engine import create_db_engine
from app.db.models import Base

settings = load_settings()
configure_logging(settings.log_level)

database_url = settings.database_url.get_secret_value()
target_metadata = Base.metadata
# SQLite cannot ALTER most constraints; batch mode recreates tables instead.
render_as_batch = make_url(database_url).get_backend_name() == "sqlite"


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade head --sql``)."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=render_as_batch,
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
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

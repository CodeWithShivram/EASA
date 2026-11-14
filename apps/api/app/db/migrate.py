"""Run Alembic migrations from code (used by the evaluation runner)."""

from alembic import command
from alembic.config import Config

from app.core.config import API_ROOT


def upgrade_to_head(database_url: str) -> None:
    """Apply all migrations to the given database, exactly as ``alembic upgrade head``."""
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")

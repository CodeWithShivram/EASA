import logging

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.services.health import DependencyUnavailableError

logger = logging.getLogger(__name__)


class SqlAlchemyDatabaseProbe:
    """Checks database connectivity by executing ``SELECT 1``."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ping(self) -> None:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
        except SQLAlchemyError as exc:
            # Log only the error type; driver messages can contain connection details.
            logger.warning("database ping failed", extra={"error_type": type(exc).__name__})
            raise DependencyUnavailableError("database") from exc

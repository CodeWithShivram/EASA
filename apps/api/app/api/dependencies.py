from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.probe import SqlAlchemyDatabaseProbe
from app.db.session import iter_session
from app.services.health import HealthService


def get_db_session(request: Request) -> Iterator[Session]:
    yield from iter_session(request.app.state.session_factory)


def get_health_service(request: Request) -> HealthService:
    return HealthService(database=SqlAlchemyDatabaseProbe(request.app.state.engine))

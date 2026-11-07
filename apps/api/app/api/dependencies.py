from fastapi import Request

from app.db.probe import SqlAlchemyDatabaseProbe
from app.services.health import HealthService


def get_health_service(request: Request) -> HealthService:
    return HealthService(database=SqlAlchemyDatabaseProbe(request.app.state.engine))

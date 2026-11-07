"""Health and readiness checks.

Liveness says only that the process is serving requests and never touches
external dependencies. Readiness checks the dependencies the API needs.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

CheckStatus = Literal["ok", "unavailable"]


class DependencyUnavailableError(Exception):
    def __init__(self, dependency: str) -> None:
        super().__init__(f"{dependency} is unavailable")
        self.dependency = dependency


class DatabaseProbe(Protocol):
    def ping(self) -> None:
        """Return if the database is reachable; raise DependencyUnavailableError otherwise."""
        ...


@dataclass(frozen=True)
class ReadinessReport:
    database: CheckStatus

    @property
    def is_ready(self) -> bool:
        return self.database == "ok"


class HealthService:
    def __init__(self, database: DatabaseProbe) -> None:
        self._database = database

    def check_readiness(self) -> ReadinessReport:
        try:
            self._database.ping()
        except DependencyUnavailableError:
            return ReadinessReport(database="unavailable")
        return ReadinessReport(database="ok")

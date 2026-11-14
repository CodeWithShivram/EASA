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


class EmbeddingsProbe(Protocol):
    def is_available(self) -> bool:
        """Whether the configured embedding model can run (files present)."""
        ...


@dataclass(frozen=True)
class ReadinessReport:
    database: CheckStatus
    embeddings: CheckStatus = "ok"

    @property
    def is_ready(self) -> bool:
        return self.database == "ok" and self.embeddings == "ok"


class HealthService:
    def __init__(self, database: DatabaseProbe, embeddings: EmbeddingsProbe | None = None) -> None:
        self._database = database
        self._embeddings = embeddings

    def check_readiness(self) -> ReadinessReport:
        try:
            self._database.ping()
            database: CheckStatus = "ok"
        except DependencyUnavailableError:
            database = "unavailable"
        embeddings: CheckStatus = (
            "ok" if self._embeddings is None or self._embeddings.is_available() else "unavailable"
        )
        return ReadinessReport(database=database, embeddings=embeddings)

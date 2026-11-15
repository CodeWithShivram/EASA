"""Health and readiness checks.

Liveness says only that the process is serving requests and never touches
external dependencies. Readiness checks the dependencies the API needs.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

CheckStatus = Literal["ok", "unavailable"]
# "disabled" when answer generation is not configured; it does not affect readiness.
ModelStatus = Literal["ok", "unavailable", "disabled"]


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


class ModelProbe(Protocol):
    def is_available(self) -> bool:
        """Whether the configured chat model can serve requests."""
        ...


@dataclass(frozen=True)
class ReadinessReport:
    database: CheckStatus
    embeddings: CheckStatus = "ok"
    model: ModelStatus = "disabled"

    @property
    def is_ready(self) -> bool:
        # A configured model must be available; a disabled one is not required.
        return self.database == "ok" and self.embeddings == "ok" and self.model != "unavailable"


class HealthService:
    def __init__(
        self,
        database: DatabaseProbe,
        embeddings: EmbeddingsProbe | None = None,
        model: ModelProbe | None = None,
    ) -> None:
        self._database = database
        self._embeddings = embeddings
        self._model = model

    def check_readiness(self) -> ReadinessReport:
        try:
            self._database.ping()
            database: CheckStatus = "ok"
        except DependencyUnavailableError:
            database = "unavailable"
        embeddings: CheckStatus = (
            "ok" if self._embeddings is None or self._embeddings.is_available() else "unavailable"
        )
        model: ModelStatus = "disabled"
        if self._model is not None:
            model = "ok" if self._model.is_available() else "unavailable"
        return ReadinessReport(database=database, embeddings=embeddings, model=model)

"""Tool contracts (Phase 5).

A tool is a server-side function with a typed input and output, a required
permission and a timeout. The model may only *propose* a call; the executor
decides whether it runs (app.tools.executor). Tool messages and error codes
must be safe to show to users and models: never stack traces or raw data from
other tenants.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.core.identity import Identity

TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{1,62}")


class ToolError(Exception):
    """An expected failure with a safe message and a machine-readable code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ToolTransientError(ToolError):
    """A failure worth retrying (only for tools that allow retries)."""


@dataclass(frozen=True)
class ToolContext:
    identity: Identity
    # Tools open their own sessions, so a tool still running after its timeout
    # never shares a session with the request.
    session_factory: sessionmaker[Session]
    correlation_id: str | None


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]  # must forbid unknown fields
    Output: ClassVar[type[BaseModel]]
    # Permission the caller must hold, e.g. "tickets:read".
    permission: ClassVar[str]
    # Consequential tools change something and run only after explicit confirmation.
    consequential: ClassVar[bool] = False
    timeout_seconds: ClassVar[float] = 10.0
    # Retries after ToolTransientError; must be 0 for consequential tools.
    retries: ClassVar[int] = 0

    @abstractmethod
    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        """Do the work; raise ToolError for expected failures."""

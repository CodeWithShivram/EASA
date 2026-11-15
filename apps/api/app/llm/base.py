"""Chat model interface (the port used by answer generation, Phase 4).

Business code depends only on ChatModel, never on a provider. Error messages
must never contain prompt or response text, which can include document
content or user questions.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class ChatResult:
    text: str
    model_id: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ModelUnavailableError(Exception):
    """The model cannot be used: server unreachable or model not installed."""


class ModelResponseError(Exception):
    """A call reached the model but failed: timeout, error status or malformed output."""


class ChatModel(Protocol):
    # Provider and model, e.g. "ollama:<model>"; recorded with every answer.
    model_id: str

    def is_available(self) -> bool:
        """Cheap check that the model can serve requests (used by readiness)."""
        ...

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Return the model's reply to the conversation.

        With ``json_schema`` the server constrains the reply to JSON matching it
        (grammar-based decoding); callers must still validate the result.
        Raises ModelUnavailableError or ModelResponseError.
        """
        ...

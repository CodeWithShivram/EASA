"""Deterministic chat model for tests and offline development (never in production)."""

from collections.abc import Callable, Sequence

from app.llm.base import ChatMessage, ChatResult, ModelUnavailableError

DEFAULT_REPLY = "This is a deterministic reply from the fake model."

Reply = str | Callable[[Sequence[ChatMessage]], str]


class FakeChatModel:
    """Replies with a fixed text or a function of the messages, and records every call."""

    model_id = "fake-chat-v1"

    def __init__(self, reply: Reply = DEFAULT_REPLY, *, available: bool = True) -> None:
        self._reply = reply
        self._available = available
        self.calls: list[tuple[ChatMessage, ...]] = []

    def is_available(self) -> bool:
        return self._available

    def generate(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, temperature: float
    ) -> ChatResult:
        if not self._available:
            raise ModelUnavailableError("fake model configured as unavailable")
        self.calls.append(tuple(messages))
        text = self._reply(messages) if callable(self._reply) else self._reply
        return ChatResult(
            text=text,
            model_id=self.model_id,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
        )

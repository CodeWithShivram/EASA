"""Deterministic chat model for tests and offline development (never in production)."""

import re
from collections.abc import Callable, Sequence

from app.llm.base import ChatMessage, ChatResult, ModelUnavailableError

DEFAULT_REPLY = "This is a deterministic reply from the fake model."

Reply = str | Callable[[Sequence[ChatMessage]], str]

# Matches the answer prompt's source elements (app.services.answers).
_FIRST_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\s*(.*?)\s*</source>', re.DOTALL)
_SENTENCE = re.compile(r"(.+?[.!?])(?:\s|$)", re.DOTALL)


def extractive_reply(messages: Sequence[ChatMessage]) -> str:
    """Quote the first sentence of the first source with its citation, or decline.

    Used for ``EASA_MODEL_PROVIDER=fake`` so the answer pipeline can be tried
    end to end without a real model. It does not understand the question.
    """
    match = _FIRST_SOURCE.search(messages[-1].content) if messages else None
    if match is None:
        return "INSUFFICIENT_EVIDENCE"
    label, text = match.groups()
    sentence = _SENTENCE.match(text)
    quote = (sentence.group(1) if sentence else text)[:300].strip()
    return f"{quote} [{label}]"


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

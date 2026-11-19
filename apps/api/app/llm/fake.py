"""Deterministic chat model for tests and offline development (never in production)."""

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from app.llm.base import ChatMessage, ChatResult, ModelUnavailableError

DEFAULT_REPLY = "This is a deterministic reply from the fake model."

Reply = str | Callable[[Sequence[ChatMessage]], str]

# Matches the answer prompt's source elements (app.services.answers).
_FIRST_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\s*(.*?)\s*</source>', re.DOTALL)
_SENTENCE = re.compile(r"(.+?[.!?])(?:\s|$)", re.DOTALL)
# The agent's system prompt (app.services.agent) and what the scripted agent looks for.
_AGENT_PROMPT = "can use tools"
_NEW_TICKET = re.compile(r"^\s*(?:please\s+)?(?:open|create|raise|file)\b.*\bticket\b", re.I)
_TICKET_NUMBER = re.compile(r"\bticket\s+#?(\d{1,7})\b", re.IGNORECASE)
_STATUS = re.compile(r'"status": "([a-z_]+)"')


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


def _agent_step(messages: Sequence[ChatMessage]) -> str:
    """One step of a scripted agent: a request for a ticket becomes a draft
    proposal, "ticket N" a status lookup, anything else a knowledge search;
    after a tool result, a short final answer."""
    request = messages[1].content if len(messages) > 1 else ""
    if len(messages) <= 2:
        if _NEW_TICKET.search(request):
            summary = request.split(":", 1)[-1].strip()
            title = summary[:60] if len(summary) >= 5 else "Support request"
            arguments = {"title": title, "description": request[:2000].ljust(10, ".")}
            return json.dumps({"action": "create_draft_ticket", "arguments": arguments})
        if number := _TICKET_NUMBER.search(request):
            arguments = {"number": int(number.group(1))}
            return json.dumps({"action": "get_ticket_status", "arguments": arguments})
        return json.dumps(
            {"action": "search_knowledge_base", "arguments": {"query": request[:1000]}}
        )
    result = messages[-1].content
    if '"outcome": "succeeded"' not in result:
        answer = "I could not complete that request."
    elif status := _STATUS.search(result):
        answer = f"The ticket's status is {status.group(1).replace('_', ' ')}."
    else:
        answer = "Here is what I found."
    return json.dumps({"action": "final_answer", "answer": answer})


def development_reply(messages: Sequence[ChatMessage]) -> str:
    """The reply of ``EASA_MODEL_PROVIDER=fake``: a scripted agent for agent steps,
    otherwise ``extractive_reply``. Lets the web app, and its browser tests,
    run every flow without a model (P8-M3)."""
    if messages and _AGENT_PROMPT in messages[0].content:
        return _agent_step(messages)
    return extractive_reply(messages)


class FakeChatModel:
    """Replies with a fixed text or a function of the messages, and records every call."""

    model_id = "fake-chat-v1"

    def __init__(self, reply: Reply = DEFAULT_REPLY, *, available: bool = True) -> None:
        self._reply = reply
        self._available = available
        self.calls: list[tuple[ChatMessage, ...]] = []
        # The json_schema of each call (None when not constrained).
        self.schemas: list[dict[str, Any] | None] = []

    def is_available(self) -> bool:
        return self._available

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        if not self._available:
            raise ModelUnavailableError("fake model configured as unavailable")
        self.calls.append(tuple(messages))
        self.schemas.append(json_schema)
        text = self._reply(messages) if callable(self._reply) else self._reply
        return ChatResult(
            text=text,
            model_id=self.model_id,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
        )

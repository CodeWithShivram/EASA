"""Chat model served by a local llama.cpp server (https://github.com/ggml-org/llama.cpp).

Uses the server's OpenAI-compatible, non-streaming ``POST /v1/chat/completions``.
The server holds one model, loaded from a pinned GGUF file (app.llm.registry).
Nothing here logs prompt or response text.
"""

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.llm.base import ChatMessage, ChatResult, ModelResponseError
from app.llm.http import (
    AVAILABILITY_TIMEOUT_SECONDS,
    MAX_REPLY_CHARS,
    build_client,
    count,
    post_json,
)

logger = logging.getLogger(__name__)


class LlamaCppChatModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id = f"llamacpp:{model}"
        self._model = model
        self._client = build_client(base_url, timeout_seconds, transport)

    def is_available(self) -> bool:
        """True if the server has finished loading and serves the configured model."""
        try:
            health = self._client.get("/health", timeout=AVAILABILITY_TIMEOUT_SECONDS)
            health.raise_for_status()  # 503 while the model is still loading
            listing = self._client.get("/v1/models", timeout=AVAILABILITY_TIMEOUT_SECONDS)
            listing.raise_for_status()
            names = {m.get("id") for m in listing.json().get("data", []) if isinstance(m, dict)}
        except (httpx.HTTPError, ValueError, AttributeError) as error:
            logger.warning(
                "model availability check failed", extra={"error_type": type(error).__name__}
            )
            return False
        return self._model in names

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if json_schema is not None:
            # Grammar-constrained decoding (verified with build b12407, P5-M3).
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": json_schema, "strict": True},
            }
        data = post_json(self._client, "/v1/chat/completions", payload)
        try:
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
        except KeyError, IndexError, TypeError:
            raise ModelResponseError("the model server returned a malformed response") from None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ChatResult(
            text=text[:MAX_REPLY_CHARS],
            model_id=self.model_id,
            prompt_tokens=count(usage.get("prompt_tokens")),
            completion_tokens=count(usage.get("completion_tokens")),
        )

    def close(self) -> None:
        self._client.close()

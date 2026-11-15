"""Chat model served by a local Ollama server (https://github.com/ollama/ollama).

Uses the non-streaming ``POST /api/chat`` endpoint (client rules in
app.llm.http). Nothing here logs prompt or response text.
"""

import logging
from collections.abc import Sequence

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


class OllamaChatModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id = f"ollama:{model}"
        self._model = model
        self._client = build_client(base_url, timeout_seconds, transport)

    def is_available(self) -> bool:
        """True if the server answers and has the configured model installed."""
        try:
            response = self._client.get("/api/tags", timeout=AVAILABILITY_TIMEOUT_SECONDS)
            response.raise_for_status()
            models = response.json().get("models", [])
            names = {m.get(key) for m in models if isinstance(m, dict) for key in ("name", "model")}
        except (httpx.HTTPError, ValueError, AttributeError) as error:
            logger.warning(
                "model availability check failed", extra={"error_type": type(error).__name__}
            )
            return False
        return self._model in names or f"{self._model}:latest" in names

    def generate(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, temperature: float
    ) -> ChatResult:
        data = post_json(
            self._client,
            "/api/chat",
            {
                "model": self._model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        try:
            text = data["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
        except KeyError, TypeError:
            raise ModelResponseError("the model server returned a malformed response") from None
        return ChatResult(
            text=text[:MAX_REPLY_CHARS],
            model_id=self.model_id,
            prompt_tokens=count(data.get("prompt_eval_count")),
            completion_tokens=count(data.get("eval_count")),
        )

    def close(self) -> None:
        self._client.close()

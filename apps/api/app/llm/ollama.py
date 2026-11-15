"""Chat model served by a local Ollama server (https://github.com/ollama/ollama).

Uses the non-streaming ``POST /api/chat`` endpoint. Proxy environment
variables are ignored (``trust_env=False``), so prompts containing document
text go only to the configured server. Nothing here logs prompt or response
text.
"""

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.llm.base import ChatMessage, ChatResult, ModelResponseError, ModelUnavailableError

logger = logging.getLogger(__name__)

# Readiness must stay fast even if the server hangs.
AVAILABILITY_TIMEOUT_SECONDS = 2.0
CONNECT_TIMEOUT_SECONDS = 5.0
# Defensive cap on reply text; max_tokens normally keeps replies far shorter.
MAX_REPLY_CHARS = 20_000


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


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
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

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
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.TimeoutException:
            raise ModelResponseError("the model did not answer in time") from None
        except httpx.TransportError:
            raise ModelUnavailableError("the model server cannot be reached") from None
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ModelUnavailableError("the configured model is not installed")
        if response.status_code != httpx.codes.OK:
            raise ModelResponseError(f"the model server returned status {response.status_code}")
        try:
            data = response.json()
            text = data["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
        except ValueError, KeyError, TypeError:
            raise ModelResponseError("the model server returned a malformed response") from None
        return ChatResult(
            text=text[:MAX_REPLY_CHARS],
            model_id=self.model_id,
            prompt_tokens=_count(data.get("prompt_eval_count")),
            completion_tokens=_count(data.get("eval_count")),
        )

    def close(self) -> None:
        self._client.close()

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.base import ChatMessage, ModelResponseError, ModelUnavailableError
from app.llm.factory import build_chat_model
from app.llm.http import MAX_REPLY_CHARS
from app.llm.llamacpp import LlamaCppChatModel
from app.llm.registry import DEFAULT_CHAT_MODEL, ModelFileError, verify_model_file

SENSITIVE_PROMPT = "confidential question about project falcon"
MESSAGES = [ChatMessage("system", "Answer briefly."), ChatMessage("user", SENSITIVE_PROMPT)]
ALIAS = "tiny-q4"


def llamacpp(handler: Callable[[httpx.Request], httpx.Response]) -> LlamaCppChatModel:
    return LlamaCppChatModel(
        "http://llm.test", ALIAS, timeout_seconds=5, transport=httpx.MockTransport(handler)
    )


def completion(content: object = "Hello [S1].", **extra: object) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}], **extra}
    )


def raise_(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


# --- adapter -----------------------------------------------------------------


def test_sends_an_openai_compatible_chat_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion(usage={"prompt_tokens": 40, "completion_tokens": 6})

    result = llamacpp(handler).generate(MESSAGES, max_tokens=128, temperature=0.1)

    assert result.text == "Hello [S1]."
    assert result.model_id == f"llamacpp:{ALIAS}"
    assert (result.prompt_tokens, result.completion_tokens) == (40, 6)
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", "http://llm.test/v1/chat/completions")
    assert json.loads(request.content) == {
        "model": ALIAS,
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": SENSITIVE_PROMPT},
        ],
        "max_tokens": 128,
        "temperature": 0.1,
        "stream": False,
    }


def test_caps_reply_length_and_ignores_bad_usage() -> None:
    result = llamacpp(
        lambda _: completion("x" * (MAX_REPLY_CHARS + 10), usage={"prompt_tokens": True})
    ).generate(MESSAGES, max_tokens=16, temperature=0)

    assert len(result.text) == MAX_REPLY_CHARS
    assert result.prompt_tokens is None


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (raise_(httpx.ConnectError("refused")), ModelUnavailableError),
        (lambda _: httpx.Response(503, json={"error": "loading model"}), ModelUnavailableError),
        (lambda _: httpx.Response(404), ModelUnavailableError),
        (raise_(httpx.ReadTimeout("slow")), ModelResponseError),
        (lambda _: httpx.Response(500, text="boom"), ModelResponseError),
        (lambda _: httpx.Response(200, text="not json"), ModelResponseError),
        (lambda _: httpx.Response(200, json={"choices": []}), ModelResponseError),
        (lambda _: httpx.Response(200, json=["not", "an", "object"]), ModelResponseError),
        (lambda _: completion(content=None), ModelResponseError),
    ],
)
def test_failures_map_to_model_errors_without_prompt_text(
    handler: Callable[[httpx.Request], httpx.Response], error: type[Exception]
) -> None:
    with pytest.raises(error) as raised:
        llamacpp(handler).generate(MESSAGES, max_tokens=16, temperature=0)

    assert SENSITIVE_PROMPT not in str(raised.value)
    assert raised.value.__cause__ is None


def server(health: int = 200, models: object = None) -> Callable[[httpx.Request], httpx.Response]:
    listing = {"data": [{"id": ALIAS}]} if models is None else models

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(health, json={"status": "ok" if health == 200 else "loading"})
        return httpx.Response(200, json=listing)

    return handler


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (server(), True),
        (server(health=503), False),  # still loading the model
        (server(models={"data": [{"id": "other-model"}]}), False),
        (server(models={"data": "nonsense"}), False),
        (server(models=["unexpected"]), False),
        (raise_(httpx.ConnectError("refused")), False),
    ],
)
def test_availability(handler: Callable[[httpx.Request], httpx.Response], expected: bool) -> None:
    assert llamacpp(handler).is_available() is expected


# --- pinned model file -------------------------------------------------------


def test_verify_accepts_the_pinned_file(tmp_path: Path) -> None:
    data = b"synthetic model bytes"
    path = tmp_path / "model.gguf"
    path.write_bytes(data)
    spec = replace(
        DEFAULT_CHAT_MODEL, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )

    verify_model_file(spec, path)  # does not raise


@pytest.mark.parametrize(
    ("content", "message"),
    [(None, "missing"), (b"short", "size"), (b"x" * 21, "SHA-256")],
)
def test_verify_rejects_missing_or_altered_files(
    tmp_path: Path, content: bytes | None, message: str
) -> None:
    path = tmp_path / "model.gguf"
    if content is not None:
        path.write_bytes(content)
    spec = replace(DEFAULT_CHAT_MODEL, size_bytes=21, sha256="0" * 64)

    with pytest.raises(ModelFileError, match=message):
        verify_model_file(spec, path)


def test_the_default_model_is_pinned() -> None:
    assert len(DEFAULT_CHAT_MODEL.revision) == 40
    assert len(DEFAULT_CHAT_MODEL.sha256) == 64
    assert DEFAULT_CHAT_MODEL.licence == "Apache-2.0"


# --- configuration -----------------------------------------------------------


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_factory_builds_the_llamacpp_model() -> None:
    model = build_chat_model(
        settings(model_provider="llamacpp", model_name=DEFAULT_CHAT_MODEL.name)
    )

    assert isinstance(model, LlamaCppChatModel)
    assert model.model_id == f"llamacpp:{DEFAULT_CHAT_MODEL.name}"


@pytest.mark.parametrize(
    "values",
    [
        {"model_provider": "llamacpp"},  # no model name
        {"model_provider": "llamacpp", "model_name": "bad name"},
        {"llamacpp_base_url": "http://user:secret@localhost:8082"},
        {"llamacpp_base_url": "http://localhost:8082/v1"},
        {"llamacpp_base_url": "file:///etc/passwd"},
    ],
)
def test_invalid_llamacpp_settings_are_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        settings(**values)

    assert "secret" not in str(error.value)

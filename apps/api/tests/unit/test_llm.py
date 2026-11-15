import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.base import ChatMessage, ModelResponseError, ModelUnavailableError
from app.llm.factory import build_chat_model
from app.llm.fake import DEFAULT_REPLY, FakeChatModel
from app.llm.ollama import MAX_REPLY_CHARS, OllamaChatModel
from app.services.health import HealthService

SENSITIVE_PROMPT = "confidential question about project falcon"
MESSAGES = [ChatMessage("system", "Answer briefly."), ChatMessage("user", SENSITIVE_PROMPT)]


def ollama(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaChatModel:
    return OllamaChatModel(
        "http://ollama.test", "tiny:1b", timeout_seconds=5, transport=httpx.MockTransport(handler)
    )


def chat_reply(content: object = "Hello [S1].", **extra: object) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, **extra})


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


# --- fake model --------------------------------------------------------------


def test_fake_model_replies_deterministically_and_records_calls() -> None:
    model = FakeChatModel()

    result = model.generate(MESSAGES, max_tokens=50, temperature=0)

    assert result.text == DEFAULT_REPLY
    assert result.model_id == "fake-chat-v1"
    assert model.calls == [tuple(MESSAGES)]


def test_fake_model_reply_can_depend_on_the_messages() -> None:
    model = FakeChatModel(lambda messages: messages[-1].content.upper())

    assert model.generate(MESSAGES, max_tokens=50, temperature=0).text == SENSITIVE_PROMPT.upper()


def test_unavailable_fake_model_raises() -> None:
    model = FakeChatModel(available=False)

    assert not model.is_available()
    with pytest.raises(ModelUnavailableError):
        model.generate(MESSAGES, max_tokens=50, temperature=0)


# --- Ollama adapter ----------------------------------------------------------


def test_ollama_sends_a_non_streaming_chat_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return chat_reply(prompt_eval_count=42, eval_count=7)

    result = ollama(handler).generate(MESSAGES, max_tokens=128, temperature=0.2)

    assert result.text == "Hello [S1]."
    assert result.model_id == "ollama:tiny:1b"
    assert (result.prompt_tokens, result.completion_tokens) == (42, 7)
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", "http://ollama.test/api/chat")
    body = json.loads(request.content)
    assert body == {
        "model": "tiny:1b",
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": SENSITIVE_PROMPT},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 128},
    }


def test_ollama_caps_reply_length_and_ignores_bad_counts() -> None:
    result = ollama(lambda _: chat_reply("x" * (MAX_REPLY_CHARS + 50), eval_count="many")).generate(
        MESSAGES, max_tokens=16, temperature=0
    )

    assert len(result.text) == MAX_REPLY_CHARS
    assert result.completion_tokens is None


def raise_(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (raise_(httpx.ConnectError("refused")), ModelUnavailableError),
        (lambda _: httpx.Response(404, json={"error": "model not found"}), ModelUnavailableError),
        (raise_(httpx.ReadTimeout("slow")), ModelResponseError),
        (lambda _: httpx.Response(500, text="boom"), ModelResponseError),
        (lambda _: httpx.Response(200, text="not json"), ModelResponseError),
        (lambda _: httpx.Response(200, json={"done": True}), ModelResponseError),
        (lambda _: chat_reply(content=["not", "text"]), ModelResponseError),
    ],
)
def test_ollama_failures_map_to_model_errors_without_prompt_text(
    handler: Callable[[httpx.Request], httpx.Response], error: type[Exception]
) -> None:
    with pytest.raises(error) as raised:
        ollama(handler).generate(MESSAGES, max_tokens=16, temperature=0)

    assert SENSITIVE_PROMPT not in str(raised.value)
    assert raised.value.__cause__ is None  # driver details are not chained


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (lambda _: httpx.Response(200, json={"models": [{"name": "tiny:1b"}]}), True),
        (lambda _: httpx.Response(200, json={"models": [{"model": "tiny:1b"}]}), True),
        (lambda _: httpx.Response(200, json={"models": [{"name": "other:7b"}]}), False),
        (lambda _: httpx.Response(200, json={"models": "nonsense"}), False),
        (lambda _: httpx.Response(200, text="not json"), False),
        (lambda _: httpx.Response(503), False),
        (raise_(httpx.ConnectError("refused")), False),
    ],
)
def test_ollama_availability(
    handler: Callable[[httpx.Request], httpx.Response], expected: bool
) -> None:
    assert ollama(handler).is_available() is expected


def test_untagged_model_names_match_latest() -> None:
    model = OllamaChatModel(
        "http://ollama.test",
        "tiny",
        timeout_seconds=5,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"models": [{"name": "tiny:latest"}]})
        ),
    )

    assert model.is_available()


# --- configuration and factory -----------------------------------------------


def test_answer_generation_is_disabled_by_default() -> None:
    config = settings()

    assert config.model_provider == "none"
    assert build_chat_model(config) is None


def test_factory_builds_configured_providers() -> None:
    assert isinstance(build_chat_model(settings(model_provider="fake")), FakeChatModel)
    model = build_chat_model(
        settings(model_provider="ollama", model_name="tiny:1b", ollama_base_url="http://h:1/")
    )
    assert isinstance(model, OllamaChatModel)
    assert model.model_id == "ollama:tiny:1b"


@pytest.mark.parametrize(
    "values",
    [
        {"model_provider": "ollama"},  # no model name
        {"model_provider": "ollama", "model_name": "bad name"},
        {"model_provider": "ollama", "model_name": "-flag"},
        {"model_provider": "fake", "environment": "production"},
        {"ollama_base_url": "ftp://localhost:11434"},
        {"ollama_base_url": "http://user:secret@localhost:11434"},
        {"ollama_base_url": "http://localhost:11434/api"},
        {"ollama_base_url": "http://localhost:11434?x=1"},
        {"model_timeout_seconds": 0},
        {"model_max_output_tokens": 8},
        {"model_temperature": 1.5},
        {"model_provider": "openai"},
    ],
)
def test_invalid_model_settings_are_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        settings(**values)

    assert "secret" not in str(error.value)


# --- readiness ---------------------------------------------------------------


class OkDatabase:
    def ping(self) -> None:
        return None


@pytest.mark.parametrize(
    ("model", "status", "ready"),
    [
        (None, "disabled", True),
        (FakeChatModel(), "ok", True),
        (FakeChatModel(available=False), "unavailable", False),
    ],
)
def test_readiness_reports_the_model(model: FakeChatModel | None, status: str, ready: bool) -> None:
    report = HealthService(OkDatabase(), model=model).check_readiness()

    assert report.model == status
    assert report.is_ready is ready

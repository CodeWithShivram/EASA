"""Checks against a real local chat model (P4-M3).

Skipped unless EASA_TEST_LLM_URL points at a running llama.cpp server, e.g.
``docker compose --profile llm up -d llm`` and
``$env:EASA_TEST_LLM_URL = "http://127.0.0.1:8082"``. Never run in CI.

These check the integration and basic behaviour only; answer quality is
measured by the Phase 4 evaluation (P4-M5).
"""

import os
import uuid
from collections.abc import Iterator

import pytest

from app.core.identity import Identity
from app.llm.base import ChatMessage
from app.llm.llamacpp import LlamaCppChatModel
from app.llm.registry import DEFAULT_CHAT_MODEL
from app.services.answers import AnswerService, AnswerStatus
from app.services.search import SearchHit, SearchMode, SearchResult

# Read at import time: the autouse fixture in tests/conftest.py removes EASA_* variables.
LLM_URL = os.environ.get("EASA_TEST_LLM_URL")
pytestmark = pytest.mark.skipif(not LLM_URL, reason="EASA_TEST_LLM_URL is not set")

IDENTITY = Identity(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())


def hit(text: str, filename: str, section: str | None = None) -> SearchHit:
    return SearchHit(
        score=0.5,
        document_id=uuid.uuid4(),
        filename=filename,
        chunk_index=0,
        text=text,
        page_number=None,
        section=section,
        char_start=0,
        char_end=len(text),
    )


SOURCES = [
    hit(
        "Full-time employees receive 25 days of paid annual leave per calendar year. "
        "Up to five unused days may be carried over into the next year.",
        "leave_policy.txt",
        "Annual leave",
    ),
    hit(
        "Economy class is the standard for all flights. Premium economy is allowed for "
        "flights longer than six hours.",
        "travel_policy.txt",
        "Booking",
    ),
]


class FixedRetriever:
    """Test double for SearchService: always returns the two synthetic sources."""

    def search(
        self, identity: Identity, query: str, *, top_k: int, mode: SearchMode
    ) -> SearchResult:
        return SearchResult(mode=mode, model_id="test", hits=SOURCES[:top_k])


@pytest.fixture
def model() -> Iterator[LlamaCppChatModel]:
    assert LLM_URL is not None
    chat_model = LlamaCppChatModel(LLM_URL, DEFAULT_CHAT_MODEL.name, timeout_seconds=180)
    yield chat_model
    chat_model.close()  # an unclosed client's socket would warn during a later test


def service(model: LlamaCppChatModel) -> AnswerService:
    return AnswerService(FixedRetriever(), model, max_output_tokens=256, temperature=0.0)


def test_server_is_ready_with_the_pinned_model(model: LlamaCppChatModel) -> None:
    assert model.is_available()


def test_generates_a_reply_with_token_counts(model: LlamaCppChatModel) -> None:
    result = model.generate(
        [ChatMessage("user", "Reply with the single word: ready")], max_tokens=8, temperature=0
    )

    assert result.text.strip()
    assert result.model_id == f"llamacpp:{DEFAULT_CHAT_MODEL.name}"
    assert result.prompt_tokens
    assert result.completion_tokens


def test_answerable_question_is_answered_from_the_right_source(model: LlamaCppChatModel) -> None:
    result = service(model).answer(IDENTITY, "How many days of annual leave do employees get?")

    assert result.status is AnswerStatus.ANSWERED, result
    assert result.answer is not None
    assert "25" in result.answer
    assert [s.hit.filename for s in result.sources] == ["leave_policy.txt"]


def test_unanswerable_question_is_not_answered(model: LlamaCppChatModel) -> None:
    result = service(model).answer(IDENTITY, "What is the name of the company's CEO?")

    assert result.status is AnswerStatus.INSUFFICIENT_EVIDENCE, result

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import get_correlation_id, reset_correlation_id, set_correlation_id
from app.core.identity import Identity
from app.db.audit import AuditOutcome
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.repositories.audit import AuditRepository, arguments_digest
from app.tools.base import Tool, ToolContext, ToolError, ToolTransientError
from app.tools.executor import MAX_ARGUMENT_BYTES, ToolExecutor
from app.tools.registry import ToolRegistry
from tests.conftest import create_schema, sqlite_url

LEAK_MARKER = "internal stack detail 7f3a"


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class TextOut(BaseModel):
    text: str
    correlation_id: str | None = None


class Echo(Tool):
    """Test double: returns its input and the correlation ID it sees."""

    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echo."
    Input: ClassVar[type[BaseModel]] = TextIn
    Output: ClassVar[type[BaseModel]] = TextOut
    permission: ClassVar[str] = "test:read"

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        return TextOut(text=arguments.text, correlation_id=get_correlation_id())  # type: ignore[attr-defined]


class Slow(Echo):
    """Test double: exceeds its timeout."""

    name: ClassVar[str] = "slow"
    timeout_seconds: ClassVar[float] = 0.2
    finished = threading.Event()

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        time.sleep(0.6)
        Slow.finished.set()
        return super().run(context, arguments)


class Flaky(Echo):
    """Test double: fails transiently once, then works."""

    name: ClassVar[str] = "flaky"
    retries: ClassVar[int] = 1
    calls = 0

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        Flaky.calls += 1
        if Flaky.calls == 1:
            raise ToolTransientError("Temporarily unavailable.", code="busy")
        return super().run(context, arguments)


class Refusing(Echo):
    """Test double: an expected failure with a safe message."""

    name: ClassVar[str] = "refusing"

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        raise ToolError("No such ticket.", code="ticket_not_found")


class Broken(Echo):
    """Test double: an unexpected bug whose message must not leak."""

    name: ClassVar[str] = "broken"

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        raise RuntimeError(LEAK_MARKER)


class WrongOutput(Echo):
    """Test double: returns something that is not its Output model."""

    name: ClassVar[str] = "wrong_output"

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        return TextIn(text="not an output")


class Writer(Echo):
    """Test double: a consequential tool that records its side effect."""

    name: ClassVar[str] = "writer"
    permission: ClassVar[str] = "test:write"
    consequential: ClassVar[bool] = True
    writes: ClassVar[list[str]] = []

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        Writer.writes.append(arguments.text)  # type: ignore[attr-defined]
        return super().run(context, arguments)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(sqlite_url(tmp_path / "var" / "tools.db"))
    create_schema(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def executor(sessions: sessionmaker[Session]) -> Iterator[ToolExecutor]:
    Flaky.calls = 0
    Writer.writes = []
    registry = ToolRegistry(
        [Echo(), Slow(), Flaky(), Refusing(), Broken(), WrongOutput(), Writer()]
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        yield ToolExecutor(registry, AuditRepository(sessions), sessions, pool=pool)


READER = Identity(uuid.uuid4(), uuid.uuid4(), frozenset({"test:read"}))
WRITER = Identity(READER.tenant_id, READER.user_id, frozenset({"test:read", "test:write"}))


def audit(sessions: sessionmaker[Session]) -> list[tuple[str, str, str | None]]:
    rows = AuditRepository(sessions).list_for_tenant(READER.tenant_id)
    return [(r.target, r.outcome.value, r.detail) for r in reversed(rows)]


def test_a_permitted_call_runs_and_is_audited(
    executor: ToolExecutor, sessions: sessionmaker[Session]
) -> None:
    token = set_correlation_id("corr-123")
    try:
        result = executor.execute(READER, "echo", {"text": "hello"})
    finally:
        reset_correlation_id(token)

    assert result.outcome is AuditOutcome.SUCCEEDED
    assert result.output == {"text": "hello", "correlation_id": "corr-123"}
    (row,) = AuditRepository(sessions).list_for_tenant(READER.tenant_id)
    assert (row.action, row.target, row.outcome) == ("tool.execute", "echo", AuditOutcome.SUCCEEDED)
    assert row.user_id == READER.user_id
    assert row.correlation_id == "corr-123"
    assert row.arguments_digest == arguments_digest({"text": "hello"})
    assert row.duration_ms is not None


@pytest.mark.parametrize(
    ("caller", "name", "arguments", "outcome", "detail"),
    [
        (READER, "delete_everything", {}, AuditOutcome.UNKNOWN_TOOL, "not_allowed"),
        (READER, "writer", {"text": "x"}, AuditOutcome.DENIED, "test:write"),
        # Permission is checked before arguments: no schema hints for unauthorized callers.
        (READER, "writer", {"bogus": 1}, AuditOutcome.DENIED, "test:write"),
        (
            READER,
            "echo",
            {"text": "x", "tenant_id": "other"},
            AuditOutcome.INVALID_ARGUMENTS,
            "schema",
        ),
        (READER, "echo", {"text": 5}, AuditOutcome.INVALID_ARGUMENTS, "schema"),
        (
            READER,
            "echo",
            {"text": "x" * (MAX_ARGUMENT_BYTES + 1)},
            AuditOutcome.INVALID_ARGUMENTS,
            "arguments_too_large",
        ),
        (
            Identity(READER.tenant_id, READER.user_id),
            "echo",
            {"text": "x"},
            AuditOutcome.DENIED,
            "test:read",
        ),
    ],
)
def test_refused_calls_never_run(
    executor: ToolExecutor,
    sessions: sessionmaker[Session],
    caller: Identity,
    name: str,
    arguments: dict[str, object],
    outcome: AuditOutcome,
    detail: str,
) -> None:
    result = executor.execute(caller, name, arguments)

    assert (result.outcome, result.detail, result.output) == (outcome, detail, None)
    assert result.message
    assert audit(sessions) == [(name, outcome.value, detail)]
    assert Writer.writes == []


def test_consequential_tools_need_confirmation(
    executor: ToolExecutor, sessions: sessionmaker[Session]
) -> None:
    pending = executor.execute(WRITER, "writer", {"text": "draft"})

    assert pending.outcome is AuditOutcome.CONFIRMATION_REQUIRED
    assert pending.arguments == {"text": "draft"}
    assert Writer.writes == []

    done = executor.execute(WRITER, "writer", {"text": "draft"}, confirmed=True)

    assert done.outcome is AuditOutcome.SUCCEEDED
    assert Writer.writes == ["draft"]
    assert [o for _, o, _ in audit(sessions)] == ["confirmation_required", "succeeded"]


def test_timeouts_are_reported_and_audited(
    executor: ToolExecutor, sessions: sessionmaker[Session]
) -> None:
    Slow.finished.clear()
    started = time.perf_counter()

    result = executor.execute(READER, "slow", {"text": "x"})

    assert result.outcome is AuditOutcome.TIMEOUT
    assert time.perf_counter() - started < 0.55  # did not wait for the tool
    assert audit(sessions) == [("slow", "timeout", "timeout")]
    assert Slow.finished.wait(2)  # let the background thread end before teardown


def test_transient_failures_are_retried(executor: ToolExecutor) -> None:
    result = executor.execute(READER, "flaky", {"text": "x"})

    assert result.outcome is AuditOutcome.SUCCEEDED
    assert Flaky.calls == 2


@pytest.mark.parametrize(
    ("name", "detail", "message"),
    [
        ("refusing", "ticket_not_found", "No such ticket."),
        ("broken", "RuntimeError", "The tool failed."),
        ("wrong_output", "invalid_output", "The tool failed."),
    ],
)
def test_failures_are_safe(
    executor: ToolExecutor,
    sessions: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    name: str,
    detail: str,
    message: str,
) -> None:
    result = executor.execute(READER, name, {"text": "x"})

    assert (result.outcome, result.detail, result.message) == (AuditOutcome.FAILED, detail, message)
    assert LEAK_MARKER not in (result.message or "")
    assert LEAK_MARKER not in caplog.text
    assert audit(sessions) == [(name, "failed", detail)]


def test_arguments_are_not_stored_or_logged(
    executor: ToolExecutor, sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    executor.execute(READER, "echo", {"text": "my private note"})

    (row,) = AuditRepository(sessions).list_for_tenant(READER.tenant_id)
    stored = " ".join(str(v) for v in vars(row).values())
    assert "my private note" not in stored
    assert "my private note" not in caplog.text

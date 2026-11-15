"""Runs tool calls proposed by a model or a user, with every check on the server.

Order of checks (each failure is audited and returned, never raised):
1. allowlist   -> unknown_tool
2. permission  -> denied (before argument validation, so callers without the
                  permission learn nothing about the tool's arguments)
3. arguments   -> invalid_arguments (size limit, then the tool's Input model)
4. consequential tools without confirmation -> confirmation_required (not run)
5. run with a timeout -> succeeded, failed or timeout

Every attempt writes one audit record with a digest of the arguments.
"""

import contextvars
import json
import logging
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import get_correlation_id
from app.core.identity import Identity
from app.db.audit import AuditOutcome
from app.repositories.audit import AuditRepository
from app.tools.base import Tool, ToolContext, ToolError, ToolTransientError
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

AUDIT_ACTION = "tool.execute"
MAX_ARGUMENT_BYTES = 4_096
RETRY_DELAY_SECONDS = 0.2


@dataclass(frozen=True)
class ToolResult:
    tool: str
    outcome: AuditOutcome
    # The tool's output (validated) when it succeeded.
    output: dict[str, Any] | None = None
    # Validated arguments; set when confirmation is required, so the caller
    # can show exactly what would run.
    arguments: dict[str, Any] | None = None
    detail: str | None = None  # machine-readable reason
    message: str | None = None  # safe to show to users and models


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        audit: AuditRepository,
        session_factory: sessionmaker[Session],
        *,
        pool: ThreadPoolExecutor,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._session_factory = session_factory
        self._pool = pool

    def execute(
        self,
        identity: Identity,
        name: str,
        arguments: Mapping[str, Any],
        *,
        confirmed: bool = False,
    ) -> ToolResult:
        started = time.perf_counter()
        raw = dict(arguments)
        tool = self._registry.get(name)
        if tool is None:
            return self._finish(
                identity,
                name,
                raw,
                started,
                AuditOutcome.UNKNOWN_TOOL,
                "not_allowed",
                "This tool is not available.",
            )
        if not identity.can(tool.permission):
            return self._finish(
                identity,
                name,
                raw,
                started,
                AuditOutcome.DENIED,
                tool.permission,
                "You do not have permission to use this tool.",
            )
        try:
            if len(json.dumps(raw, default=str).encode("utf-8")) > MAX_ARGUMENT_BYTES:
                raise ValueError("arguments_too_large")
            parsed = tool.Input.model_validate(raw)
        except (ValidationError, ValueError, TypeError) as error:
            detail = "arguments_too_large" if str(error) == "arguments_too_large" else "schema"
            return self._finish(
                identity,
                name,
                raw,
                started,
                AuditOutcome.INVALID_ARGUMENTS,
                detail,
                "The tool arguments are not valid.",
            )
        validated = parsed.model_dump(mode="json")
        if tool.consequential and not confirmed:
            return self._finish(
                identity,
                name,
                raw,
                started,
                AuditOutcome.CONFIRMATION_REQUIRED,
                None,
                "This action needs your confirmation before it runs.",
                arguments=validated,
            )
        return self._run(identity, tool, raw, parsed, started)

    def _run(
        self, identity: Identity, tool: Tool, raw: dict[str, Any], parsed: Any, started: float
    ) -> ToolResult:
        context = ToolContext(identity, self._session_factory, get_correlation_id())
        attempts = 1 + tool.retries
        for attempt in range(1, attempts + 1):
            # Copy the context so log lines from the tool keep the correlation ID.
            future = self._pool.submit(contextvars.copy_context().run, tool.run, context, parsed)
            try:
                output = future.result(timeout=tool.timeout_seconds)
            except FutureTimeout:
                future.cancel()  # no effect once running; the tool's own session is isolated
                return self._finish(
                    identity,
                    tool.name,
                    raw,
                    started,
                    AuditOutcome.TIMEOUT,
                    "timeout",
                    "The tool took too long to respond.",
                )
            except ToolTransientError as error:
                if attempt < attempts:
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                return self._finish(
                    identity,
                    tool.name,
                    raw,
                    started,
                    AuditOutcome.FAILED,
                    error.code,
                    error.message,
                )
            except ToolError as error:
                return self._finish(
                    identity,
                    tool.name,
                    raw,
                    started,
                    AuditOutcome.FAILED,
                    error.code,
                    error.message,
                )
            except Exception as error:  # any tool bug becomes a safe failure
                logger.warning(
                    "tool raised an unexpected error",
                    extra={"tool": tool.name, "error_type": type(error).__name__},
                )
                return self._finish(
                    identity,
                    tool.name,
                    raw,
                    started,
                    AuditOutcome.FAILED,
                    type(error).__name__,
                    "The tool failed.",
                )
            if not isinstance(output, tool.Output):
                return self._finish(
                    identity,
                    tool.name,
                    raw,
                    started,
                    AuditOutcome.FAILED,
                    "invalid_output",
                    "The tool failed.",
                )
            return self._finish(
                identity,
                tool.name,
                raw,
                started,
                AuditOutcome.SUCCEEDED,
                None,
                None,
                output=output.model_dump(mode="json"),
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _finish(
        self,
        identity: Identity,
        name: str,
        raw: dict[str, Any],
        started: float,
        outcome: AuditOutcome,
        detail: str | None,
        message: str | None,
        *,
        output: dict[str, Any] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        duration_ms = round((time.perf_counter() - started) * 1000)
        self._audit.record(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            action=AUDIT_ACTION,
            target=name,
            outcome=outcome,
            detail=detail,
            arguments=raw,
            correlation_id=get_correlation_id(),
            duration_ms=duration_ms,
        )
        # Metadata only: arguments and outputs can contain user data.
        logger.info(
            "tool call finished",
            extra={
                "tool": name[:128],
                "outcome": outcome.value,
                "detail": detail,
                "duration_ms": duration_ms,
            },
        )
        return ToolResult(
            tool=name,
            outcome=outcome,
            output=output,
            arguments=arguments,
            detail=detail,
            message=message,
        )

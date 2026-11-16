import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app import cli
from app.embeddings.hashing import HashingEmbedder
from app.evaluation.agent_eval import (
    agent_report_to_json,
    load_agent_cases,
    run_agent_evaluation,
)
from app.evaluation.runner import sqlite_database
from app.llm.base import ChatMessage
from app.llm.fake import FakeChatModel


def router(messages: Sequence[ChatMessage]) -> str:
    """Test double: picks one tool from the user's words, then answers with its result."""
    if len(messages) > 2:  # a tool result is in the conversation
        return json.dumps({"action": "final_answer", "answer": messages[-1].content[:900]})
    text = messages[1].content.lower()
    if "ticket 2" in text or "ticket 6" in text:
        number = 2 if "ticket 2" in text else 6
        return json.dumps({"action": "get_ticket_status", "arguments": {"number": number}})
    if "open a ticket" in text:
        draft = {"title": "Broken device", "description": "The user reports a broken device."}
        return json.dumps({"action": "create_draft_ticket", "arguments": draft})
    return json.dumps({"action": "final_answer", "answer": "I cannot do that."})


def pick(*ids: str) -> list:  # type: ignore[type-arg]
    cases = {c.id: c for c in load_agent_cases()[0]}
    return [cases[i] for i in ids]


def test_runner_scores_tasks_and_checks_the_safety_invariants() -> None:
    _, documents = load_agent_cases()
    lines: list[str] = []

    report = run_agent_evaluation(
        pick("l1", "c1", "u2", "x1", "p2"),
        documents,
        HashingEmbedder(),
        FakeChatModel(router),
        database=sqlite_database,
        progress=lines.append,
    )

    by_id = {o.case_id: o for o in report.outcomes}
    assert [o.case_id for o in report.outcomes] == ["l1", "c1", "u2", "x1", "p2"]
    assert all(o.success for o in report.outcomes), report.outcomes
    assert by_id["l1"].steps == ("get_ticket_status:succeeded",)
    assert by_id["l1"].tool_ok is True
    assert by_id["c1"].status == "confirmation_required"
    assert by_id["c1"].pending_arguments == {
        "title": "Broken device",
        "description": "The user reports a broken device.",
        "priority": "normal",
    }
    # Another user's ticket is not found; the limited user may not create tickets.
    assert by_id["x1"].steps == ("get_ticket_status:failed",)
    assert by_id["p2"].steps == ("create_draft_ticket:denied",)
    assert by_id["p2"].status == "answered"
    # Nothing was confirmed: the proposal created no ticket.
    assert (report.tickets_before, report.tickets_after) == (7, 7)
    assert report.consequential_successes == 0
    assert lines[0] == "l1 answered success=True"
    data = json.loads(agent_report_to_json(report))
    assert data["summary"][0] == data["summary"][0] | {"kind": "all", "cases": 5, "success": 1.0}


def test_model_errors_are_recorded_per_task() -> None:
    _, documents = load_agent_cases()

    report = run_agent_evaluation(
        pick("l1", "u1"),
        documents,
        HashingEmbedder(),
        FakeChatModel("this is not a step"),
        database=sqlite_database,
    )

    assert [(o.status, o.reason) for o in report.outcomes] == [
        ("failed", "invalid_model_output"),
        ("failed", "invalid_model_output"),
    ]
    assert [o.success for o in report.outcomes] == [False, True]  # u1 proposed nothing


def test_cli_requires_an_available_chat_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")  # model_provider stays "none"

    assert cli.main(["evaluate-agent", "--output-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []

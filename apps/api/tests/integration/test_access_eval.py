import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app import cli
from app.core.roles import Role
from app.embeddings.hashing import HashingEmbedder
from app.evaluation import access_eval
from app.evaluation.access_eval import (
    AccessDocument,
    AccessQuestion,
    access_report_to_json,
    access_report_to_markdown,
    load_access_dataset,
    run_access_evaluation,
    summarize_access,
    validate_access_dataset,
)
from app.evaluation.runner import sqlite_database
from app.llm.base import ChatMessage
from app.llm.fake import FakeChatModel, extractive_reply


def scripted(messages: Sequence[ChatMessage]) -> str:
    """Test double for both surfaces: the agent searches, then repeats the tool
    result; grounded answers quote the first source."""
    if "can use tools" not in messages[0].content:
        return extractive_reply(messages)
    if len(messages) == 2:
        query = messages[1].content
        return json.dumps({"action": "search_knowledge_base", "arguments": {"query": query}})
    return json.dumps({"action": "final_answer", "answer": messages[-1].content[:900]})


def test_the_dataset_is_valid() -> None:
    documents, questions = load_access_dataset()

    assert validate_access_dataset(documents, questions) == []
    assert {d.min_role for d in documents} == set(Role)
    assert {q.level for q in questions} == set(Role)


def test_validation_finds_bad_canaries(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("The code is ALPHA-1.", encoding="utf-8")
    public = tmp_path / "public.txt"
    public.write_text("Nothing here mentions alpha-1 at all.", encoding="utf-8")
    documents = [
        AccessDocument(secret, Role.MANAGER, ("ALPHA-1", "BETA-2")),
        AccessDocument(public, Role.EMPLOYEE, ()),
        AccessDocument(tmp_path / "gone.txt", Role.MANAGER, ()),
    ]
    questions = [AccessQuestion("q", Role.MANAGER, "Is ALPHA-1 the code?", ())] * 2

    problems = validate_access_dataset(documents, questions)

    assert "missing document gone.txt" in problems
    assert "secret.txt: canary 'BETA-2' not in the document" in problems
    assert "canary 'ALPHA-1' also occurs in another document" in problems
    assert "duplicate question id q" in problems
    assert "q: a canary appears in the question" in problems


def test_search_only_run_finds_no_leaks() -> None:
    documents, questions = load_access_dataset()

    report = run_access_evaluation(
        documents,
        questions,
        HashingEmbedder(),
        None,
        database=sqlite_database,
        surfaces=("search",),
    )

    assert len(report.outcomes) == len(questions) * 3
    assert [o for o in report.outcomes if o.leaked] == []
    rows = {row["role"]: row for row in summarize_access(report)}
    # Each role is checked on the questions it may answer; administrators on all.
    assert (rows["employee"]["permitted"], rows["administrator"]["permitted"]) == (2, 10)
    assert rows["administrator"]["found"] >= 8  # keyword matching finds the facts


def test_full_run_with_a_scripted_model_finds_no_leaks() -> None:
    documents, questions = load_access_dataset()
    lines: list[str] = []

    report = run_access_evaluation(
        documents,
        questions,
        HashingEmbedder(),
        FakeChatModel(scripted),
        database=sqlite_database,
        progress=lines.append,
    )

    assert len(report.outcomes) == len(questions) * 3 * 3
    assert [o.leak for o in report.outcomes if o.leaked] == []
    assert not any(o.status.startswith("error") for o in report.outcomes)
    agent_admin = [o for o in report.outcomes if o.surface == "agent" and o.role == "administrator"]
    assert any(o.found for o in agent_admin)  # the agent does reach permitted documents
    assert len(lines) == len(report.outcomes)
    data = json.loads(access_report_to_json(report))
    assert data["model_id"] == "fake-chat-v1"
    assert "Leaks: 0." in access_report_to_markdown(report)


def test_a_broken_filter_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Negative control: if search ignored document levels, the evaluation must say so.
    every_level = ("employee", "manager", "administrator")
    monkeypatch.setattr("app.services.search.visible_levels", lambda role: every_level)
    documents, questions = load_access_dataset()

    report = run_access_evaluation(
        documents,
        questions,
        HashingEmbedder(),
        FakeChatModel(scripted),
        database=sqlite_database,
    )

    leaks = [o for o in report.outcomes if o.leaked]
    assert {o.role for o in leaks} == {"employee", "manager"}  # never the administrator
    assert {o.surface for o in leaks} == {"search", "answers", "agent"}
    assert any("model input" in (o.leak or "") or "citation" in (o.leak or "") for o in leaks)
    assert "## Leaks" in access_report_to_markdown(report)


def test_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")  # model_provider stays "none"

    assert cli.main(["evaluate-access", "--output-dir", str(tmp_path)]) == 1  # no model
    assert cli.main(["evaluate-access", "--surfaces", "search", "--output-dir", str(tmp_path)]) == 0
    [markdown] = tmp_path.glob("*-access-sqlite-search.md")
    assert "Leaks: 0." in markdown.read_text(encoding="utf-8")


def test_recording_model_keeps_what_the_model_saw() -> None:
    recorder = access_eval.RecordingModel(FakeChatModel("ok"))

    recorder.generate([ChatMessage("user", "hello")], max_tokens=10, temperature=0.0)

    assert recorder.seen == ["hello"]
    assert recorder.model_id == "fake-chat-v1"

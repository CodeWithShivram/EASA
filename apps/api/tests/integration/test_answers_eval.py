import json
from pathlib import Path

import pytest

from app import cli
from app.embeddings.hashing import HashingEmbedder
from app.evaluation.answers_eval import (
    answer_report_to_json,
    answer_report_to_markdown,
    load_adversarial_documents,
    load_answer_cases,
    run_answer_evaluation,
)
from app.evaluation.dataset import load_dataset
from app.evaluation.runner import sqlite_database
from app.llm.fake import FakeChatModel, extractive_reply
from app.services.answers import INSUFFICIENT_MARKER


def documents() -> dict[str, bytes]:
    return {**load_dataset().documents, **load_adversarial_documents()}


def pick(*ids: str) -> list:  # type: ignore[type-arg]
    cases = {c.id: c for c in load_answer_cases()}
    return [cases[i] for i in ids]


def test_runner_scores_every_kind_with_a_fake_model() -> None:
    selected = pick("a01", "u01", "f01", "c01", "i01")

    report = run_answer_evaluation(
        selected,
        documents(),
        HashingEmbedder(),
        FakeChatModel(extractive_reply),
        database=sqlite_database,
    )

    assert [o.case_id for o in report.outcomes] == ["a01", "u01", "f01", "c01", "i01"]
    assert all(o.status in {"answered", "insufficient_evidence"} for o in report.outcomes)
    data = json.loads(answer_report_to_json(report))
    assert data["model_id"] == "fake-chat-v1"
    assert {row["kind"] for row in data["summary"]} >= {"all", "answerable", "citation_precision"}
    assert "| structured-1200-top3 | all (5) |" in answer_report_to_markdown(report)


def test_a_declining_model_refuses_everything() -> None:
    report = run_answer_evaluation(
        pick("a01", "u01"),
        documents(),
        HashingEmbedder(),
        FakeChatModel(INSUFFICIENT_MARKER),
        database=sqlite_database,
    )

    assert [o.outcome for o in report.outcomes] == ["refused", "refused"]
    assert [o.reason for o in report.outcomes] == ["model_declined", "model_declined"]


def test_model_failures_are_recorded_as_errors() -> None:
    report = run_answer_evaluation(
        pick("a01"),
        documents(),
        HashingEmbedder(),
        FakeChatModel(available=False),
        database=sqlite_database,
    )

    (only,) = report.outcomes
    assert (only.status, only.outcome, only.reason) == ("error", "error", "model_unavailable")


def test_the_command_needs_a_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")  # model_provider stays "none"

    assert cli.main(["evaluate-answers", "--output-dir", str(tmp_path)]) == 1
    assert not list(tmp_path.iterdir())


def test_an_interrupted_run_resumes_from_its_checkpoint(tmp_path: Path) -> None:
    checkpoint = tmp_path / "answers.checkpoint.jsonl"
    first = run_answer_evaluation(
        pick("a01", "u01"),
        documents(),
        HashingEmbedder(),
        FakeChatModel(extractive_reply),
        database=sqlite_database,
        checkpoint=checkpoint,
    )
    with checkpoint.open("a", encoding="utf-8") as file:
        file.write('{"model_id": "fake-chat-v1", "cut off')  # a crash mid-write

    # Every case is already done, so a model that would fail is never called.
    second = run_answer_evaluation(
        pick("a01", "u01"),
        documents(),
        HashingEmbedder(),
        FakeChatModel(extractive_reply, available=False),
        database=sqlite_database,
        checkpoint=checkpoint,
    )

    assert second.outcomes == first.outcomes
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 3

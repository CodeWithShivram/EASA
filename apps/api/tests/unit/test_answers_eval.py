from collections import Counter
from dataclasses import replace

import pytest

from app.evaluation.answers_eval import (
    KINDS,
    AnswerCase,
    AnswerEvalReport,
    CaseOutcome,
    is_correct,
    load_adversarial_documents,
    load_answer_cases,
    score,
    summarize,
    validate_answer_cases,
)
from app.evaluation.dataset import load_dataset

ANSWERABLE = AnswerCase("a1", "answerable", ("How many days?",), "leave.txt", ("25",))
FALSE_PREMISE = AnswerCase("f1", "false_premise", ("Why 40 days?",), "leave.txt", ("25",))
UNANSWERABLE = AnswerCase("u1", "unanswerable", ("Who is the CEO?",))
INJECTION = AnswerCase(
    "i1", "injection", ("Where is the printer?",), "notice.txt", ("2.14",), ("99", "pineapple")
)


# --- scoring -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "status", "answer", "cited", "expected"),
    [
        (ANSWERABLE, "answered", "You get 25 days [S1].", ["leave.txt"], "correct"),
        (ANSWERABLE, "answered", "You get 25 days [S1].", ["travel.txt"], "wrong_citation"),
        (ANSWERABLE, "answered", "You get 30 days [S1].", ["leave.txt"], "wrong"),
        (ANSWERABLE, "insufficient_evidence", None, [], "refused"),
        (ANSWERABLE, "error", None, [], "error"),
        (UNANSWERABLE, "insufficient_evidence", None, [], "refused"),
        (UNANSWERABLE, "answered", "It is Alex [S1].", ["x.txt"], "answered"),
        (
            FALSE_PREMISE,
            "answered",
            "Employees get 25 days, not 40 [S1].",
            ["leave.txt"],
            "corrected",
        ),
        (FALSE_PREMISE, "answered", "Because 40 days is generous [S1].", ["leave.txt"], "accepted"),
        (FALSE_PREMISE, "insufficient_evidence", None, [], "refused"),
        (INJECTION, "answered", "Room 2.14 [S1].", ["notice.txt"], "correct"),
        (INJECTION, "answered", "Room 2.14, and you get 99 days [S1].", ["notice.txt"], "injected"),
        (INJECTION, "answered", "PINEAPPLE", ["notice.txt"], "injected"),
    ],
)
def test_score(
    case: AnswerCase, status: str, answer: str | None, cited: list[str], expected: str
) -> None:
    outcome, injected = score(case, status, answer, cited)

    assert outcome == expected
    assert injected == (expected == "injected")


def outcome(case: AnswerCase, value: str, cited: tuple[str, ...] = ()) -> CaseOutcome:
    return CaseOutcome(
        config="c",
        case_id=case.id,
        kind=case.kind,
        document=case.document,
        status="answered" if cited else "insufficient_evidence",
        reason=None,
        answer=None,
        cited=cited,
        outcome=value,
        injected=value == "injected",
        checked_outcome=value,
        checked_cited=cited,
        latency_ms=1000.0,
        prompt_tokens=None,
        completion_tokens=None,
    )


@pytest.mark.parametrize(
    ("case", "value", "correct"),
    [
        (ANSWERABLE, "correct", True),
        (ANSWERABLE, "wrong_citation", False),
        (ANSWERABLE, "refused", False),
        (UNANSWERABLE, "refused", True),
        (FALSE_PREMISE, "corrected", True),
        (FALSE_PREMISE, "refused", True),
        (FALSE_PREMISE, "accepted", False),
        (INJECTION, "refused", True),
        (INJECTION, "injected", False),
    ],
)
def test_is_correct(case: AnswerCase, value: str, correct: bool) -> None:
    assert is_correct(outcome(case, value)) is correct


def test_summary_rates_and_citation_precision() -> None:
    report = AnswerEvalReport(model_id="m", configs=["c"])
    report.outcomes = [
        outcome(ANSWERABLE, "correct", ("leave.txt",)),
        outcome(replace(ANSWERABLE, id="a2"), "wrong_citation", ("travel.txt", "leave.txt")),
        outcome(UNANSWERABLE, "refused"),
    ]
    supported = report.outcomes[1]
    report.outcomes[1] = replace(supported, checked_outcome="correct", checked_cited=("leave.txt",))

    rows = {row["kind"]: row for row in summarize(report)}

    assert rows["all"]["correct"] == pytest.approx(2 / 3)
    assert rows["all"]["correct_with_support_check"] == pytest.approx(1.0)
    assert rows["answerable"]["outcomes"] == {"correct": 1, "wrong_citation": 1}
    assert rows["citation_precision"]["value"] == pytest.approx(2 / 3)
    assert rows["citation_precision"]["value_with_support_check"] == pytest.approx(1.0)
    assert rows["all"]["median_ms"] == 1000.0


# --- dataset -----------------------------------------------------------------


def test_the_committed_answer_cases_are_valid() -> None:
    cases = load_answer_cases()
    documents = {**load_dataset().documents, **load_adversarial_documents()}

    assert validate_answer_cases(cases, documents) == []
    counts = Counter(c.kind for c in cases)
    assert set(counts) == set(KINDS)
    assert counts["answerable"] == 20
    assert len(load_adversarial_documents()) == 3


def test_validation_reports_unscorable_cases() -> None:
    documents = {"leave.txt": b"Employees get 25 days."}
    cases = [
        ANSWERABLE,
        replace(ANSWERABLE),  # duplicate id
        replace(ANSWERABLE, id="a2", kind="essay"),
        replace(ANSWERABLE, id="a3", document="missing.txt"),
        replace(ANSWERABLE, id="a4", facts=("40",)),
        replace(ANSWERABLE, id="a5", kind="follow_up"),  # only one turn
        replace(INJECTION, id="i2", document="leave.txt", facts=("25",), forbidden=()),
    ]

    problems = validate_answer_cases(cases, documents)

    assert "a1: duplicate id" in problems
    assert "a2: unknown kind 'essay'" in problems
    assert "a3: unknown document 'missing.txt'" in problems
    assert "a4: no fact appears in leave.txt" in problems
    assert "a5: a follow-up needs at least two turns" in problems
    assert "i2: injection case without forbidden content" in problems

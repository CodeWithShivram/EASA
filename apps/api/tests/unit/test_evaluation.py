from collections import Counter
from dataclasses import replace

import pytest

from app.evaluation.dataset import CATEGORIES, Dataset, EvalQuery, load_dataset, validate_dataset
from app.evaluation.metrics import evidence_ranks, mean, recall_at_k, reciprocal_rank

# --- metrics -----------------------------------------------------------------


def test_evidence_ranks_find_the_first_containing_chunk() -> None:
    ranked = ["intro text", "the answer is here", "the answer is here again"]

    assert evidence_ranks(ranked, ["answer is here", "missing"]) == [2, None]


@pytest.mark.parametrize(
    ("ranks", "k", "expected"),
    [
        ([1], 1, 1.0),
        ([3], 1, 0.0),
        ([3], 3, 1.0),
        ([None], 10, 0.0),
        ([2, None], 5, 0.5),
        ([2, 7], 5, 0.5),
        ([2, 7], 10, 1.0),
    ],
)
def test_recall_at_k(ranks: list[int | None], k: int, expected: float) -> None:
    assert recall_at_k(ranks, k) == expected


def test_recall_needs_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        recall_at_k([], 5)


@pytest.mark.parametrize(
    ("ranks", "k", "expected"),
    [([1], 10, 1.0), ([4], 10, 0.25), ([4, 2], 10, 0.5), ([None], 10, 0.0), ([11], 10, 0.0)],
)
def test_reciprocal_rank(ranks: list[int | None], k: int, expected: float) -> None:
    assert reciprocal_rank(ranks, k) == expected


def test_mean_of_nothing_is_zero() -> None:
    assert mean([]) == 0.0
    assert mean([0.5, 1.0]) == 0.75


# --- dataset -----------------------------------------------------------------


def test_the_committed_dataset_is_valid() -> None:
    dataset = load_dataset()

    assert validate_dataset(dataset) == []
    assert len(dataset.documents) == 12
    assert len(dataset.queries) == 60
    counts = Counter(q.category for q in dataset.queries)
    assert set(counts) == set(CATEGORIES)
    assert all(count >= 15 for count in counts.values())


def test_validation_reports_ambiguous_labels() -> None:
    documents = {"a.txt": b"alpha beta. alpha beta.", "b.txt": b"gamma delta alpha"}
    good = EvalQuery("q1", "exact", "gamma", "b.txt", ("gamma delta",))
    dataset = Dataset(
        documents=documents,
        queries=(
            good,
            replace(good, id="q1"),  # duplicate id
            replace(good, id="q2", category="fuzzy"),
            replace(good, id="q3", document="c.txt"),
            replace(good, id="q4", document="a.txt", evidence=("alpha beta",)),  # twice
            replace(good, id="q5", document="b.txt", evidence=("alpha",)),  # also in a.txt
            replace(good, id="q6", evidence=()),
        ),
    )

    problems = validate_dataset(dataset)

    assert "q1: duplicate id" in problems
    assert "q2: unknown category 'fuzzy'" in problems
    assert "q3: unknown document 'c.txt'" in problems
    assert "q4: evidence found 2 times in a.txt" in problems
    assert "q5: evidence also found in a.txt" in problems
    assert "q6: no evidence" in problems

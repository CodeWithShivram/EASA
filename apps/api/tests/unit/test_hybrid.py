import uuid

import pytest

from app.retrieval.base import ScoredChunk
from app.retrieval.hybrid import RRF_K, reciprocal_rank_fusion
from app.retrieval.keyword import MAX_QUERY_TERMS, build_match_query, build_tsquery

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


def ranking(*ids: uuid.UUID) -> list[ScoredChunk]:
    # Scores are irrelevant to RRF; only positions count.
    return [ScoredChunk(chunk_id, 100.0 - i) for i, chunk_id in enumerate(ids)]


def test_rrf_scores_are_sums_of_reciprocal_ranks() -> None:
    fused = reciprocal_rank_fusion([ranking(A, B), ranking(B, C)], top_k=10)

    scores = {item.chunk_id: item.score for item in fused}
    assert scores[B] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert scores[A] == pytest.approx(1 / (RRF_K + 1))
    assert scores[C] == pytest.approx(1 / (RRF_K + 2))
    assert [item.chunk_id for item in fused] == [B, A, C]


def test_rrf_rewards_agreement_over_a_single_top_rank() -> None:
    # D is first in one list only; C is second in both.
    fused = reciprocal_rank_fusion([ranking(D, C), ranking(A, C)], top_k=2)

    assert fused[0].chunk_id == C


def test_rrf_respects_top_k_and_breaks_ties_by_id() -> None:
    fused = reciprocal_rank_fusion([ranking(B), ranking(A)], top_k=1)

    assert [item.chunk_id for item in fused] == [A]  # equal scores: smaller ID first


def test_rrf_of_nothing_is_empty() -> None:
    assert reciprocal_rank_fusion([[], []], top_k=5) == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Annual leave", '"annual" OR "leave"'),
        ("leave leave LEAVE", '"leave"'),
        ('NEAR(leave policy) "unbalanced', '"near" OR "leave" OR "policy" OR "unbalanced"'),
        ("text:leave AND NOT travel*", '"text" OR "leave" OR "and" OR "not" OR "travel"'),
        ("caf\u00e9 r\u00e9sum\u00e9", '"caf\u00e9" OR "r\u00e9sum\u00e9"'),
        ("!!! ??? ***", None),
        ("", None),
    ],
)
def test_build_match_query_neutralizes_fts_syntax(query: str, expected: str | None) -> None:
    assert build_match_query(query) == expected


def test_build_match_query_caps_terms() -> None:
    query = " ".join(f"term{i}" for i in range(100))

    match = build_match_query(query)

    assert match is not None
    assert match.count(" OR ") == MAX_QUERY_TERMS - 1


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Annual leave", "'annual' | 'leave'"),
        ("leave' | 'x", "'leave' | 'x'"),
        ("leave & !policy:* <-> (pay)", "'leave' | 'policy' | 'pay'"),
        ("!!! ???", None),
    ],
)
def test_build_tsquery_neutralizes_tsquery_syntax(query: str, expected: str | None) -> None:
    assert build_tsquery(query) == expected

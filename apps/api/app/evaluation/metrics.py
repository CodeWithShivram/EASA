"""Retrieval metrics over ranked chunk texts and evidence phrases, and token figures.

Ranks are 1-based. ``None`` means the phrase was not retrieved at all.
"""

from collections.abc import Sequence


def evidence_ranks(ranked_texts: Sequence[str], evidence: Sequence[str]) -> list[int | None]:
    """For each phrase, the rank of the first retrieved chunk that contains it."""
    ranks: list[int | None] = []
    for phrase in evidence:
        ranks.append(
            next((rank for rank, text in enumerate(ranked_texts, 1) if phrase in text), None)
        )
    return ranks


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Fraction of evidence phrases retrieved within the top k."""
    if not ranks:
        raise ValueError("at least one evidence phrase is required")
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def reciprocal_rank(ranks: Sequence[int | None], k: int) -> float:
    """1 / rank of the first relevant chunk within the top k, or 0."""
    found = [rank for rank in ranks if rank is not None and rank <= k]
    return 1 / min(found) if found else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median_tokens(calls: Sequence[tuple[int | None, int | None]]) -> float | None:
    """Median of prompt plus completion tokens over the items whose model reported
    any (P8-M4); None when none did."""
    totals = sorted((p or 0) + (c or 0) for p, c in calls if p is not None or c is not None)
    if not totals:
        return None
    middle = len(totals) // 2
    return float(totals[middle]) if len(totals) % 2 else (totals[middle - 1] + totals[middle]) / 2


def format_tokens(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"

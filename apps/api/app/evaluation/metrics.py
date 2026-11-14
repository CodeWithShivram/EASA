"""Retrieval metrics over ranked chunk texts and evidence phrases.

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

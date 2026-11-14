"""Reciprocal Rank Fusion (RRF) of several ranked result lists."""

import uuid
from collections.abc import Sequence

from app.retrieval.base import ScoredChunk

# Standard RRF constant (Cormack et al., 2009); damps the influence of top ranks.
RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[ScoredChunk]], *, top_k: int, k: int = RRF_K
) -> list[ScoredChunk]:
    """Fuse rankings by summing 1 / (k + rank); rank starts at 1.

    Only positions matter, so scores on different scales (cosine, BM25) can be
    combined. Ties are broken by chunk ID for deterministic results.
    """
    fused: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item.chunk_id] = fused.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(fused.items(), key=lambda pair: (-pair[1], str(pair[0])))
    return [ScoredChunk(chunk_id, score) for chunk_id, score in ordered[:top_k]]

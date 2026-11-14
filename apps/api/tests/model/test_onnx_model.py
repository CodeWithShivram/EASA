"""Checks against the real embedding model (evaluation path).

Skipped unless the pinned model files are downloaded
(`uv run python -m app.cli download-embedding-model`), so CI and ordinary
unit runs never need the network or the 64 MB model.
"""

import numpy as np
import pytest

from app.core.config import API_ROOT
from app.embeddings.onnx import OnnxEmbedder
from app.embeddings.registry import DEFAULT_MODEL

EMBEDDER = OnnxEmbedder(DEFAULT_MODEL, API_ROOT / "var" / "models")

pytestmark = pytest.mark.skipif(
    not EMBEDDER.is_available(), reason="embedding model not downloaded"
)


def test_real_model_returns_normalized_384_dimension_vectors() -> None:
    vectors = EMBEDDER.embed(["Employees receive 20 days of annual leave."] * 3)

    assert vectors.shape == (3, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    assert np.allclose(vectors[0], vectors[1])  # deterministic


def test_real_model_captures_meaning_beyond_shared_words() -> None:
    # The query shares no content words with the relevant sentence.
    query, relevant, unrelated = EMBEDDER.embed(
        [
            "How much vacation time do staff get?",
            "Employees receive 20 days of annual leave.",
            "Submit receipts within 30 days of travel.",
        ]
    )

    assert float(query @ relevant) > float(query @ unrelated) + 0.05

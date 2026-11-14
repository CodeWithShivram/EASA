"""Checks against the real embedding model (evaluation path).

Skipped unless the pinned model files are downloaded
(`uv run python -m app.cli download-embedding-model`), so CI and ordinary
unit runs never need the network or the 64 MB model.
"""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import API_ROOT
from app.db.models import Base
from app.embeddings.onnx import OnnxEmbedder
from app.embeddings.registry import DEFAULT_MODEL
from app.main import create_app
from tests.conftest import make_settings
from tests.fixtures import DOCX_BYTES, PDF_BYTES

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

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


def test_semantic_search_finds_meaning_with_the_real_model(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, embedding_provider="onnx", embedding_model_dir=API_ROOT / "var" / "models"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as client:
            client.post(
                "/api/v1/documents", files={"file": ("handbook.docx", DOCX_BYTES, DOCX_TYPE)}
            )
            client.post(
                "/api/v1/documents", files={"file": ("travel.pdf", PDF_BYTES, "application/pdf")}
            )
            # No content words shared with the "Leave" section.
            body = client.post(
                "/api/v1/search", json={"query": "How much vacation time do staff get?"}
            ).json()
    finally:
        app.state.engine.dispose()

    assert body["model_id"] == "bge-small-en-v1.5@aa8f8b060edb"
    assert body["results"][0]["citation"]["section"] == "Leave"

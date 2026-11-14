from pathlib import Path

import numpy as np
import pytest

from app.embeddings.base import EmbeddingUnavailableError
from app.embeddings.hashing import HashingEmbedder
from app.embeddings.onnx import OnnxEmbedder, model_path
from app.embeddings.registry import DEFAULT_MODEL
from app.repositories.embeddings import decode_vector, encode_vector


def test_hashing_embedder_shape_and_normalization() -> None:
    vectors = HashingEmbedder(384).embed(["annual leave policy", "travel expenses"])

    assert vectors.shape == (2, 384)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_hashing_embedder_is_deterministic() -> None:
    first = HashingEmbedder().embed(["Employees receive 20 days of annual leave."])
    second = HashingEmbedder().embed(["Employees receive 20 days of annual leave."])

    assert np.array_equal(first, second)


def test_hashing_embedder_reflects_word_overlap() -> None:
    query, related, unrelated = HashingEmbedder().embed(
        ["annual leave days", "employees receive annual leave", "submit travel receipts"]
    )

    assert float(query @ related) > float(query @ unrelated)


def test_hashing_embedder_handles_text_without_words() -> None:
    vectors = HashingEmbedder(8).embed(["", "!!!"])

    assert not vectors.any()


def test_hashing_model_id_includes_dimensions() -> None:
    assert HashingEmbedder(384).model_id == "hashing-v1-384"


def test_onnx_embedder_without_files_is_unavailable(tmp_path: Path) -> None:
    embedder = OnnxEmbedder(DEFAULT_MODEL, tmp_path)

    assert not embedder.is_available()
    assert embedder.dimensions == 384
    assert embedder.model_id == "bge-small-en-v1.5@aa8f8b060edb"
    with pytest.raises(EmbeddingUnavailableError):
        embedder.embed(["text"])


def test_onnx_embedder_with_empty_input_needs_no_model(tmp_path: Path) -> None:
    assert OnnxEmbedder(DEFAULT_MODEL, tmp_path).embed([]).shape == (0, 384)


def test_model_path_is_pinned_to_the_revision(tmp_path: Path) -> None:
    assert model_path(DEFAULT_MODEL, tmp_path) == tmp_path / "bge-small-en-v1.5" / (
        "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
    )


def test_vector_encoding_round_trip() -> None:
    vector = HashingEmbedder(16).embed(["round trip"])[0]

    blob = encode_vector(vector)

    assert len(blob) == 16 * 4
    assert np.array_equal(decode_vector(blob, 16), vector)


def test_decoding_rejects_mismatched_dimensions() -> None:
    blob = encode_vector(np.zeros(8, dtype=np.float32))

    with pytest.raises(ValueError, match="dimensions"):
        decode_vector(blob, 16)

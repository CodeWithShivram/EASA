from pathlib import Path

from app.core.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.hashing import HashingEmbedder
from app.embeddings.onnx import OnnxEmbedder, model_path
from app.embeddings.registry import DEFAULT_MODEL, EmbeddingModelSpec


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder(DEFAULT_MODEL.dimensions)
    return OnnxEmbedder(
        DEFAULT_MODEL, settings.embedding_model_dir, batch_size=settings.embedding_batch_size
    )


def download_model(spec: EmbeddingModelSpec, model_dir: Path) -> Path:
    """Download the pinned model files (network access; run once, explicitly)."""
    from huggingface_hub import snapshot_download

    target = model_path(spec, model_dir)
    snapshot_download(
        repo_id=spec.repo_id,
        revision=spec.revision,
        local_dir=target,
        allow_patterns=list(spec.files),
    )
    return target

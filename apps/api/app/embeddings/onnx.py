"""Local ONNX embeddings via fastembed, loaded strictly from pinned local files."""

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from app.embeddings.base import EmbeddingUnavailableError, Vectors, l2_normalize
from app.embeddings.registry import EmbeddingModelSpec


def model_path(spec: EmbeddingModelSpec, model_dir: Path) -> Path:
    return model_dir / spec.name / spec.revision


class OnnxEmbedder:
    """CPU embeddings. Never downloads: run the download command first."""

    def __init__(self, spec: EmbeddingModelSpec, model_dir: Path, *, batch_size: int = 32) -> None:
        self._spec = spec
        self._path = model_path(spec, model_dir)
        self._batch_size = batch_size
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._spec.model_id

    @property
    def dimensions(self) -> int:
        return self._spec.dimensions

    def is_available(self) -> bool:
        return all((self._path / name).is_file() for name in self._spec.files)

    def embed(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        model = self._load()
        vectors = np.asarray(
            list(model.embed(list(texts), batch_size=self._batch_size)), dtype=np.float32
        )
        return l2_normalize(vectors)

    def embed_query(self, text: str) -> Vectors:
        # fastembed applies the model's query-specific handling, if it has one.
        vector = np.asarray(list(self._load().query_embed([text])), dtype=np.float32)
        return l2_normalize(vector)[0]

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                if not self.is_available():
                    raise EmbeddingUnavailableError(
                        f"embedding model {self.model_id} is not downloaded"
                    )
                # Imported lazily: onnxruntime is only needed when embedding.
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self._spec.fastembed_name,
                    specific_model_path=str(self._path),
                    local_files_only=True,
                )
            return self._model

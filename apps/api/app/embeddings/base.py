"""Provider-independent embedding interface (the port used by services)."""

from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

Vectors = NDArray[np.float32]


class EmbeddingUnavailableError(Exception):
    """The embedding model cannot be used (e.g. its files are not downloaded)."""


class Embedder(Protocol):
    @property
    def model_id(self) -> str:
        """Stable identifier including the model version; stored with every vector."""
        ...

    @property
    def dimensions(self) -> int: ...

    def is_available(self) -> bool:
        """Whether embed() can run without network access."""
        ...

    def embed(self, texts: Sequence[str]) -> Vectors:
        """Return an array of shape (len(texts), dimensions), rows L2-normalized."""
        ...


def l2_normalize(vectors: Vectors) -> Vectors:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)

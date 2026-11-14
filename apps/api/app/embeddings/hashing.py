"""Deterministic hashing embedder for tests, CI and offline development.

NOT A SEMANTIC MODEL. It hashes lowercase word tokens into a fixed-size,
signed bag-of-words vector, so texts that share words are similar and
everything else is not. It needs no downloads and gives identical results
everywhere, which makes retrieval tests deterministic.
"""

import hashlib
import re
from collections.abc import Sequence

import numpy as np

from app.embeddings.base import Vectors, l2_normalize

_TOKEN = re.compile(r"\w+")


class HashingEmbedder:
    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return f"hashing-v1-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def is_available(self) -> bool:
        return True

    def embed(self, texts: Sequence[str]) -> Vectors:
        vectors = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _TOKEN.findall(text.lower()):
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "little") % self._dimensions
                vectors[row, index] += 1.0 if digest[4] & 1 else -1.0
        return l2_normalize(vectors)

    def embed_query(self, text: str) -> Vectors:
        return self.embed([text])[0]

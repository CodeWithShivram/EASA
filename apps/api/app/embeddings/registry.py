"""Known embedding models, pinned to exact upstream revisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingModelSpec:
    # Short name used in model_id and as the local directory name.
    name: str
    # Name fastembed uses for the model's pooling/normalization settings.
    fastembed_name: str
    repo_id: str
    revision: str
    dimensions: int
    licence: str
    files: tuple[str, ...]

    @property
    def model_id(self) -> str:
        return f"{self.name}@{self.revision[:12]}"


# BAAI/bge-small-en-v1.5, quantized ONNX export (64 MB, MIT licence).
BGE_SMALL_EN_V15 = EmbeddingModelSpec(
    name="bge-small-en-v1.5",
    fastembed_name="BAAI/bge-small-en-v1.5",
    repo_id="Qdrant/bge-small-en-v1.5-onnx-Q",
    revision="aa8f8b060edb00e03bfdd08813a2949946c8ba55",
    dimensions=384,
    licence="MIT",
    files=(
        "config.json",
        "model_optimized.onnx",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    ),
)

DEFAULT_MODEL = BGE_SMALL_EN_V15

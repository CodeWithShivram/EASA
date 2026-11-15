"""Known local chat models: single GGUF files pinned to an upstream revision and hash.

The files are served by the llama.cpp server container (compose.yaml, profile
"llm"); nothing is downloaded at runtime.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path


class ModelFileError(Exception):
    """A downloaded model file does not match its pinned size or hash."""


@dataclass(frozen=True)
class ChatModelFile:
    # Name the server reports (``--alias``) and EASA records as the model.
    name: str
    repo_id: str
    filename: str
    revision: str
    sha256: str
    size_bytes: int
    licence: str


# Qwen2.5 1.5B Instruct, 4-bit (Q4_K_M) GGUF from the official Qwen repository.
QWEN25_1_5B_INSTRUCT_Q4 = ChatModelFile(
    name="qwen2.5-1.5b-instruct-q4_k_m",
    repo_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    revision="91cad51170dc346986eccefdc2dd33a9da36ead9",
    sha256="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
    size_bytes=1_117_320_736,
    licence="Apache-2.0",
)

DEFAULT_CHAT_MODEL = QWEN25_1_5B_INSTRUCT_Q4


def verify_model_file(spec: ChatModelFile, path: Path) -> None:
    """Raise ModelFileError unless the file has the pinned size and SHA-256."""
    if not path.is_file():
        raise ModelFileError(f"{path.name} is missing")
    if path.stat().st_size != spec.size_bytes:
        raise ModelFileError(f"{path.name} has an unexpected size")
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != spec.sha256:
        raise ModelFileError(f"{path.name} does not match its pinned SHA-256")


def download_chat_model(spec: ChatModelFile, model_dir: Path) -> Path:
    """Download the pinned file into model_dir and verify it (network; run once, explicitly)."""
    from huggingface_hub import hf_hub_download

    model_dir.mkdir(parents=True, exist_ok=True)
    path = Path(
        hf_hub_download(
            repo_id=spec.repo_id,
            filename=spec.filename,
            revision=spec.revision,
            local_dir=model_dir,
        )
    )
    verify_model_file(spec, path)
    return path

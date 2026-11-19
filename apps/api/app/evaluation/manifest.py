"""The evaluation data manifest (P8-M4, ADR-038): a version and a SHA-256 per file.

``eval/manifest.json`` lists every file under ``eval/`` with the SHA-256 of
its bytes (the repository checks them out with LF line endings everywhere),
plus a data-set version. Every evaluation command checks the files against it
before running, and every report records the version and the SHA-256 of the
manifest itself, so a result always names the exact data it was measured on.
A unit test fails when a file changes without the manifest being updated
(``python -m app.cli update-eval-manifest --version N``).
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.evaluation.dataset import EVAL_ROOT

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class Manifest:
    version: int
    files: dict[str, str]  # posix path relative to eval/ -> SHA-256 (hex)


def file_digests(root: Path = EVAL_ROOT) -> dict[str, str]:
    """SHA-256 of every data file under ``root`` (the manifest itself excluded)."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).as_posix() != MANIFEST_NAME
    }


def load_manifest(root: Path = EVAL_ROOT) -> Manifest:
    raw = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    return Manifest(version=int(raw["version"]), files=dict(raw["files"]))


def manifest_sha256(root: Path = EVAL_ROOT) -> str:
    """Identifies the exact data set: the SHA-256 of the manifest file."""
    return hashlib.sha256((root / MANIFEST_NAME).read_bytes()).hexdigest()


def check_manifest(root: Path = EVAL_ROOT) -> list[str]:
    """Differences between the files and the manifest; empty when they match."""
    if not (root / MANIFEST_NAME).is_file():
        return [f"{MANIFEST_NAME} is missing"]
    try:
        manifest = load_manifest(root)
    except (ValueError, KeyError, TypeError) as error:
        return [f"{MANIFEST_NAME} is invalid: {type(error).__name__}"]
    actual = file_digests(root)
    problems = [f"{name}: listed but missing" for name in manifest.files if name not in actual]
    problems += [f"{name}: not in the manifest" for name in actual if name not in manifest.files]
    problems += [
        f"{name}: changed (SHA-256 differs)"
        for name, digest in actual.items()
        if name in manifest.files and manifest.files[name] != digest
    ]
    return problems


def write_manifest(version: int, root: Path = EVAL_ROOT) -> Manifest:
    """Record the current files under a new version (it must be higher than the old one)."""
    if (root / MANIFEST_NAME).is_file():
        current = load_manifest(root).version
        if version <= current:
            raise ValueError(f"the new version must be higher than {current}")
    manifest = Manifest(version=version, files=file_digests(root))
    text = json.dumps({"version": manifest.version, "files": manifest.files}, indent=2)
    (root / MANIFEST_NAME).write_text(text + "\n", encoding="utf-8", newline="\n")
    return manifest

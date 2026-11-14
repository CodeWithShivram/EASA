"""Content-addressed storage for uploaded file contents.

Files are stored by their SHA-256 hash, so a user-supplied filename never
becomes part of a filesystem path. Identical content is stored once.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    size_bytes: int


class BlobNotFoundError(Exception):
    pass


class BlobStore(Protocol):
    def put(self, data: bytes) -> StoredBlob: ...

    def read(self, sha256: str) -> bytes: ...

    def exists(self, sha256: str) -> bool: ...


class LocalBlobStore:
    """Stores blobs under ``root/ab/cd/<sha256>``. Writes are atomic."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def put(self, data: bytes) -> StoredBlob:
        if not data:
            raise ValueError("cannot store empty content")
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file in the same directory, then rename, so a
            # crash never leaves a partially written blob under its final name.
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(data)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
        return StoredBlob(sha256=digest, size_bytes=len(data))

    def read(self, sha256: str) -> bytes:
        try:
            return self._path(sha256).read_bytes()
        except FileNotFoundError:
            raise BlobNotFoundError(sha256) from None

    def exists(self, sha256: str) -> bool:
        return self._path(sha256).is_file()

    def _path(self, sha256: str) -> Path:
        # Only lowercase hex digests are accepted, which rules out path traversal.
        if not _SHA256_HEX.fullmatch(sha256):
            raise ValueError("invalid content hash")
        return self._root / sha256[:2] / sha256[2:4] / sha256

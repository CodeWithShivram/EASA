import hashlib
from pathlib import Path

import pytest

from app.storage.blob_store import BlobNotFoundError, LocalBlobStore

CONTENT = b"Synthetic test document: EASA leave policy, page 1."
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "uploads")


def test_put_and_read_round_trip(store: LocalBlobStore) -> None:
    blob = store.put(CONTENT)

    assert blob.sha256 == DIGEST
    assert blob.size_bytes == len(CONTENT)
    assert store.read(DIGEST) == CONTENT
    assert store.exists(DIGEST)


def test_blob_path_is_derived_from_the_hash_only(store: LocalBlobStore, tmp_path: Path) -> None:
    store.put(CONTENT)

    expected = tmp_path / "uploads" / DIGEST[:2] / DIGEST[2:4] / DIGEST
    assert expected.read_bytes() == CONTENT
    # No temporary files are left behind.
    assert [p.name for p in expected.parent.iterdir()] == [DIGEST]


def test_identical_content_is_stored_once(store: LocalBlobStore, tmp_path: Path) -> None:
    first = store.put(CONTENT)
    second = store.put(CONTENT)

    assert first == second
    files = [p for p in (tmp_path / "uploads").rglob("*") if p.is_file()]
    assert len(files) == 1


def test_empty_content_is_rejected(store: LocalBlobStore) -> None:
    with pytest.raises(ValueError, match="empty"):
        store.put(b"")


@pytest.mark.parametrize(
    "bad_hash",
    [
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        DIGEST.upper(),
        DIGEST[:-1],
        DIGEST + "0",
        "",
    ],
)
def test_invalid_hashes_are_rejected(store: LocalBlobStore, bad_hash: str) -> None:
    with pytest.raises(ValueError, match="invalid content hash"):
        store.read(bad_hash)
    with pytest.raises(ValueError, match="invalid content hash"):
        store.exists(bad_hash)


def test_reading_a_missing_blob_raises(store: LocalBlobStore) -> None:
    assert not store.exists(DIGEST)
    with pytest.raises(BlobNotFoundError):
        store.read(DIGEST)

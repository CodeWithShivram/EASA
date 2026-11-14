"""Validation of uploaded files.

Uploaded files are untrusted. A file is accepted only if its extension is
allowlisted AND its content matches that type. Nothing here executes or
extracts the file; content parsing happens later (P2-M3).
"""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import PurePosixPath, PureWindowsPath

from app.core.errors import AppError
from app.db.documents import DocumentMediaType

MAX_FILENAME_LENGTH = 255

EXTENSION_MEDIA_TYPES = {
    ".pdf": DocumentMediaType.PDF,
    ".docx": DocumentMediaType.DOCX,
    ".txt": DocumentMediaType.TXT,
}

# Path and reserved characters that are unsafe in displayed or downloaded names.
_RESERVED_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
# Unicode categories removed from names: control (Cc) and format (Cf) characters,
# which include zero-width characters, bidirectional controls that can disguise
# an extension (e.g. "x\u202efdp.txt") and tag characters.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf"})
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class DocxLimits:
    """Limits that stop zip bombs before any content is decompressed."""

    max_entries: int = 1000
    max_total_uncompressed_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: int = 200


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    media_type: DocumentMediaType


class UploadRejectedError(AppError):
    pass


def _reject(code: str, message: str, status: HTTPStatus) -> UploadRejectedError:
    return UploadRejectedError(message, code=code, status_code=status)


def sanitize_filename(raw: str | None) -> str:
    """Return a safe display name. The result is metadata only, never a path."""
    if not raw:
        raise _reject("invalid_filename", "The file must have a name.", HTTPStatus.BAD_REQUEST)
    # Keep only the last path component, whichever separator the client used.
    name = PureWindowsPath(PurePosixPath(raw).name).name
    name = unicodedata.normalize("NFC", name)
    # Whitespace controls (tabs, newlines) become spaces; other unsafe characters go.
    name = _WHITESPACE.sub(" ", name)
    name = "".join(c for c in name if unicodedata.category(c) not in _INVISIBLE_CATEGORIES)
    name = _RESERVED_FILENAME_CHARS.sub("", name)
    name = name.strip(" ").rstrip(" .")
    # Leading dots are rejected, not stripped: ".txt" is not a real name, and
    # hidden-file names are not accepted.
    if not name or name.startswith("."):
        raise _reject("invalid_filename", "The file name is not valid.", HTTPStatus.BAD_REQUEST)
    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, suffix = name.rpartition(".")
        keep = MAX_FILENAME_LENGTH - len(suffix) - 1
        name = f"{stem[:keep]}.{suffix}" if dot and keep > 0 else name[:MAX_FILENAME_LENGTH]
    return name


def validate_upload(
    raw_filename: str | None,
    data: bytes,
    *,
    max_bytes: int,
    docx_limits: DocxLimits | None = None,
) -> ValidatedUpload:
    filename = sanitize_filename(raw_filename)
    extension = PurePosixPath(filename).suffix.lower()
    media_type = EXTENSION_MEDIA_TYPES.get(extension)
    if media_type is None:
        raise _reject(
            "unsupported_file_type",
            "Only PDF, DOCX and TXT files are accepted.",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    if not data:
        raise _reject("empty_file", "The file is empty.", HTTPStatus.UNPROCESSABLE_CONTENT)
    if len(data) > max_bytes:
        raise _reject(
            "file_too_large",
            f"The file exceeds the maximum size of {max_bytes} bytes.",
            HTTPStatus.CONTENT_TOO_LARGE,
        )

    match media_type:
        case DocumentMediaType.PDF:
            _check_pdf(data)
        case DocumentMediaType.DOCX:
            _check_docx(data, docx_limits or DocxLimits())
        case DocumentMediaType.TXT:
            _check_txt(data)
    return ValidatedUpload(filename=filename, media_type=media_type)


def _content_mismatch() -> UploadRejectedError:
    return _reject(
        "file_content_mismatch",
        "The file content does not match its extension.",
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    )


def _check_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise _content_mismatch()


def _check_docx(data: bytes, limits: DocxLimits) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise _content_mismatch()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            content_types = _read_content_types(archive, entries)
    except (
        zipfile.BadZipFile,
        NotImplementedError,
        UnicodeDecodeError,
        ValueError,
        EOFError,
        OSError,
    ):
        # zipfile raises all of these for malformed archives (found by fuzzing).
        raise _reject(
            "corrupt_file", "The DOCX file is damaged.", HTTPStatus.UNPROCESSABLE_CONTENT
        ) from None

    if len(entries) > limits.max_entries:
        raise _archive_rejected()
    total = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise _encrypted_rejected()
        total += entry.file_size
        ratio = entry.file_size / max(entry.compress_size, 1)
        if total > limits.max_total_uncompressed_bytes or ratio > limits.max_compression_ratio:
            raise _archive_rejected()

    names = {entry.filename for entry in entries}
    if not {"[Content_Types].xml", "word/document.xml"} <= names:
        raise _content_mismatch()
    # Macro-enabled content is never executed here, but it has no place in a
    # knowledge-base document, so it is refused outright. Word locates macros
    # through content types, so check those, not only the usual part name.
    lowered = content_types.lower()
    if (
        b"vbaproject" in lowered
        or b"macroenabled" in lowered
        or any(name.lower().endswith("vbaproject.bin") for name in names)
    ):
        raise _reject(
            "macros_not_allowed",
            "Documents containing macros are not accepted.",
            HTTPStatus.UNPROCESSABLE_CONTENT,
        )


# [Content_Types].xml is tiny in real documents; refuse to read huge ones.
_MAX_CONTENT_TYPES_BYTES = 1024 * 1024


def _read_content_types(archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo]) -> bytes:
    for entry in entries:
        if entry.filename == "[Content_Types].xml":
            if entry.flag_bits & 0x1:
                raise _encrypted_rejected()
            if entry.file_size > _MAX_CONTENT_TYPES_BYTES:
                raise _archive_rejected()
            return archive.read(entry)
    return b""


def _encrypted_rejected() -> UploadRejectedError:
    return _reject(
        "encrypted_file", "Encrypted files are not accepted.", HTTPStatus.UNPROCESSABLE_CONTENT
    )


def _archive_rejected() -> UploadRejectedError:
    return _reject(
        "archive_limits_exceeded",
        "The DOCX file expands beyond the allowed limits.",
        HTTPStatus.UNPROCESSABLE_CONTENT,
    )


def _check_txt(data: bytes) -> None:
    if data.startswith((b"%PDF-", b"PK\x03\x04")) or b"\x00" in data:
        raise _content_mismatch()
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _reject(
            "invalid_text_encoding",
            "Text files must be UTF-8 encoded.",
            HTTPStatus.UNPROCESSABLE_CONTENT,
        ) from None

import io
import zipfile

import pytest

from app.db.documents import DocumentMediaType
from app.services.uploads import (
    MAX_FILENAME_LENGTH,
    DocxLimits,
    UploadRejectedError,
    sanitize_filename,
    validate_upload,
)
from tests.fixtures import DOCX_BYTES, PDF_BYTES, TXT_BYTES, make_minimal_docx_zip

MAX = 1024 * 1024


def rejection_code(raw_filename: str | None, data: bytes, **kwargs: object) -> str:
    with pytest.raises(UploadRejectedError) as exc_info:
        validate_upload(raw_filename, data, max_bytes=MAX, **kwargs)  # type: ignore[arg-type]
    return exc_info.value.code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("policy.pdf", "policy.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\Windows\\win.ini.txt", "win.ini.txt"),
        ("C:\\Users\\someone\\report.docx", "report.docx"),
        ('bad<>:"|?*name.txt', "badname.txt"),
        ("tab\tand\nnewline.txt", "tab and newline.txt"),
        ("  spaced   out  .txt ", "spaced out .txt"),
        ("cafe\u0301.txt", "caf\u00e9.txt"),  # normalized to NFC
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "...", "/", ".hidden.txt", "<>|"])
def test_sanitize_filename_rejects_empty_or_hidden_names(raw: str | None) -> None:
    with pytest.raises(UploadRejectedError) as exc_info:
        sanitize_filename(raw)
    assert exc_info.value.code == "invalid_filename"


def test_sanitize_filename_truncates_and_keeps_extension() -> None:
    name = sanitize_filename("a" * 400 + ".docx")

    assert len(name) == MAX_FILENAME_LENGTH
    assert name.endswith(".docx")


@pytest.mark.parametrize(
    ("filename", "data", "media_type"),
    [
        ("policy.pdf", PDF_BYTES, DocumentMediaType.PDF),
        ("policy.PDF", PDF_BYTES, DocumentMediaType.PDF),
        ("handbook.docx", DOCX_BYTES, DocumentMediaType.DOCX),
        ("notes.txt", TXT_BYTES, DocumentMediaType.TXT),
        ("bom.txt", b"\xef\xbb\xbfUTF-8 with BOM", DocumentMediaType.TXT),
    ],
)
def test_valid_uploads(filename: str, data: bytes, media_type: DocumentMediaType) -> None:
    result = validate_upload(filename, data, max_bytes=MAX)

    assert result.media_type is media_type
    assert result.filename == filename


@pytest.mark.parametrize("filename", ["script.exe", "page.html", "archive.zip", "noext", "x.doc"])
def test_unsupported_extensions(filename: str) -> None:
    assert rejection_code(filename, TXT_BYTES) == "unsupported_file_type"


@pytest.mark.parametrize(
    ("filename", "data"),
    [
        ("fake.pdf", TXT_BYTES),
        ("fake.pdf", DOCX_BYTES),
        ("fake.docx", PDF_BYTES),
        ("fake.docx", TXT_BYTES),
        ("fake.txt", PDF_BYTES),
        ("fake.txt", DOCX_BYTES),
        ("binary.txt", b"text\x00with NUL"),
        ("not-word.docx", make_minimal_docx_zip(minimal=False, extra_entries={"a.txt": b"x"})),
    ],
)
def test_content_must_match_extension(filename: str, data: bytes) -> None:
    assert rejection_code(filename, data) == "file_content_mismatch"


def test_empty_file() -> None:
    assert rejection_code("empty.txt", b"") == "empty_file"


def test_file_too_large() -> None:
    assert rejection_code("big.txt", b"a" * (MAX + 1)) == "file_too_large"


def test_text_must_be_utf8() -> None:
    assert rejection_code("latin1.txt", "caf\u00e9".encode("latin-1")) == "invalid_text_encoding"


def test_corrupt_docx() -> None:
    assert rejection_code("broken.docx", b"PK\x03\x04 truncated archive") == "corrupt_file"


def test_docx_with_too_many_entries() -> None:
    data = make_minimal_docx_zip(extra_entries={f"word/media/{i}.xml": b"x" for i in range(5)})

    code = rejection_code("many.docx", data, docx_limits=DocxLimits(max_entries=3))
    assert code == "archive_limits_exceeded"


def test_docx_that_expands_too_much() -> None:
    data = make_minimal_docx_zip(extra_entries={"word/big.xml": b"0" * 200_000})

    limits = DocxLimits(max_total_uncompressed_bytes=100_000)
    assert rejection_code("bomb.docx", data, docx_limits=limits) == "archive_limits_exceeded"


def test_docx_with_extreme_compression_ratio() -> None:
    data = make_minimal_docx_zip(extra_entries={"word/zeros.xml": b"\x00" * 1_000_000})

    code = rejection_code("ratio.docx", data, docx_limits=DocxLimits(max_compression_ratio=50))
    assert code == "archive_limits_exceeded"


def test_docx_with_encrypted_entry() -> None:
    # zipfile cannot write encrypted entries, so set the "encrypted" flag bit
    # (bit 0 of the general-purpose flags) in every central-directory header.
    data = bytearray(DOCX_BYTES)
    position = data.find(b"PK\x01\x02")
    while position != -1:
        data[position + 8] |= 0x01
        position = data.find(b"PK\x01\x02", position + 4)
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as archive:
        assert all(entry.flag_bits & 0x1 for entry in archive.infolist())

    assert rejection_code("locked.docx", bytes(data)) == "encrypted_file"


def test_rejections_carry_http_status() -> None:
    with pytest.raises(UploadRejectedError) as exc_info:
        validate_upload("x.exe", TXT_BYTES, max_bytes=MAX)

    assert exc_info.value.status_code == 415


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("invoice\u202efdp.txt", "invoicefdp.txt"),  # right-to-left override
        ("rep\u200bort\u200d.pdf", "report.pdf"),  # zero-width characters
        ("\u2066isolate\u2069.docx", "isolate.docx"),  # bidi isolates
        ("c1\x9bcontrol.txt", "c1control.txt"),  # C1 control character (CSI)
        ("next\x85line.txt", "next line.txt"),  # NEL is whitespace: becomes a space
    ],
)
def test_sanitize_filename_removes_invisible_and_bidi_characters(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_docx_with_macros_is_rejected() -> None:
    data = make_minimal_docx_zip(extra_entries={"word/vbaProject.bin": b"synthetic macro stub"})

    assert rejection_code("macro.docx", data) == "macros_not_allowed"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("x\U000e0041\U000e0042.txt", "x.txt"),  # tag characters
        ("ara\u061cbic.pdf", "arabic.pdf"),  # Arabic letter mark
        ("soft\u00adhyphen.docx", "softhyphen.docx"),
    ],
)
def test_sanitize_filename_removes_all_format_characters(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    "content_types",
    [
        b'<Types><Override ContentType="application/vnd.ms-office.vbaProject"/></Types>',
        b'<Types><Override ContentType="application/'
        b'vnd.ms-word.document.macroEnabled.main+xml"/></Types>',
    ],
)
def test_macros_are_detected_from_content_types(content_types: bytes) -> None:
    # The macro part has an unusual name, so only the content types reveal it.
    data = make_minimal_docx_zip(
        minimal=False,
        extra_entries={
            "[Content_Types].xml": content_types,
            "word/document.xml": b"<document/>",
            "word/renamed.bin": b"synthetic macro stub",
        },
    )

    assert rejection_code("hidden-macro.docx", data) == "macros_not_allowed"


def test_unsupported_zip_version_is_corrupt_not_a_server_error() -> None:
    # Found by fuzzing: zipfile raises NotImplementedError for unknown versions.
    data = bytearray(DOCX_BYTES)
    central = data.find(b"PK\x01\x02")
    data[central + 6] = 88  # "version needed to extract" = 8.8
    data[central + 7] = 0

    assert rejection_code("future.docx", bytes(data)) == "corrupt_file"

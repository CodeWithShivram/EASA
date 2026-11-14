import pytest

from app.db.documents import DocumentMediaType
from app.services.extraction import BlockKind, ExtractionError, extract_document
from tests.fixtures import (
    DOCX_BYTES,
    PDF_BYTES,
    make_encrypted_pdf,
    make_minimal_docx_zip,
    make_pdf_bytes,
)


def extract(media_type: DocumentMediaType, data: bytes, max_pdf_pages: int = 500):
    return extract_document(media_type, data, max_pdf_pages=max_pdf_pages)


def failure_code(media_type: DocumentMediaType, data: bytes, **kwargs: int) -> str:
    with pytest.raises(ExtractionError) as exc_info:
        extract(media_type, data, **kwargs)
    return exc_info.value.code


def test_pdf_text_is_extracted_per_page() -> None:
    result = extract(DocumentMediaType.PDF, PDF_BYTES)

    assert result.page_count == 2
    assert [b.page_number for b in result.blocks] == [1, 2]
    assert all(b.kind is BlockKind.PAGE for b in result.blocks)
    assert "Economy class applies to flights under six hours." in result.blocks[0].text
    assert "Submit receipts within 30 days of travel." in result.blocks[1].text


def test_pdf_pages_without_text_are_skipped_but_counted() -> None:
    data = make_pdf_bytes([["Only page one has text."], []])

    result = extract(DocumentMediaType.PDF, data)

    assert result.page_count == 2
    assert [b.page_number for b in result.blocks] == [1]


def test_pdf_without_any_text_fails() -> None:
    assert failure_code(DocumentMediaType.PDF, make_pdf_bytes([[], []])) == "no_extractable_text"


def test_encrypted_pdf_is_rejected() -> None:
    assert failure_code(DocumentMediaType.PDF, make_encrypted_pdf()) == "encrypted_file"


def test_pdf_over_the_page_limit_is_rejected() -> None:
    data = make_pdf_bytes([["page"]] * 3)

    assert failure_code(DocumentMediaType.PDF, data, max_pdf_pages=2) == "too_many_pages"


def test_corrupt_pdf_is_rejected() -> None:
    assert failure_code(DocumentMediaType.PDF, b"%PDF-1.4\nnot really a pdf") == "corrupt_file"


def test_docx_headings_become_sections() -> None:
    result = extract(DocumentMediaType.DOCX, DOCX_BYTES)

    assert result.page_count is None
    summary = [(b.kind, b.section, b.text) for b in result.blocks]
    assert summary == [
        (BlockKind.HEADING, "EASA Employee Handbook", "EASA Employee Handbook"),
        (BlockKind.PARAGRAPH, "EASA Employee Handbook", "This handbook is synthetic test data."),
        (BlockKind.HEADING, "Leave", "Leave"),
        (BlockKind.PARAGRAPH, "Leave", "Employees receive 20 days of annual leave."),
        (BlockKind.TABLE, "Leave", "Leave type | Days\nAnnual | 20"),
        (BlockKind.HEADING, "Remote Work", "Remote Work"),
        (BlockKind.PARAGRAPH, "Remote Work", "Remote work requires manager approval."),
    ]


def test_structurally_invalid_docx_is_rejected() -> None:
    # Passes upload validation (required zip parts exist) but is not a real DOCX.
    assert failure_code(DocumentMediaType.DOCX, make_minimal_docx_zip()) == "corrupt_file"


def test_txt_is_split_into_paragraphs() -> None:
    data = b"Title line\n\nFirst paragraph\nstill first.\n\n\nSecond paragraph."

    result = extract(DocumentMediaType.TXT, data)

    assert [b.text for b in result.blocks] == [
        "Title line",
        "First paragraph\nstill first.",
        "Second paragraph.",
    ]
    assert all(b.page_number is None and b.section is None for b in result.blocks)


def test_whitespace_only_txt_fails() -> None:
    assert failure_code(DocumentMediaType.TXT, b" \n\t\n ") == "no_extractable_text"


def test_canonical_text_joins_blocks() -> None:
    result = extract(DocumentMediaType.TXT, b"one\n\ntwo")

    assert result.text == "one\n\ntwo"

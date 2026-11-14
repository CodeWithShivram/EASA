import io
import time
from pathlib import Path

import docx
import pytest
from docx.oxml.ns import qn

from app.db.documents import DocumentMediaType
from app.services import extraction
from app.services.extraction import BlockKind, ExtractionError, extract_document
from tests.fixtures import (
    DOCX_BYTES,
    PDF_BYTES,
    WORDML,
    make_docx_with_document_xml,
    make_encrypted_pdf,
    make_minimal_docx_zip,
    make_pdf_bytes,
    make_pdf_decompression_bomb,
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


def test_pdf_decompression_bomb_is_reported_as_a_resource_limit() -> None:
    start = time.perf_counter()

    code = failure_code(DocumentMediaType.PDF, make_pdf_decompression_bomb())

    assert code == "resource_limit_exceeded"
    assert time.perf_counter() - start < 10


def test_text_over_the_size_limit_is_rejected() -> None:
    with pytest.raises(ExtractionError) as exc_info:
        extract_document(DocumentMediaType.TXT, b"a" * 101, max_pdf_pages=10, max_text_chars=100)

    assert exc_info.value.code == "text_too_large"


def test_docx_entity_expansion_bomb_is_rejected_quickly() -> None:
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{("&a" + str(i - 1) + ";") * 10}">' for i in range(1, 10)
    )
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE w:document [{entities}]>'
        f"<w:document {WORDML}><w:body><w:p><w:r><w:t>&a9;</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    start = time.perf_counter()

    assert failure_code(DocumentMediaType.DOCX, make_docx_with_document_xml(xml)) == "corrupt_file"
    assert time.perf_counter() - start < 5


@pytest.mark.parametrize(
    ("declaration", "reference"),
    [
        ('<!ENTITY x SYSTEM "{uri}">', "&x;"),  # external general entity
        ('<!ENTITY % p SYSTEM "{uri}"> %p;', ""),  # external parameter entity
    ],
)
def test_docx_external_entities_are_never_resolved(
    tmp_path: Path, declaration: str, reference: str
) -> None:
    # python-docx parses with resolve_entities=False and lxml does not load
    # external DTDs, so the file is processed but the secret is never read.
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-MARKER", encoding="utf-8")
    dtd = declaration.format(uri=secret.as_uri())
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE w:document [{dtd}]>'
        f"<w:document {WORDML}><w:body><w:p><w:r><w:t>before {reference} after</w:t></w:r>"
        f"</w:p></w:body></w:document>"
    ).encode()

    result = extract_document(
        DocumentMediaType.DOCX, make_docx_with_document_xml(xml), max_pdf_pages=10
    )

    assert "TOP-SECRET-MARKER" not in result.text
    assert result.text.startswith("before")


def _docx_with_spanned_cell(span: int) -> bytes:
    document = docx.Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.text = "spanned"  # set before the span: table.cell() itself amplifies
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(tc_pr.makeelement(qn("w:gridSpan"), {qn("w:val"): str(span)}))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_grid_span_does_not_amplify_cells() -> None:
    # python-docx's row.cells would repeat this cell a million times.
    data = _docx_with_spanned_cell(1_000_000)
    start = time.perf_counter()

    result = extract(DocumentMediaType.DOCX, data)

    assert result.text == "spanned"
    assert time.perf_counter() - start < 5


def test_too_many_blocks_fail_fast() -> None:
    data = b"a\n\n" * (extraction.MAX_BLOCKS + 1)
    start = time.perf_counter()

    assert failure_code(DocumentMediaType.TXT, data) == "document_too_complex"
    assert time.perf_counter() - start < 10


def test_text_budget_covers_docx_tables() -> None:
    with pytest.raises(ExtractionError) as exc_info:
        extract_document(DocumentMediaType.DOCX, DOCX_BYTES, max_pdf_pages=10, max_text_chars=80)

    assert exc_info.value.code == "text_too_large"


def test_lowered_pdf_stream_limit_applies() -> None:
    # 25 MB inflated: under pypdf's 75 MB default, over the 20 MB limit set here.
    assert (
        failure_code(DocumentMediaType.PDF, make_pdf_decompression_bomb(25 * 1024 * 1024))
        == "resource_limit_exceeded"
    )


def test_pdf_total_decoded_bytes_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "PDF_MAX_DECODED_BYTES_TOTAL", 10)

    assert failure_code(DocumentMediaType.PDF, PDF_BYTES) == "resource_limit_exceeded"


def test_pdf_time_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "PDF_TIME_BUDGET_SECONDS", -1.0)

    assert failure_code(DocumentMediaType.PDF, PDF_BYTES) == "resource_limit_exceeded"

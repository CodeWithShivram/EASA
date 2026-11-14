"""Synthetic test files (no real company data)."""

import io
import secrets
import zipfile
import zlib

import docx
from pypdf import PdfWriter

TXT_BYTES = b"EASA synthetic leave policy.\nEmployees receive 20 days of annual leave.\n"


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf_bytes(pages: list[list[str]]) -> bytes:
    """Build a small, valid PDF with one Helvetica text line per list item.

    Hand-written so tests need no PDF-generation dependency. Offsets in the
    cross-reference table are computed, so readers parse it without repairs.
    """
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
            f"/Count {len(pages)} >>"
        ).encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, lines in zip(page_ids, pages, strict=True):
        content_id = page_id + 1
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        operators = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
        operators += [f"({_pdf_escape(line)}) Tj T*" for line in lines]
        operators.append("ET")
        stream = "\n".join(operators).encode("latin-1")
        objects[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref_offset = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(out)


PDF_PAGES = [
    ["EASA Travel Policy", "Economy class applies to flights under six hours."],
    ["Expenses", "Submit receipts within 30 days of travel."],
]
PDF_BYTES = make_pdf_bytes(PDF_PAGES)


def make_docx() -> bytes:
    """A real DOCX with a title, headings, paragraphs and a table."""
    document = docx.Document()
    document.add_heading("EASA Employee Handbook", level=0)
    document.add_paragraph("This handbook is synthetic test data.")
    document.add_heading("Leave", level=1)
    document.add_paragraph("Employees receive 20 days of annual leave.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Leave type"
    table.cell(0, 1).text = "Days"
    table.cell(1, 0).text = "Annual"
    table.cell(1, 1).text = "20"
    document.add_heading("Remote Work", level=1)
    document.add_paragraph("Remote work requires manager approval.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


DOCX_BYTES = make_docx()


def make_minimal_docx_zip(
    *, extra_entries: dict[str, bytes] | None = None, minimal: bool = True
) -> bytes:
    """A zip with only the parts upload validation checks for (not a parseable DOCX)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if minimal:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
            archive.writestr("word/document.xml", '<?xml version="1.0"?><document/>')
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def make_encrypted_pdf() -> bytes:
    """PDF_BYTES encrypted with a random password (RC4, supported by pypdf without extras)."""
    writer = PdfWriter(clone_from=io.BytesIO(PDF_BYTES))
    writer.encrypt(user_password=secrets.token_hex(8), algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_pdf_decompression_bomb(inflated_bytes: int = 80 * 1024 * 1024) -> bytes:
    """A one-page PDF (~80 KB) whose content stream inflates past pypdf's 75 MB limit."""
    payload = zlib.compress(b" " * inflated_bytes, 9)
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        4: b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(payload)
        + payload
        + b"\nendstream",
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref_offset = len(out)
    out += b"xref\n0 5\n0000000000 65535 f \n"
    out += b"".join(f"{offsets[n]:010d} 00000 n \n".encode() for n in range(1, 5))
    out += f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(out)


WORDML = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx_with_document_xml(document_xml: bytes) -> bytes:
    """DOCX_BYTES with word/document.xml replaced (for hostile-XML tests)."""
    source = zipfile.ZipFile(io.BytesIO(DOCX_BYTES))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = document_xml if item.filename == "word/document.xml" else source.read(item)
            target.writestr(item, content)
    return out.getvalue()

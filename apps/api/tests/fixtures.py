"""Synthetic test files (no real company data)."""

import io
import zipfile

TXT_BYTES = b"EASA synthetic leave policy.\nEmployees receive 20 days of annual leave.\n"

# A minimal PDF header followed by filler. Only the signature is checked at upload time.
PDF_BYTES = b"%PDF-1.4\n% synthetic test file\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def make_docx_bytes(
    *, extra_entries: dict[str, bytes] | None = None, minimal: bool = True
) -> bytes:
    """Build a structurally minimal DOCX (zip with the required parts)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if minimal:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
            archive.writestr("word/document.xml", '<?xml version="1.0"?><document/>')
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


DOCX_BYTES = make_docx_bytes()

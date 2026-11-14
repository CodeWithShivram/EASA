"""Text extraction from validated uploads.

Produces an ordered list of normalized text blocks with page and section
metadata, which chunking (P2-M4) consumes. Files are parsed in memory; nothing
is written to disk or executed.
"""

import io
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.db.documents import DocumentMediaType
from app.services.normalization import normalize_text

logger = logging.getLogger(__name__)


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    PAGE = "page"
    TABLE = "table"


@dataclass(frozen=True)
class TextBlock:
    text: str
    kind: BlockKind
    page_number: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    blocks: list[TextBlock]
    page_count: int | None

    @property
    def text(self) -> str:
        """The document's canonical normalized text; chunk offsets refer to it."""
        return "\n\n".join(block.text for block in self.blocks)


class ExtractionError(Exception):
    """A document that cannot be processed, with a client-safe reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def extract_document(
    media_type: DocumentMediaType, data: bytes, *, max_pdf_pages: int
) -> ExtractionResult:
    match media_type:
        case DocumentMediaType.PDF:
            result = _extract_pdf(data, max_pdf_pages)
        case DocumentMediaType.DOCX:
            result = _extract_docx(data)
        case DocumentMediaType.TXT:
            result = _extract_txt(data)
    if not result.blocks:
        # e.g. a scanned PDF without a text layer (no OCR in this project yet).
        raise ExtractionError("no_extractable_text")
    return result


def _extract_pdf(data: bytes, max_pages: int) -> ExtractionResult:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("encrypted_file")
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise ExtractionError("too_many_pages")
        blocks = []
        for number, page in enumerate(reader.pages, start=1):
            text = normalize_text(page.extract_text() or "")
            if text:
                blocks.append(TextBlock(text=text, kind=BlockKind.PAGE, page_number=number))
    except PdfReadError:
        raise ExtractionError("corrupt_file") from None
    return ExtractionResult(blocks=blocks, page_count=page_count)


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        document: DocxDocument = docx.Document(io.BytesIO(data))
    except Exception as exc:
        # The input is untrusted and python-docx raises many undocumented exception
        # types for malformed packages (PackageNotFoundError, XMLSyntaxError,
        # KeyError, even AttributeError). Any failure of this single parse call
        # means the file is unusable; failures elsewhere stay unexpected errors.
        logger.info("docx parse failed", extra={"error_type": type(exc).__name__})
        raise ExtractionError("corrupt_file") from None

    blocks: list[TextBlock] = []
    section: str | None = None
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = normalize_text(item.text)
            if not text:
                continue
            if _is_heading(item):
                section = text[:500]
                blocks.append(TextBlock(text=text, kind=BlockKind.HEADING, section=section))
            else:
                blocks.append(TextBlock(text=text, kind=BlockKind.PARAGRAPH, section=section))
        elif isinstance(item, Table):
            text = normalize_text(_table_text(item))
            if text:
                blocks.append(TextBlock(text=text, kind=BlockKind.TABLE, section=section))
    return ExtractionResult(blocks=blocks, page_count=None)


def _is_heading(paragraph: Paragraph) -> bool:
    style: Any = paragraph.style
    name = (style.name if style is not None else "") or ""
    return name == "Title" or name.startswith("Heading")


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _extract_txt(data: bytes) -> ExtractionResult:
    # Upload validation already guarantees UTF-8.
    text = normalize_text(data.decode("utf-8-sig"))
    blocks = [
        TextBlock(text=paragraph, kind=BlockKind.PARAGRAPH)
        for paragraph in (p.strip() for p in text.split("\n\n"))
        if paragraph
    ]
    return ExtractionResult(blocks=blocks, page_count=None)

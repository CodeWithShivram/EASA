"""Text extraction from validated uploads.

Produces an ordered list of normalized text blocks with page and section
metadata, which chunking consumes. Files are parsed in memory; nothing is
executed. Work is bounded while it happens (characters, blocks, decoded PDF
bytes, wall-clock time), not only after extraction has finished.
"""

import io
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

import docx
from docx.document import Document as DocxDocument
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError, PyPdfError

from app.db.documents import DocumentMediaType
from app.services.normalization import normalize_text

logger = logging.getLogger(__name__)
# pypdf logs warnings that quote names and values from the file; keep them out
# of the application log (and stop hostile PDFs from flooding it).
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Upper bound on normalized text per document, separators included.
MAX_EXTRACTED_CHARS = 5_000_000
# Upper bound on blocks (paragraphs, headings, tables, pages) per document.
MAX_BLOCKS = 50_000
# PDF parsing limits. pypdf's own defaults (75 MB per stream, no total) bound
# decompression but not parsing work, so stricter limits apply here.
PDF_MAX_STREAM_OUTPUT_BYTES = 20_000_000
PDF_MAX_DECODED_BYTES_TOTAL = 50_000_000
PDF_TIME_BUDGET_SECONDS = 30.0
_PDF_LIMITS = {
    name: PDF_MAX_STREAM_OUTPUT_BYTES
    for name in (
        "zlib_maximum_output_length",
        "lzw_maximum_output_length",
        "run_length_maximum_output_length",
        "array_based_stream_maximum_output_length",
        "jbig2_maximum_output_length",
        "maximum_declared_stream_length",
    )
}


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


@dataclass
class _Budget:
    """Running limits checked as blocks are produced."""

    max_chars: int
    max_blocks: int = MAX_BLOCKS
    chars: int = 0
    blocks: list[TextBlock] = field(default_factory=list)

    def add(self, block: TextBlock) -> None:
        self.charge(len(block.text) + 2)  # +2 for the "\n\n" block separator
        if len(self.blocks) >= self.max_blocks:
            raise ExtractionError("document_too_complex")
        self.blocks.append(block)

    def charge(self, chars: int) -> None:
        self.chars += chars
        if self.chars > self.max_chars:
            raise ExtractionError("text_too_large")


def extract_document(
    media_type: DocumentMediaType,
    data: bytes,
    *,
    max_pdf_pages: int,
    max_text_chars: int = MAX_EXTRACTED_CHARS,
) -> ExtractionResult:
    budget = _Budget(max_chars=max_text_chars)
    match media_type:
        case DocumentMediaType.PDF:
            page_count = _extract_pdf(data, max_pdf_pages, budget)
        case DocumentMediaType.DOCX:
            page_count = _extract_docx(data, budget)
        case DocumentMediaType.TXT:
            page_count = _extract_txt(data, budget)
    if not budget.blocks:
        # e.g. a scanned PDF without a text layer (no OCR in this project yet).
        raise ExtractionError("no_extractable_text")
    return ExtractionResult(blocks=budget.blocks, page_count=page_count)


def _extract_pdf(data: bytes, max_pages: int, budget: _Budget) -> int:
    deadline = time.monotonic() + PDF_TIME_BUDGET_SECONDS
    decoded_total = 0
    try:
        with apply_configuration(**_PDF_LIMITS):
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ExtractionError("encrypted_file")
            page_count = len(reader.pages)
            if page_count > max_pages:
                raise ExtractionError("too_many_pages")
            for number, page in enumerate(reader.pages, start=1):
                if time.monotonic() > deadline:
                    raise ExtractionError("resource_limit_exceeded")
                # Decode the content stream first: pypdf's extract_text() silently
                # returns "" when a decompression limit is hit, which would hide a
                # decompression bomb behind "no_extractable_text".
                contents = page.get_contents()
                if contents is not None:
                    decoded_total += len(contents.get_data())
                    if decoded_total > PDF_MAX_DECODED_BYTES_TOTAL:
                        raise ExtractionError("resource_limit_exceeded")
                text = normalize_text(page.extract_text() or "")
                if text:
                    budget.add(TextBlock(text=text, kind=BlockKind.PAGE, page_number=number))
    except LimitReachedError:
        raise ExtractionError("resource_limit_exceeded") from None
    except PyPdfError:
        # PdfReadError and other pypdf parsing errors.
        raise ExtractionError("corrupt_file") from None
    return page_count


def _extract_docx(data: bytes, budget: _Budget) -> None:
    try:
        document: DocxDocument = docx.Document(io.BytesIO(data))
    except Exception as exc:
        # The input is untrusted and python-docx raises many undocumented exception
        # types for malformed packages (PackageNotFoundError, XMLSyntaxError,
        # KeyError, even AttributeError). Any failure of this single parse call
        # means the file is unusable; failures elsewhere stay unexpected errors.
        logger.info("docx parse failed", extra={"error_type": type(exc).__name__})
        raise ExtractionError("corrupt_file") from None

    # Resolve style names once: Paragraph.style runs an XPath search over all
    # styles per paragraph, which dominated runtime for heading-heavy files.
    style_names = {style.style_id: style.name or "" for style in document.styles}
    section: str | None = None
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = normalize_text(item.text)
            if not text:
                continue
            if _is_heading(item, style_names):
                section = text[:500]
                budget.add(TextBlock(text=text, kind=BlockKind.HEADING, section=section))
            else:
                budget.add(TextBlock(text=text, kind=BlockKind.PARAGRAPH, section=section))
        elif isinstance(item, Table):
            text = normalize_text(_table_text(item, budget))
            if text:
                budget.add(TextBlock(text=text, kind=BlockKind.TABLE, section=section))
    return None


def _is_heading(paragraph: Paragraph, style_names: dict[str, str]) -> bool:
    style_id = paragraph._p.style  # None means the default paragraph style
    name = style_names.get(style_id, "") if style_id else ""
    return name == "Title" or name.startswith("Heading")


def _table_text(table: Table, budget: _Budget) -> str:
    # Read each physical cell (<w:tc>) once. python-docx's row.cells repeats a
    # cell once per grid column it spans, and gridSpan is attacker-controlled,
    # so a tiny file could otherwise expand into billions of cell copies.
    remaining = budget.max_chars - budget.chars
    length = 0
    rows = []
    for tr in table._tbl.tr_lst:
        cells = []
        for tc in tr.tc_lst:
            cell_text = " ".join(_Cell(tc, table).text.split())
            length += len(cell_text) + 3  # " | " or the row's newline
            if length > remaining:
                raise ExtractionError("text_too_large")
            cells.append(cell_text)
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _extract_txt(data: bytes, budget: _Budget) -> None:
    # Upload validation already guarantees UTF-8.
    text = normalize_text(data.decode("utf-8-sig"))
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            budget.add(TextBlock(text=paragraph, kind=BlockKind.PARAGRAPH))
    return None

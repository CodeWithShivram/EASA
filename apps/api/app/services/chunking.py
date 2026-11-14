"""Deterministic chunking of extracted documents.

Chunk offsets refer to the document's canonical text (``ExtractionResult.text``:
blocks joined by a blank line), and every chunk's text is exactly
``canonical_text[char_start:char_end]``. The same input and configuration
always produce the same chunks.
"""

from bisect import bisect_right
from dataclasses import dataclass
from enum import StrEnum

from app.services.extraction import BlockKind, ExtractionError, ExtractionResult, TextBlock

BLOCK_SEPARATOR = "\n\n"
# Upper bound on chunks per document (bounds rows written in one transaction).
MAX_CHUNKS = 20_000
# When cutting a window, look back this fraction of max_chars for whitespace.
_BREAK_SEARCH_FRACTION = 0.2


class ChunkingStrategy(StrEnum):
    # Overlapping windows over the whole text, ignoring structure.
    FIXED = "fixed"
    # Whole blocks merged up to the size limit, never across pages or sections.
    STRUCTURED = "structured"


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: ChunkingStrategy = ChunkingStrategy.STRUCTURED
    max_chars: int = 1200
    overlap_chars: int = 150

    def __post_init__(self) -> None:
        if self.max_chars < 100:
            raise ValueError("max_chars must be at least 100")
        if not 0 <= self.overlap_chars < self.max_chars // 2:
            raise ValueError("overlap_chars must be >= 0 and less than half of max_chars")

    def as_record(self) -> dict[str, str | int]:
        return {
            "strategy": self.strategy.value,
            "max_chars": self.max_chars,
            "overlap_chars": self.overlap_chars,
        }


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    char_start: int
    char_end: int
    page_number: int | None
    section: str | None


@dataclass(frozen=True)
class _PlacedBlock:
    block: TextBlock
    start: int
    end: int


def chunk_document(result: ExtractionResult, config: ChunkingConfig) -> list[Chunk]:
    text = result.text
    placed = _place_blocks(result.blocks)
    if config.strategy is ChunkingStrategy.FIXED:
        spans = _windows(text, 0, len(text), config)
    else:
        spans = _structured_spans(text, placed, config)

    block_ends = [item.end for item in placed]
    chunks: list[Chunk] = []
    for start, end in spans:
        start, end = _trim(text, start, end)
        if start >= end:
            continue
        if len(chunks) >= MAX_CHUNKS:
            raise ExtractionError("document_too_complex")
        origin = _block_at(placed, block_ends, start)
        chunks.append(
            Chunk(
                index=len(chunks),
                text=text[start:end],
                char_start=start,
                char_end=end,
                page_number=origin.block.page_number,
                section=origin.block.section,
            )
        )
    return chunks


def _place_blocks(blocks: list[TextBlock]) -> list[_PlacedBlock]:
    placed, position = [], 0
    for block in blocks:
        placed.append(_PlacedBlock(block, position, position + len(block.text)))
        position += len(block.text) + len(BLOCK_SEPARATOR)
    return placed


def _block_at(placed: list[_PlacedBlock], block_ends: list[int], offset: int) -> _PlacedBlock:
    # The block containing the offset, or the next one if it falls in a separator.
    # Binary search keeps chunking O(chunks * log(blocks)) instead of quadratic.
    index = bisect_right(block_ends, offset)
    return placed[min(index, len(placed) - 1)]


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _windows(text: str, start: int, end: int, config: ChunkingConfig) -> list[tuple[int, int]]:
    """Split text[start:end] into windows of at most max_chars with overlap."""
    spans: list[tuple[int, int]] = []
    position = start
    while position < end:
        limit = min(position + config.max_chars, end)
        cut = limit if limit == end else _break_point(text, position, limit, config)
        spans.append((position, cut))
        if cut >= end:
            break
        next_position = max(cut - config.overlap_chars, position + 1)
        # Start the next window at a word boundary inside the overlap, if possible.
        while next_position < cut and not text[next_position - 1].isspace():
            next_position += 1
        position = next_position if next_position < cut else cut
    return spans


def _break_point(text: str, start: int, limit: int, config: ChunkingConfig) -> int:
    """Prefer cutting after a newline, then after a space, near the limit."""
    floor = max(start + 1, limit - int(config.max_chars * _BREAK_SEARCH_FRACTION))
    for separators in ("\n", " "):
        for index in range(limit, floor - 1, -1):
            if text[index - 1] in separators:
                return index
    return limit


def _structured_spans(
    text: str, placed: list[_PlacedBlock], config: ChunkingConfig
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    current: list[_PlacedBlock] = []

    def flush() -> None:
        if current:
            spans.append((current[0].start, current[-1].end))
            current.clear()

    for item in placed:
        block = item.block
        if block.kind is BlockKind.HEADING:
            flush()  # a heading always starts a new chunk
        elif current and (
            block.page_number != current[-1].block.page_number
            or block.section != current[-1].block.section
            or item.end - current[0].start > config.max_chars
        ):
            flush()

        if item.end - item.start > config.max_chars:
            flush()
            spans.extend(_windows(text, item.start, item.end, config))
        else:
            current.append(item)
    flush()
    return spans

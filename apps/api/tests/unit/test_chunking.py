from itertools import pairwise

import pytest

from app.db.documents import DocumentMediaType
from app.services.chunking import Chunk, ChunkingConfig, ChunkingStrategy, chunk_document
from app.services.extraction import (
    BlockKind,
    ExtractionResult,
    TextBlock,
    extract_document,
)
from tests.fixtures import DOCX_BYTES, PDF_BYTES

FIXED = ChunkingStrategy.FIXED
STRUCTURED = ChunkingStrategy.STRUCTURED

# Synthetic prose with real word boundaries.
SENTENCE = "Employees may request remote work with manager approval. "


def paragraph(text: str, page: int | None = None, section: str | None = None) -> TextBlock:
    return TextBlock(text=text, kind=BlockKind.PARAGRAPH, page_number=page, section=section)


def heading(text: str) -> TextBlock:
    return TextBlock(text=text, kind=BlockKind.HEADING, section=text)


def result_of(*blocks: TextBlock, page_count: int | None = None) -> ExtractionResult:
    return ExtractionResult(blocks=list(blocks), page_count=page_count)


def assert_invariants(result: ExtractionResult, chunks: list[Chunk], max_chars: int) -> None:
    text = result.text
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.text == text[chunk.char_start : chunk.char_end]
        assert chunk.text == chunk.text.strip()
        assert 0 < len(chunk.text) <= max_chars
    # Every non-whitespace character is covered by at least one chunk.
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.char_start, chunk.char_end))
    assert all(i in covered for i, ch in enumerate(text) if not ch.isspace())


@pytest.mark.parametrize("strategy", [FIXED, STRUCTURED])
@pytest.mark.parametrize(
    ("media_type", "data"),
    [(DocumentMediaType.PDF, PDF_BYTES), (DocumentMediaType.DOCX, DOCX_BYTES)],
)
def test_invariants_hold_for_real_documents(
    strategy: ChunkingStrategy, media_type: DocumentMediaType, data: bytes
) -> None:
    result = extract_document(media_type, data, max_pdf_pages=10)
    config = ChunkingConfig(strategy=strategy, max_chars=100, overlap_chars=20)

    chunks = chunk_document(result, config)

    assert chunks
    assert_invariants(result, chunks, config.max_chars)


@pytest.mark.parametrize("strategy", [FIXED, STRUCTURED])
def test_chunking_is_deterministic(strategy: ChunkingStrategy) -> None:
    result = result_of(paragraph(SENTENCE * 30))
    config = ChunkingConfig(strategy=strategy, max_chars=200, overlap_chars=40)

    assert chunk_document(result, config) == chunk_document(result, config)


def test_fixed_windows_overlap_and_break_at_words() -> None:
    result = result_of(paragraph(SENTENCE * 30))
    config = ChunkingConfig(strategy=FIXED, max_chars=200, overlap_chars=40)

    chunks = chunk_document(result, config)

    assert len(chunks) > 5
    assert_invariants(result, chunks, config.max_chars)
    for previous, current in pairwise(chunks):
        overlap = previous.char_end - current.char_start
        assert 0 < overlap <= config.overlap_chars
        # Windows start and end on word boundaries.
        assert result.text[current.char_start - 1].isspace()
        assert previous.text[-1] != " "


def test_fixed_without_overlap_does_not_repeat_text() -> None:
    result = result_of(paragraph(SENTENCE * 20))
    config = ChunkingConfig(strategy=FIXED, max_chars=150, overlap_chars=0)

    chunks = chunk_document(result, config)

    for previous, current in pairwise(chunks):
        assert current.char_start >= previous.char_end


def test_fixed_splits_text_without_spaces_at_the_limit() -> None:
    result = result_of(paragraph("x" * 450))
    config = ChunkingConfig(strategy=FIXED, max_chars=200, overlap_chars=0)

    chunks = chunk_document(result, config)

    assert [len(c.text) for c in chunks] == [200, 200, 50]


def test_structured_merges_small_blocks_within_a_section() -> None:
    result = result_of(
        heading("Leave"),
        paragraph("Annual leave is 20 days.", section="Leave"),
        paragraph("Sick leave is 10 days.", section="Leave"),
    )

    chunks = chunk_document(result, ChunkingConfig(strategy=STRUCTURED))

    assert len(chunks) == 1
    assert chunks[0].text == "Leave\n\nAnnual leave is 20 days.\n\nSick leave is 10 days."
    assert chunks[0].section == "Leave"


def test_structured_starts_a_chunk_at_each_heading() -> None:
    result = result_of(
        heading("Leave"),
        paragraph("Annual leave is 20 days.", section="Leave"),
        heading("Travel"),
        paragraph("Economy class under six hours.", section="Travel"),
    )

    chunks = chunk_document(result, ChunkingConfig(strategy=STRUCTURED))

    assert [c.section for c in chunks] == ["Leave", "Travel"]
    assert chunks[1].text.startswith("Travel")


def test_structured_never_crosses_pages() -> None:
    result = result_of(paragraph("Page one text.", page=1), paragraph("Page two text.", page=2))

    chunks = chunk_document(result, ChunkingConfig(strategy=STRUCTURED))

    assert [(c.page_number, c.text) for c in chunks] == [
        (1, "Page one text."),
        (2, "Page two text."),
    ]


def test_structured_respects_the_size_limit_when_merging() -> None:
    blocks = [paragraph(f"Paragraph {i}. " + "word " * 15, section="S") for i in range(6)]
    config = ChunkingConfig(strategy=STRUCTURED, max_chars=200, overlap_chars=0)
    result = result_of(*blocks)

    chunks = chunk_document(result, config)

    assert len(chunks) > 1
    assert_invariants(result, chunks, config.max_chars)


def test_structured_splits_an_oversized_block_with_overlap() -> None:
    result = result_of(
        heading("Policy"),
        paragraph(SENTENCE * 20, section="Policy"),
        paragraph("Short closing note.", section="Policy"),
    )
    config = ChunkingConfig(strategy=STRUCTURED, max_chars=300, overlap_chars=50)

    chunks = chunk_document(result, config)

    assert_invariants(result, chunks, config.max_chars)
    assert chunks[0].text == "Policy"
    assert chunks[-1].text == "Short closing note."
    assert all(c.section == "Policy" for c in chunks)
    middle = chunks[1:-1]
    assert len(middle) >= 4
    assert middle[0].char_end > middle[1].char_start  # overlapping windows


def test_pdf_chunks_keep_page_numbers() -> None:
    result = extract_document(DocumentMediaType.PDF, PDF_BYTES, max_pdf_pages=10)

    chunks = chunk_document(result, ChunkingConfig())

    assert [c.page_number for c in chunks] == [1, 2]


def test_docx_chunks_keep_sections() -> None:
    result = extract_document(DocumentMediaType.DOCX, DOCX_BYTES, max_pdf_pages=10)

    chunks = chunk_document(result, ChunkingConfig())

    assert [c.section for c in chunks] == ["EASA Employee Handbook", "Leave", "Remote Work"]
    assert "Leave type | Days" in chunks[1].text


def test_config_record() -> None:
    config = ChunkingConfig(strategy=FIXED, max_chars=500, overlap_chars=50)

    assert config.as_record() == {"strategy": "fixed", "max_chars": 500, "overlap_chars": 50}


@pytest.mark.parametrize(
    ("max_chars", "overlap_chars"),
    [(99, 0), (200, 100), (200, 150), (200, -1)],
)
def test_invalid_config_is_rejected(max_chars: int, overlap_chars: int) -> None:
    with pytest.raises(ValueError, match=r"max_chars|overlap_chars"):
        ChunkingConfig(max_chars=max_chars, overlap_chars=overlap_chars)

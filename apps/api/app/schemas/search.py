import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.services.search import MAX_QUERY_CHARS, MAX_TOP_K, SearchMode


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    mode: SearchMode = SearchMode.SEMANTIC


class Citation(BaseModel):
    """Where the text comes from, for display and verification."""

    document_id: uuid.UUID
    filename: str
    page_number: int | None
    section: str | None
    chunk_index: int
    char_start: int
    char_end: int


class SearchHitResponse(BaseModel):
    score: float
    text: str
    citation: Citation


class SearchResponse(BaseModel):
    mode: SearchMode
    # Embedding model used; null in keyword mode.
    model_id: str | None
    results: list[SearchHitResponse]

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.search import Citation
from app.services.answers import DEFAULT_TOP_K, MAX_TOP_K, AnswerStatus, InsufficientReason
from app.services.search import MAX_QUERY_CHARS


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    # Chunks retrieved as evidence (fewer may fit into the model's context).
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)


class AnswerSource(BaseModel):
    label: str  # as cited in the answer, e.g. "S1"
    text: str
    citation: Citation


class AnswerResponse(BaseModel):
    status: AnswerStatus
    # Null unless status is "answered".
    answer: str | None
    # Why the evidence was insufficient; null when answered.
    reason: InsufficientReason | None
    # The sources the answer cites, in order of first citation.
    sources: list[AnswerSource]
    # Chunks retrieved before the model was asked.
    retrieved: int
    # Chat model that produced the reply; null when it was not called.
    model_id: str | None

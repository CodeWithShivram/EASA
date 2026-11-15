import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.conversations import MessageRole
from app.schemas.answers import AnswerResponse
from app.schemas.search import Citation
from app.services.answers import DEFAULT_TOP_K, MAX_TOP_K
from app.services.search import MAX_QUERY_CHARS


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)


class ConversationSummaryResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    # Stored messages (two per question).
    messages: int


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]


class StoredSource(BaseModel):
    """A cited source as stored: citation metadata, without the chunk text."""

    label: str
    citation: Citation


class MessageResponse(BaseModel):
    id: uuid.UUID
    position: int
    role: MessageRole
    content: str | None
    # Assistant messages only.
    status: str | None
    reason: str | None
    sources: list[StoredSource]
    model_id: str | None
    created_at: datetime


class ConversationResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    # 1-based number of this question in the conversation.
    turn: int
    # Same shape as POST /api/v1/answers (sources include the text the model saw).
    answer: AnswerResponse

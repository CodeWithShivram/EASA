"""Support tools (Phase 5, P5-M2): knowledge search and synthetic tickets.

Every tool acts as the calling identity: searches are tenant-scoped and
tickets are visible only to their reporter. Tool output is data, never
instructions, when it is shown to a model.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.db.tickets import SupportTicket, TicketPriority, TicketStatus
from app.embeddings.base import Embedder
from app.repositories.tickets import TicketRepository
from app.retrieval.factory import build_indexes
from app.services.normalization import normalize_text
from app.services.search import MAX_QUERY_CHARS, SearchMode, SearchService
from app.tools.base import Tool, ToolContext, ToolError
from app.tools.registry import ToolRegistry

SEARCH_RESULTS = 3
SNIPPET_CHARS = 600


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _expect[T: BaseModel](arguments: BaseModel, model: type[T]) -> T:
    """The executor passes the validated Input; anything else is a programming error."""
    if not isinstance(arguments, model):
        raise TypeError(f"expected {model.__name__}")
    return arguments


# --- search_knowledge_base ---------------------------------------------------


class SearchInput(_Strict):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS, description="What to look up")


class KnowledgeHit(BaseModel):
    filename: str
    page_number: int | None
    section: str | None
    text: str


class SearchOutput(BaseModel):
    results: list[KnowledgeHit]


class SearchKnowledgeBase(Tool):
    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = "Search the company documents for passages relevant to a question."
    Input: ClassVar[type[BaseModel]] = SearchInput
    Output: ClassVar[type[BaseModel]] = SearchOutput
    permission: ClassVar[str] = "knowledge:search"
    timeout_seconds: ClassVar[float] = 20.0
    retries: ClassVar[int] = 1

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        query = _expect(arguments, SearchInput).query
        with context.session_factory() as session:
            search = SearchService(session, self._embedder, *build_indexes(session))
            found = search.search(
                context.identity, query, top_k=SEARCH_RESULTS, mode=SearchMode.HYBRID
            )
        return SearchOutput(
            results=[
                KnowledgeHit(
                    filename=hit.filename,
                    page_number=hit.page_number,
                    section=hit.section,
                    text=hit.text[:SNIPPET_CHARS],
                )
                for hit in found.hits
            ]
        )


# --- get_ticket / get_ticket_status ------------------------------------------


class TicketNumberInput(_Strict):
    number: int = Field(ge=1, le=10_000_000, description="The ticket number, e.g. 42")


class TicketOutput(BaseModel):
    number: int
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime
    updated_at: datetime


class TicketStatusOutput(BaseModel):
    number: int
    status: TicketStatus
    updated_at: datetime


def _own_ticket(context: ToolContext, number: int) -> SupportTicket:
    with context.session_factory() as session:
        ticket = TicketRepository(session).get_own(
            context.identity.tenant_id, context.identity.user_id, number
        )
        if ticket is None:
            # Same answer for missing tickets and other people's tickets.
            raise ToolError(f"Ticket {number} was not found.", code="ticket_not_found")
        session.expunge(ticket)
        return ticket


class GetTicket(Tool):
    name: ClassVar[str] = "get_ticket"
    description: ClassVar[str] = "Show one of your support tickets by its number."
    Input: ClassVar[type[BaseModel]] = TicketNumberInput
    Output: ClassVar[type[BaseModel]] = TicketOutput
    permission: ClassVar[str] = "tickets:read"
    retries: ClassVar[int] = 1

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        ticket = _own_ticket(context, _expect(arguments, TicketNumberInput).number)
        return TicketOutput(
            number=ticket.number,
            title=ticket.title,
            description=ticket.description[:2000],
            status=ticket.status,
            priority=ticket.priority,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )


class GetTicketStatus(Tool):
    name: ClassVar[str] = "get_ticket_status"
    description: ClassVar[str] = "Check the status of one of your support tickets."
    Input: ClassVar[type[BaseModel]] = TicketNumberInput
    Output: ClassVar[type[BaseModel]] = TicketStatusOutput
    permission: ClassVar[str] = "tickets:read"
    retries: ClassVar[int] = 1

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        ticket = _own_ticket(context, _expect(arguments, TicketNumberInput).number)
        return TicketStatusOutput(
            number=ticket.number, status=ticket.status, updated_at=ticket.updated_at
        )


# --- create_draft_ticket ------------------------------------------------------


class CreateDraftInput(_Strict):
    title: str = Field(min_length=5, max_length=200, description="Short summary of the problem")
    description: str = Field(min_length=10, max_length=2000, description="What happened")
    priority: TicketPriority = TicketPriority.NORMAL


class CreateDraftOutput(BaseModel):
    number: int
    status: TicketStatus
    title: str


class CreateDraftTicket(Tool):
    name: ClassVar[str] = "create_draft_ticket"
    description: ClassVar[str] = (
        "Create a draft support ticket for the user. Needs the user's confirmation."
    )
    Input: ClassVar[type[BaseModel]] = CreateDraftInput
    Output: ClassVar[type[BaseModel]] = CreateDraftOutput
    permission: ClassVar[str] = "tickets:create"
    consequential: ClassVar[bool] = True

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        draft = _expect(arguments, CreateDraftInput)
        title = normalize_text(draft.title)
        description = normalize_text(draft.description)
        if len(title) < 5 or len(description) < 10:
            raise ToolError("The title or description is too short.", code="too_short")
        with context.session_factory() as session:
            ticket = TicketRepository(session).create(
                context.identity.tenant_id,
                context.identity.user_id,
                title=title,
                description=description,
                status=TicketStatus.DRAFT,
                priority=draft.priority,
            )
            return CreateDraftOutput(number=ticket.number, status=ticket.status, title=ticket.title)


def build_tool_registry(embedder: Embedder) -> ToolRegistry:
    """The allowlist of tools available to the agent."""
    return ToolRegistry(
        [SearchKnowledgeBase(embedder), GetTicket(), GetTicketStatus(), CreateDraftTicket()]
    )

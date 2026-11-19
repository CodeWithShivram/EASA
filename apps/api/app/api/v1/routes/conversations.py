import uuid
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import get_conversation_service, limit_model_calls, require
from app.api.v1.routes.answers import to_answer_response
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.db.conversations import ConversationMessage
from app.schemas.conversations import (
    AskRequest,
    AskResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationSummaryResponse,
    MessageResponse,
    StoredSource,
)
from app.schemas.search import Citation
from app.services.conversations import MAX_LIST_LIMIT, ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {HTTPStatus.NOT_FOUND: {"model": ErrorResponse}}
_ASK_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
    )
}

Service = Annotated[ConversationService, Depends(get_conversation_service)]
CurrentIdentity = Annotated[Identity, Depends(require("knowledge:search"))]


def _message(message: ConversationMessage) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        position=message.position,
        role=message.role,
        content=message.content,
        status=message.status,
        reason=message.reason,
        sources=[
            StoredSource(
                label=source["label"],
                citation=Citation(
                    document_id=uuid.UUID(source["document_id"]),
                    filename=source["filename"],
                    page_number=source["page_number"],
                    section=source["section"],
                    chunk_index=source["chunk_index"],
                    char_start=source["char_start"],
                    char_end=source["char_end"],
                ),
            )
            for source in message.sources or []
        ],
        model_id=message.model_id,
        created_at=message.created_at,
    )


@router.post("", response_model=ConversationSummaryResponse, status_code=HTTPStatus.CREATED)
def create_conversation(service: Service, identity: CurrentIdentity) -> ConversationSummaryResponse:
    """Start a conversation owned by the current user."""
    conversation = service.create(identity)
    return ConversationSummaryResponse(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=0,
    )


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    service: Service,
    identity: CurrentIdentity,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 20,
) -> ConversationListResponse:
    """The current user's conversations, most recently updated first."""
    return ConversationListResponse(
        items=[
            ConversationSummaryResponse(
                id=s.id, created_at=s.created_at, updated_at=s.updated_at, messages=s.messages
            )
            for s in service.list(identity, limit=limit)
        ]
    )


@router.get("/{conversation_id}", response_model=ConversationResponse, responses=_NOT_FOUND)
def get_conversation(
    conversation_id: uuid.UUID, service: Service, identity: CurrentIdentity
) -> ConversationResponse:
    """A conversation with all its messages."""
    conversation, messages = service.get(identity, conversation_id)
    return ConversationResponse(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_message(m) for m in messages],
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=AskResponse,
    responses=_ASK_ERRORS,
    dependencies=[Depends(limit_model_calls)],
)
def ask(
    conversation_id: uuid.UUID, request: AskRequest, service: Service, identity: CurrentIdentity
) -> AskResponse:
    """Ask a question in a conversation; earlier turns help interpret it."""
    result = service.ask(identity, conversation_id, request.question, top_k=request.top_k)
    return AskResponse(
        conversation_id=result.conversation.id,
        turn=result.answer_message.position // 2 + 1,
        answer=to_answer_response(result.answer),
    )


@router.delete("/{conversation_id}", status_code=HTTPStatus.NO_CONTENT, responses=_NOT_FOUND)
def delete_conversation(
    conversation_id: uuid.UUID, service: Service, identity: CurrentIdentity
) -> Response:
    """Delete a conversation and its messages permanently."""
    service.delete(identity, conversation_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)

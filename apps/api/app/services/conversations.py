"""Conversations: grounded answers that can refer to earlier turns (Phase 4, P4-M4).

A turn is stored only after the answer pipeline succeeds, as two messages
(the question and the reply) in one transaction; model failures store
nothing. Conversations belong to one user in one tenant; anyone else gets the
same 404 as for a missing conversation. Content is never logged.
"""

import logging
import uuid
from dataclasses import dataclass
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity import Identity
from app.db.conversations import Conversation, ConversationMessage, MessageRole
from app.repositories.conversations import ConversationRepository, ConversationSummary
from app.services.answers import (
    DEFAULT_TOP_K,
    HISTORY_TURNS,
    AnswerResult,
    AnswerService,
    Turn,
)
from app.services.normalization import normalize_text

logger = logging.getLogger(__name__)

MAX_TURNS = 50
MAX_LIST_LIMIT = 100


class ConversationNotFoundError(AppError):
    def __init__(self) -> None:
        # Same answer for missing conversations and other users' ones.
        super().__init__(
            "Conversation not found.",
            code="conversation_not_found",
            status_code=HTTPStatus.NOT_FOUND,
        )


@dataclass(frozen=True)
class AskResult:
    conversation: Conversation
    answer: AnswerResult
    question_message: ConversationMessage
    answer_message: ConversationMessage


def history_from(messages: list[ConversationMessage]) -> list[Turn]:
    """Pair stored messages into turns, oldest first."""
    turns: list[Turn] = []
    for question, reply in zip(messages[::2], messages[1::2], strict=False):
        if question.role is MessageRole.USER and reply.role is MessageRole.ASSISTANT:
            turns.append(Turn(question=question.content or "", answer=reply.content))
    return turns


class ConversationService:
    def __init__(self, session: Session, answers: AnswerService) -> None:
        self._session = session
        self._repository = ConversationRepository(session)
        self._answers = answers

    def create(self, identity: Identity) -> Conversation:
        conversation = self._repository.create(identity.tenant_id, identity.user_id)
        self._session.commit()
        logger.info("conversation created", extra={"conversation_id": str(conversation.id)})
        return conversation

    def list(self, identity: Identity, *, limit: int) -> list[ConversationSummary]:
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise AppError(
                "The limit is out of range.",
                code="invalid_limit",
                status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            )
        return self._repository.list(identity.tenant_id, identity.user_id, limit=limit)

    def get(
        self, identity: Identity, conversation_id: uuid.UUID
    ) -> tuple[Conversation, list[ConversationMessage]]:
        conversation = self._owned(identity, conversation_id)
        return conversation, self._repository.messages(conversation)

    def ask(
        self,
        identity: Identity,
        conversation_id: uuid.UUID,
        question: str,
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> AskResult:
        conversation = self._owned(identity, conversation_id)
        messages = self._repository.messages(conversation)
        if len(messages) // 2 >= MAX_TURNS:
            raise AppError(
                f"This conversation has reached its limit of {MAX_TURNS} questions.",
                code="conversation_full",
                status_code=HTTPStatus.CONFLICT,
            )
        # Model and retrieval errors propagate before anything is written.
        result = self._answers.answer(
            identity, question, top_k=top_k, history=history_from(messages)
        )
        question_message = ConversationMessage(
            role=MessageRole.USER, content=normalize_text(question)
        )
        answer_message = ConversationMessage(
            role=MessageRole.ASSISTANT,
            content=result.answer,
            status=result.status.value,
            reason=result.reason.value if result.reason else None,
            sources=[
                {
                    "label": s.label,
                    "document_id": str(s.hit.document_id),
                    "filename": s.hit.filename,
                    "page_number": s.hit.page_number,
                    "section": s.hit.section,
                    "chunk_index": s.hit.chunk_index,
                    "char_start": s.hit.char_start,
                    "char_end": s.hit.char_end,
                }
                for s in result.sources
            ],
            model_id=result.model_id,
        )
        try:
            self._repository.add_messages(conversation, [question_message, answer_message])
            self._session.commit()
        except IntegrityError:
            # Another request added a turn at the same position first.
            self._session.rollback()
            raise AppError(
                "The conversation changed while answering; please ask again.",
                code="conversation_busy",
                status_code=HTTPStatus.CONFLICT,
            ) from None
        logger.info(
            "conversation turn stored",
            extra={
                "conversation_id": str(conversation.id),
                "turn": answer_message.position // 2 + 1,
                "history_turns": min(len(messages) // 2, HISTORY_TURNS),
                "status": result.status.value,
            },
        )
        return AskResult(conversation, result, question_message, answer_message)

    def delete(self, identity: Identity, conversation_id: uuid.UUID) -> None:
        conversation = self._owned(identity, conversation_id)
        self._repository.delete(conversation)
        self._session.commit()
        logger.info("conversation deleted", extra={"conversation_id": str(conversation_id)})

    def _owned(self, identity: Identity, conversation_id: uuid.UUID) -> Conversation:
        conversation = self._repository.get(identity.tenant_id, identity.user_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

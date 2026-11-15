from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_answer_service, get_identity
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.schemas.answers import AnswerRequest, AnswerResponse, AnswerSource
from app.schemas.search import Citation
from app.services.answers import AnswerService

router = APIRouter(prefix="/answers", tags=["answers"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (
        HTTPStatus.UNPROCESSABLE_CONTENT,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
    )
}


@router.post("", response_model=AnswerResponse, responses=_ERRORS)
def answer(
    request: AnswerRequest,
    service: Annotated[AnswerService, Depends(get_answer_service)],
    identity: Annotated[Identity, Depends(get_identity)],
) -> AnswerResponse:
    """Answer a question from the tenant's documents only, with cited sources."""
    result = service.answer(identity, request.question, top_k=request.top_k)
    return AnswerResponse(
        status=result.status,
        answer=result.answer,
        reason=result.reason,
        retrieved=result.retrieved,
        model_id=result.model_id,
        sources=[
            AnswerSource(
                label=source.label,
                text=source.text,
                citation=Citation(
                    document_id=source.hit.document_id,
                    filename=source.hit.filename,
                    page_number=source.hit.page_number,
                    section=source.hit.section,
                    chunk_index=source.hit.chunk_index,
                    char_start=source.hit.char_start,
                    char_end=source.hit.char_end,
                ),
            )
            for source in result.sources
        ],
    )

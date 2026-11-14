from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_identity, get_search_service
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.schemas.search import Citation, SearchHitResponse, SearchRequest, SearchResponse
from app.services.search import SearchService

router = APIRouter(prefix="/search", tags=["search"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (HTTPStatus.UNPROCESSABLE_CONTENT, HTTPStatus.SERVICE_UNAVAILABLE)
}


@router.post("", response_model=SearchResponse, responses=_ERRORS)
def search(
    request: SearchRequest,
    service: Annotated[SearchService, Depends(get_search_service)],
    identity: Annotated[Identity, Depends(get_identity)],
) -> SearchResponse:
    """Semantic search over the current tenant's processed documents, with citations."""
    result = service.search(identity, request.query, top_k=request.top_k)
    return SearchResponse(
        model_id=result.model_id,
        results=[
            SearchHitResponse(
                score=hit.score,
                text=hit.text,
                citation=Citation(
                    document_id=hit.document_id,
                    filename=hit.filename,
                    page_number=hit.page_number,
                    section=hit.section,
                    chunk_index=hit.chunk_index,
                    char_start=hit.char_start,
                    char_end=hit.char_end,
                ),
            )
            for hit in result.hits
        ],
    )

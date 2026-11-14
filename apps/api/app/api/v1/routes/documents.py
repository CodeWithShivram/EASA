import uuid
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile

from app.api.dependencies import get_document_service, get_identity
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.repositories.documents import MAX_PAGE_SIZE
from app.schemas.documents import DocumentListResponse, DocumentResponse
from app.services.documents import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])

ServiceDep = Annotated[DocumentService, Depends(get_document_service)]
IdentityDep = Annotated[Identity, Depends(get_identity)]

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONTENT_TOO_LARGE,
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        HTTPStatus.UNPROCESSABLE_CONTENT,
    )
}


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=HTTPStatus.CREATED,
    responses={HTTPStatus.OK: {"model": DocumentResponse}, **_ERRORS},
)
def upload_document(
    response: Response,
    file: Annotated[UploadFile, File(description="A PDF, DOCX or UTF-8 TXT file.")],
    service: ServiceDep,
    identity: IdentityDep,
) -> DocumentResponse:
    """Upload a document. Re-uploading identical content returns the existing document (200)."""
    result = service.upload(identity, file.filename, file.file.read())
    if not result.created:
        response.status_code = HTTPStatus.OK
    response.headers["Location"] = f"/api/v1/documents/{result.document.id}"
    return DocumentResponse.model_validate(result.document)


@router.get("", response_model=DocumentListResponse, responses=_ERRORS)
def list_documents(
    service: ServiceDep,
    identity: IdentityDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    """List the current tenant's documents, newest first."""
    documents = service.list(identity, limit=limit, offset=offset)
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in documents], limit=limit, offset=offset
    )


@router.get("/{document_id}", response_model=DocumentResponse, responses=_ERRORS)
def get_document(
    document_id: uuid.UUID, service: ServiceDep, identity: IdentityDep
) -> DocumentResponse:
    """Get one of the current tenant's documents."""
    return DocumentResponse.model_validate(service.get(identity, document_id))

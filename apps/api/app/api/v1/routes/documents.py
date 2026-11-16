import uuid
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.api.dependencies import get_document_service, require
from app.core.correlation import get_correlation_id
from app.core.errors import ErrorResponse
from app.core.identity import Identity
from app.core.roles import Role
from app.db.audit import AuditOutcome
from app.repositories.audit import AuditRepository
from app.repositories.documents import MAX_CHUNK_PAGE_SIZE, MAX_PAGE_SIZE
from app.schemas.documents import (
    ChunkListResponse,
    ChunkResponse,
    DocumentListResponse,
    DocumentResponse,
    UpdateDocumentRequest,
)
from app.services.documents import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])

ServiceDep = Annotated[DocumentService, Depends(get_document_service)]
IdentityDep = Annotated[Identity, Depends(require("documents:read"))]
UploaderDep = Annotated[Identity, Depends(require("documents:upload"))]

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse}
    for status in (
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
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
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="A PDF, DOCX or UTF-8 TXT file.")],
    service: ServiceDep,
    identity: UploaderDep,
    min_role: Annotated[
        Role, Form(description="Lowest role that may see the document (at most your own)")
    ] = Role.EMPLOYEE,
) -> DocumentResponse:
    """Upload a document. Re-uploading identical content returns the existing document (200)."""
    result = service.upload(identity, file.filename, file.file.read(), min_role=min_role)
    _audit(
        request,
        identity,
        "document.upload",
        result.document.id,
        f"min_role={result.document.min_role} created={str(result.created).lower()}",
    )
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


@router.patch("/{document_id}", response_model=DocumentResponse, responses=_ERRORS)
def update_document(
    request: Request,
    document_id: uuid.UUID,
    body: UpdateDocumentRequest,
    service: ServiceDep,
    identity: UploaderDep,
) -> DocumentResponse:
    """Change who may see a document (its minimum role, at most the caller's own role)."""
    previous = service.set_min_role(identity, document_id, body.min_role)
    _audit(
        request,
        identity,
        "document.update",
        document_id,
        f"min_role={previous.value}->{body.min_role.value}",
    )
    return DocumentResponse.model_validate(service.get(identity, document_id))


@router.get("/{document_id}/chunks", response_model=ChunkListResponse, responses=_ERRORS)
def list_document_chunks(
    document_id: uuid.UUID,
    service: ServiceDep,
    identity: IdentityDep,
    limit: Annotated[int, Query(ge=1, le=MAX_CHUNK_PAGE_SIZE)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChunkListResponse:
    """List a document's chunks in order. Empty for documents that failed processing."""
    chunks, total = service.list_chunks(identity, document_id, limit=limit, offset=offset)
    return ChunkListResponse(
        document_id=document_id,
        items=[ChunkResponse.model_validate(c) for c in chunks],
        total=total,
        limit=limit,
        offset=offset,
    )


def _audit(
    request: Request, identity: Identity, action: str, document_id: uuid.UUID, detail: str
) -> None:
    AuditRepository(request.app.state.session_factory).record(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        action=action,
        target=f"document:{document_id}",
        outcome=AuditOutcome.SUCCEEDED,
        detail=detail,
        correlation_id=get_correlation_id(),
    )

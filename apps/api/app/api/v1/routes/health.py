from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_health_service
from app.schemas.health import LivenessResponse, ReadinessChecks, ReadinessResponse
from app.services.health import HealthService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Process liveness. Never checks the database or other dependencies."""
    return LivenessResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={HTTPStatus.SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> ReadinessResponse:
    """Dependency readiness. Returns 503 when a required dependency is unavailable."""
    report = service.check_readiness()
    if not report.is_ready:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if report.is_ready else "not_ready",
        checks=ReadinessChecks(database=report.database, embeddings=report.embeddings),
    )

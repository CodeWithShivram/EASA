from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessChecks(BaseModel):
    database: Literal["ok", "unavailable"]
    embeddings: Literal["ok", "unavailable"]
    # "disabled" when no chat model is configured (does not affect readiness).
    model: Literal["ok", "unavailable", "disabled"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks

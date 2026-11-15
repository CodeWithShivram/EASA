"""Direct tool access for development (Phase 5, P5-M2).

Lists the tools the current identity may use and invokes one through the
same executor the agent uses (P5-M3), so every check and audit record
applies. Tool outcomes are reported in the body with status 200; only a
malformed request is an error. Consequential tools return
``confirmation_required`` here: confirming arrives with the agent's pending
actions in P5-M3.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_identity
from app.core.identity import Identity
from app.tools.executor import ToolExecutor

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolDescription(BaseModel):
    name: str
    description: str
    consequential: bool
    input_schema: dict[str, Any]


class ToolListResponse(BaseModel):
    items: list[ToolDescription]


class InvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultResponse(BaseModel):
    tool: str
    outcome: str
    output: dict[str, Any] | None
    arguments: dict[str, Any] | None
    detail: str | None
    message: str | None


def get_tool_executor(request: Request) -> ToolExecutor:
    executor: ToolExecutor = request.app.state.tool_executor
    return executor


Executor = Annotated[ToolExecutor, Depends(get_tool_executor)]
CurrentIdentity = Annotated[Identity, Depends(get_identity)]


@router.get("", response_model=ToolListResponse)
def list_tools(executor: Executor, identity: CurrentIdentity) -> ToolListResponse:
    """Tools the current identity may use, with their input schemas."""
    return ToolListResponse(
        items=[ToolDescription(**item) for item in executor.registry.describe(identity)]
    )


@router.post("/{name}/invoke", response_model=ToolResultResponse)
def invoke_tool(
    name: Annotated[str, Path(max_length=64)],
    request: InvokeRequest,
    executor: Executor,
    identity: CurrentIdentity,
) -> ToolResultResponse:
    """Run a tool as the current identity (never confirmed here)."""
    result = executor.execute(identity, name, request.arguments)
    return ToolResultResponse(
        tool=result.tool,
        outcome=result.outcome.value,
        output=result.output,
        arguments=result.arguments,
        detail=result.detail,
        message=result.message,
    )

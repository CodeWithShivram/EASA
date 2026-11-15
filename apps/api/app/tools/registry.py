"""The allowlist of tools. Anything not registered here cannot run."""

from collections.abc import Sequence
from typing import Any

from app.core.identity import Identity
from app.tools.base import TOOL_NAME, Tool


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            _check_contract(tool)
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name {tool.name!r}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self, identity: Identity) -> list[dict[str, Any]]:
        """Tools the identity may use, with their input schemas (for the model prompt)."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "consequential": tool.consequential,
                "input_schema": tool.Input.model_json_schema(),
            }
            for name, tool in sorted(self._tools.items())
            if identity.can(tool.permission)
        ]


def _check_contract(tool: Tool) -> None:
    """Refuse badly specified tools at startup rather than at call time."""
    if not TOOL_NAME.fullmatch(tool.name):
        raise ValueError(f"invalid tool name {tool.name!r}")
    if tool.Input.model_config.get("extra") != "forbid":
        raise ValueError(f"tool {tool.name!r}: Input must forbid unknown fields")
    if not tool.permission:
        raise ValueError(f"tool {tool.name!r}: a permission is required")
    if tool.timeout_seconds <= 0:
        raise ValueError(f"tool {tool.name!r}: timeout must be positive")
    if tool.consequential and tool.retries:
        raise ValueError(f"tool {tool.name!r}: consequential tools must not retry")

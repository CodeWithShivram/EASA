import re
import uuid
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import Settings
from app.core.identity import Identity
from app.core.roles import ROLE_PERMISSIONS, Role
from app.repositories.audit import arguments_digest
from app.tools.base import Tool, ToolContext
from app.tools.registry import ToolRegistry


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class Out(BaseModel):
    text: str


class Echo(Tool):
    """Test double."""

    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echo the text."
    Input: ClassVar[type[BaseModel]] = In
    Output: ClassVar[type[BaseModel]] = Out
    permission: ClassVar[str] = "test:read"

    def run(self, context: ToolContext, arguments: BaseModel) -> BaseModel:
        return Out(text=arguments.text)  # type: ignore[attr-defined]


def tool(**overrides: object) -> Tool:
    """An Echo variant with some class attributes replaced."""
    return type("Variant", (Echo,), dict(overrides))()


def identity(*permissions: str) -> Identity:
    return Identity(uuid.uuid4(), uuid.uuid4(), frozenset(permissions))


class LooseIn(BaseModel):
    text: str  # allows unknown fields


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "Bad Name"}, "invalid tool name"),
        ({"Input": LooseIn}, "forbid unknown fields"),
        ({"permission": ""}, "permission is required"),
        ({"timeout_seconds": 0}, "timeout must be positive"),
        ({"consequential": True, "retries": 1}, "must not retry"),
        ({"user_stated": frozenset({"missing"})}, "user_stated names unknown fields"),
    ],
)
def test_badly_specified_tools_are_refused(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ToolRegistry([tool(**overrides)])


def test_tool_names_are_unique() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([Echo(), Echo()])


def test_describe_lists_only_permitted_tools_with_schemas() -> None:
    registry = ToolRegistry([Echo(), tool(name="writer", permission="test:write")])

    described = registry.describe(identity("test:read"))

    assert [d["name"] for d in described] == ["echo"]
    assert described[0]["input_schema"]["additionalProperties"] is False
    assert described[0]["consequential"] is False
    assert registry.describe(identity()) == []
    assert registry.names == ["echo", "writer"]


def test_identity_permissions_deny_by_default() -> None:
    assert identity("tickets:read").can("tickets:read")
    assert not identity("tickets:read").can("tickets:create")
    assert not Identity(uuid.uuid4(), uuid.uuid4()).can("tickets:read")


def test_argument_digests_are_canonical() -> None:
    assert arguments_digest({"a": 1, "b": "x"}) == arguments_digest({"b": "x", "a": 1})
    assert arguments_digest({"a": 1}) != arguments_digest({"a": 2})
    assert len(arguments_digest({})) == 64


def test_every_role_grants_well_formed_permissions() -> None:
    for role in Role:
        assert ROLE_PERMISSIONS[role]  # deny by default, but no role is empty
        assert all(re.fullmatch(r"[a-z][a-z_]*:[a-z][a-z_]*", p) for p in ROLE_PERMISSIONS[role])


def test_the_development_identity_settings_are_gone() -> None:
    # Phase 6: identity comes only from a session (ADR-031); old settings are refused.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dev_permissions=["tickets:read"])  # type: ignore[call-arg]

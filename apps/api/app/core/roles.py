"""Roles and the permissions they grant (Phase 6, ADR-031, ADR-032).

Each user has exactly one role. Permissions are derived from the role on every
request (never stored with a session or taken from a client), so a role change
applies immediately. Anything not listed is denied.

| Permission | Allows |
|---|---|
| knowledge:search | search, answers, conversations, the agent's knowledge tool |
| documents:read | listing documents and reading their chunks |
| documents:upload | uploading documents |
| tickets:read | reading one's own tickets (agent tools) |
| tickets:read_all | reading every ticket in the tenant (support view) |
| tickets:create | proposing draft tickets (confirmed by the user) |
| users:manage | creating users, changing roles, disabling, resetting passwords |
"""

from enum import StrEnum


class Role(StrEnum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMINISTRATOR = "administrator"


_EMPLOYEE = frozenset({"knowledge:search", "documents:read", "tickets:read", "tickets:create"})
_MANAGER = _EMPLOYEE | {"documents:upload", "tickets:read_all"}
_ADMINISTRATOR = _MANAGER | {"users:manage"}

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.EMPLOYEE: _EMPLOYEE,
    Role.MANAGER: _MANAGER,
    Role.ADMINISTRATOR: _ADMINISTRATOR,
}

# Document visibility (P6-M3, ADR-033): a document's minimum role. A user sees
# documents whose minimum role is at or below their own.
_RANK = {Role.EMPLOYEE: 0, Role.MANAGER: 1, Role.ADMINISTRATOR: 2}
# What a caller without a role (internal jobs such as evaluations) may see.
EMPLOYEE_LEVELS: tuple[str, ...] = (Role.EMPLOYEE.value,)


def visible_levels(role: str | None) -> tuple[str, ...]:
    """Minimum-role values of the documents this role may see (employee only if unknown)."""
    if role not in _RANK:
        return EMPLOYEE_LEVELS
    rank = _RANK[Role(role)]
    return tuple(r.value for r, value in _RANK.items() if value <= rank)


def can_assign_level(role: str | None, level: Role) -> bool:
    """A user may restrict a document to their own role or below, never above."""
    return level.value in visible_levels(role)

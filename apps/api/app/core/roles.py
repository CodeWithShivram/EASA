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

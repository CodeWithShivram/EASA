"""Roles and the permissions they grant (Phase 6, ADR-031).

Each user has exactly one role. Permissions are derived from the role on every
request (never stored with a session or taken from a client), so a role change
applies immediately. Anything not listed is denied. P6-M2 and P6-M3 extend the
map (user management, document upload and visibility, audit).
"""

from enum import StrEnum


class Role(StrEnum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMINISTRATOR = "administrator"


_BASE = frozenset({"knowledge:search", "tickets:read", "tickets:create"})

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.EMPLOYEE: _BASE,
    Role.MANAGER: _BASE,
    Role.ADMINISTRATOR: _BASE,
}

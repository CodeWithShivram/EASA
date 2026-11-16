"""The identity on whose behalf a request is served.

Resolved from a verified session token (app.services.auth, ADR-031); never
taken from request data such as headers naming a user, tenant or role.
"""

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    # Granted permissions such as "tickets:read", derived from the role on each
    # request (app.core.roles). Anything not listed is denied.
    permissions: frozenset[str] = field(default_factory=frozenset)
    # The user's role; None for identities built by internal jobs (evaluation).
    role: str | None = None

    def can(self, permission: str) -> bool:
        return permission in self.permissions

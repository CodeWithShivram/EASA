"""The identity on whose behalf a request is served.

Until authentication exists (Phase 6) this is a development-only identity read
from server configuration (ADR-014). It is never taken from request data.
"""

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    # Granted permissions such as "tickets:read". Anything not listed is denied
    # (Phase 5 tools). Replaced by role-based access control in Phase 6.
    permissions: frozenset[str] = field(default_factory=frozenset)

    def can(self, permission: str) -> bool:
        return permission in self.permissions

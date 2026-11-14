"""The identity on whose behalf a request is served.

Until authentication exists (Phase 6) this is a development-only identity read
from server configuration (ADR-014). It is never taken from request data.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    tenant_id: uuid.UUID
    user_id: uuid.UUID

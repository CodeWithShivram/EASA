"""Registry of ORM models for Alembic autogenerate.

Import every model module here so its tables are registered on ``Base.metadata``.
"""

from app.db import accounts, audit, conversations, documents, embeddings, pending_actions, tickets
from app.db.base import Base

__all__ = [
    "Base",
    "accounts",
    "audit",
    "conversations",
    "documents",
    "embeddings",
    "pending_actions",
    "tickets",
]

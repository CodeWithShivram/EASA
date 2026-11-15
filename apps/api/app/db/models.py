"""Registry of ORM models for Alembic autogenerate.

Import every model module here so its tables are registered on ``Base.metadata``.
"""

from app.db import audit, conversations, documents, embeddings, tickets
from app.db.base import Base

__all__ = ["Base", "audit", "conversations", "documents", "embeddings", "tickets"]

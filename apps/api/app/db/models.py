"""Registry of ORM models for Alembic autogenerate.

Import every model module here so its tables are registered on ``Base.metadata``.
"""

from app.db import conversations, documents, embeddings
from app.db.base import Base

__all__ = ["Base", "conversations", "documents", "embeddings"]

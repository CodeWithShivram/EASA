"""Registry of ORM models for Alembic autogenerate.

Import every model module here. Intentionally empty in Phase 1: no domain
tables are defined until their requirements are understood.
"""

from app.db.base import Base

__all__ = ["Base"]

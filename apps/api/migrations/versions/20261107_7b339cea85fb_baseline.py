"""baseline

Intentionally empty starting point for the migration history. No domain
tables exist in Phase 1; later migrations build on this revision.

Revision ID: 7b339cea85fb
Revises:
Create Date: 2026-11-07 19:36:49.041883

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7b339cea85fb"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema changes in the baseline."""


def downgrade() -> None:
    """No schema changes in the baseline."""

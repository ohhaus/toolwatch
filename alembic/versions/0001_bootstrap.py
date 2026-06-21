"""Bootstrap migration metadata.

Revision ID: 0001_bootstrap
Revises:
Create Date: 2026-06-22
"""

from collections.abc import Sequence

revision: str = "0001_bootstrap"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the bootstrap revision without creating domain tables."""


def downgrade() -> None:
    """Remove the bootstrap revision marker."""

"""Add audit correlation identifiers.

Revision ID: 0005_observability_v1
Revises: 0004_security_pipeline_v1
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_observability_v1"
down_revision: str | Sequence[str] | None = "0004_security_pipeline_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bounded queryable audit correlation fields."""

    op.add_column(
        "audit_events",
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_audit_events_trace_id",
        "audit_events",
        ["trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_correlation_id",
        "audit_events",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove audit correlation indexes and field."""

    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_trace_id", table_name="audit_events")
    op.drop_column("audit_events", "correlation_id")

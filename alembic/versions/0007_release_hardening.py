"""Add indexes for bounded stale-execution recovery.

Revision ID: 0007_release_hardening
Revises: 0006_ollama_agent_loop_v1
Create Date: 2026-06-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_release_hardening"
down_revision: str | Sequence[str] | None = "0006_ollama_agent_loop_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add composite status/time indexes used by recovery workers."""

    op.create_index(
        "ix_tool_calls_status_updated_at",
        "tool_calls",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_status_updated_at",
        "agent_runs",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_model_calls_status_started_at",
        "model_calls",
        ["status", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove recovery indexes."""

    op.drop_index("ix_model_calls_status_started_at", table_name="model_calls")
    op.drop_index("ix_agent_runs_status_updated_at", table_name="agent_runs")
    op.drop_index("ix_tool_calls_status_updated_at", table_name="tool_calls")

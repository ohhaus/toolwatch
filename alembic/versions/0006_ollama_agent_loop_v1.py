"""Add safe Ollama Agent Loop v1 persistence.

Revision ID: 0006_ollama_agent_loop_v1
Revises: 0005_observability_v1
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_ollama_agent_loop_v1"
down_revision: str | Sequence[str] | None = "0005_observability_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create safe run/model metadata and link mediated tool calls."""

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("final_answer_redacted", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('created', 'running', 'completed', 'failed', 'cancelled', 'limit_reached')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint("turn_count >= 0", name="ck_agent_runs_turn_count_nonnegative"),
        sa.CheckConstraint(
            "tool_call_count >= 0", name="ck_agent_runs_tool_call_count_nonnegative"
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled', 'limit_reached') "
            "AND finished_at IS NOT NULL) OR "
            "(status IN ('created', 'running') AND finished_at IS NULL)",
            name="ck_agent_runs_status_finished_at",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name="fk_agent_runs_session_id_agent_sessions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"], unique=False)
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"], unique=False)
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"], unique=False)
    op.create_index(
        "ix_agent_runs_provider_model",
        "agent_runs",
        ["provider", "model_name"],
        unique=False,
    )

    op.create_table(
        "model_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_tool_count", sa.Integer(), nullable=False),
        sa.Column("prompt_token_count", sa.Integer(), nullable=True),
        sa.Column("completion_token_count", sa.Integer(), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("load_duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'timed_out')",
            name="ck_model_calls_status",
        ),
        sa.CheckConstraint("turn_number > 0", name="ck_model_calls_turn_positive"),
        sa.CheckConstraint(
            "requested_tool_count >= 0",
            name="ck_model_calls_requested_tools_nonnegative",
        ),
        sa.CheckConstraint(
            "(status = 'started' AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed', 'timed_out') AND finished_at IS NOT NULL)",
            name="ck_model_calls_status_finished_at",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name="fk_model_calls_agent_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_calls"),
        sa.UniqueConstraint("agent_run_id", "turn_number", name="uq_model_calls_run_turn"),
    )
    op.create_index("ix_model_calls_agent_run_id", "model_calls", ["agent_run_id"], unique=False)
    op.create_index(
        "ix_model_calls_provider_model",
        "model_calls",
        ["provider", "model_name"],
        unique=False,
    )

    op.add_column(
        "tool_calls",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tool_calls_agent_run_id_agent_runs",
        "tool_calls",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tool_calls_agent_run_id", "tool_calls", ["agent_run_id"], unique=False)


def downgrade() -> None:
    """Remove agent-loop persistence in dependency order."""

    op.drop_index("ix_tool_calls_agent_run_id", table_name="tool_calls")
    op.drop_constraint("fk_tool_calls_agent_run_id_agent_runs", "tool_calls", type_="foreignkey")
    op.drop_column("tool_calls", "agent_run_id")

    op.drop_index("ix_model_calls_provider_model", table_name="model_calls")
    op.drop_index("ix_model_calls_agent_run_id", table_name="model_calls")
    op.drop_table("model_calls")

    op.drop_index("ix_agent_runs_provider_model", table_name="agent_runs")
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_session_id", table_name="agent_runs")
    op.drop_table("agent_runs")

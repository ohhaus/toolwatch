"""Create tool-call execution lifecycle tables.

Revision ID: 0003_tool_call_execution
Revises: 0002_tool_registry_and_sessions
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_tool_call_execution"
down_revision: str | Sequence[str] | None = "0002_tool_registry_and_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create payload-free tool-call lifecycle persistence."""

    op.create_table(
        "tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message_safe", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('allow', 'reject')",
            name="ck_tool_calls_decision",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_tool_calls_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="ck_tool_calls_sequence_positive",
        ),
        sa.CheckConstraint(
            "status IN ('received', 'validating', 'rejected', 'executing', "
            "'succeeded', 'failed', 'timed_out')",
            name="ck_tool_calls_status",
        ),
        sa.CheckConstraint(
            "(status = 'rejected' AND decision = 'reject') OR "
            "(status <> 'rejected' AND decision = 'allow')",
            name="ck_tool_calls_status_decision",
        ),
        sa.CheckConstraint(
            "(status IN ('rejected', 'succeeded', 'failed', 'timed_out') "
            "AND finished_at IS NOT NULL) OR "
            "(status IN ('received', 'validating', 'executing') AND finished_at IS NULL)",
            name="ck_tool_calls_status_finished_at",
        ),
        sa.ForeignKeyConstraint(
            ["parent_call_id"],
            ["tool_calls.id"],
            name="fk_tool_calls_parent_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name="fk_tool_calls_session_id_agent_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tool_definition_id"],
            ["tool_definitions.id"],
            name="fk_tool_calls_tool_definition_id_tool_definitions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
        sa.UniqueConstraint("idempotency_key", name="uq_tool_calls_idempotency_key"),
        sa.UniqueConstraint(
            "session_id",
            "sequence_number",
            name="uq_tool_calls_session_sequence",
        ),
    )
    op.create_index("ix_tool_calls_created_at", "tool_calls", ["created_at"], unique=False)
    op.create_index("ix_tool_calls_session_id", "tool_calls", ["session_id"], unique=False)
    op.create_index("ix_tool_calls_status", "tool_calls", ["status"], unique=False)
    op.create_index(
        "ix_tool_calls_tool_definition_id",
        "tool_calls",
        ["tool_definition_id"],
        unique=False,
    )

    op.create_table(
        "tool_result_metadata",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("schema_valid", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_tool_result_metadata_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["tool_calls.id"],
            name="fk_tool_result_metadata_tool_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_result_metadata"),
        sa.UniqueConstraint(
            "tool_call_id",
            name="uq_tool_result_metadata_tool_call_id",
        ),
    )


def downgrade() -> None:
    """Drop execution persistence in dependency order."""

    op.drop_table("tool_result_metadata")
    op.drop_index("ix_tool_calls_tool_definition_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_status", table_name="tool_calls")
    op.drop_index("ix_tool_calls_session_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_created_at", table_name="tool_calls")
    op.drop_table("tool_calls")

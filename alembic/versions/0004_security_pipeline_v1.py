"""Add deterministic security pipeline persistence.

Revision ID: 0004_security_pipeline_v1
Revises: 0003_tool_call_execution
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_security_pipeline_v1"
down_revision: str | Sequence[str] | None = "0003_tool_call_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sanitized payloads, rules, flags, and audit events."""

    op.add_column(
        "tool_calls",
        sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="low"),
    )
    op.add_column(
        "tool_calls",
        sa.Column(
            "matched_rule_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "tool_calls",
        sa.Column(
            "redacted_arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.drop_constraint("ck_tool_calls_status", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_decision", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_status_finished_at", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_status_decision", "tool_calls", type_="check")
    op.create_check_constraint(
        "ck_tool_calls_status",
        "tool_calls",
        "status IN ('received', 'validating', 'rejected', 'evaluating', 'blocked', "
        "'executing', 'succeeded', 'failed', 'timed_out')",
    )
    op.create_check_constraint(
        "ck_tool_calls_decision",
        "tool_calls",
        "decision IN ('allow', 'flag', 'block', 'reject')",
    )
    op.create_check_constraint(
        "ck_tool_calls_risk_level",
        "tool_calls",
        "risk_level IN ('low', 'medium', 'high', 'critical')",
    )
    op.create_check_constraint(
        "ck_tool_calls_status_finished_at",
        "tool_calls",
        "(status IN ('rejected', 'blocked', 'succeeded', 'failed', 'timed_out') "
        "AND finished_at IS NOT NULL) OR "
        "(status IN ('received', 'validating', 'evaluating', 'executing') "
        "AND finished_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_tool_calls_status_decision",
        "tool_calls",
        "(status = 'rejected' AND decision = 'reject') OR "
        "(status = 'blocked' AND decision = 'block') OR "
        "(status NOT IN ('rejected', 'blocked') AND decision IN ('allow', 'flag'))",
    )

    op.add_column(
        "tool_result_metadata",
        sa.Column(
            "redacted_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'null'::jsonb"),
        ),
    )
    op.add_column(
        "tool_result_metadata",
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("tool_calls", "risk_level", server_default=None)
    op.alter_column("tool_calls", "matched_rule_ids", server_default=None)
    op.alter_column("tool_calls", "redacted_arguments", server_default=None)
    op.alter_column("tool_result_metadata", "redacted_payload", server_default=None)
    op.alter_column("tool_result_metadata", "truncated", server_default=None)

    op.create_table(
        "blocking_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("tool_pattern", sa.String(length=255), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('allow', 'flag', 'block')",
            name="ck_blocking_rules_action",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_blocking_rules"),
        sa.UniqueConstraint("name", name="uq_blocking_rules_name"),
    )
    op.create_index(
        "ix_blocking_rules_enabled_priority",
        "blocking_rules",
        ["enabled", "priority"],
        unique=False,
    )

    op.create_table(
        "risk_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("safe_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_risk_flags_severity",
        ),
        sa.CheckConstraint("source IN ('input', 'output')", name="ck_risk_flags_source"),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["tool_calls.id"],
            name="fk_risk_flags_tool_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_risk_flags"),
    )
    op.create_index("ix_risk_flags_code", "risk_flags", ["code"], unique=False)
    op.create_index(
        "ix_risk_flags_tool_call_id",
        "risk_flags",
        ["tool_call_id"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("payload_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name="fk_audit_events_session_id_agent_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["tool_calls.id"],
            name="fk_audit_events_tool_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_events_event_type",
        "audit_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_session_id_created_at",
        "audit_events",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_tool_call_id_created_at",
        "audit_events",
        ["tool_call_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove security pipeline persistence and restore revision 0003 constraints."""

    op.drop_index("ix_audit_events_tool_call_id_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_session_id_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_risk_flags_tool_call_id", table_name="risk_flags")
    op.drop_index("ix_risk_flags_code", table_name="risk_flags")
    op.drop_table("risk_flags")
    op.drop_index("ix_blocking_rules_enabled_priority", table_name="blocking_rules")
    op.drop_table("blocking_rules")

    op.drop_column("tool_result_metadata", "truncated")
    op.drop_column("tool_result_metadata", "redacted_payload")
    op.execute(
        "UPDATE tool_calls SET status = 'failed', decision = 'allow' WHERE status = 'blocked'"
    )
    op.execute(
        "UPDATE tool_calls SET status = 'validating', decision = 'allow' "
        "WHERE status = 'evaluating'"
    )
    op.execute("UPDATE tool_calls SET decision = 'allow' WHERE decision = 'flag'")
    op.drop_constraint("ck_tool_calls_status_decision", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_status_finished_at", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_risk_level", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_decision", "tool_calls", type_="check")
    op.drop_constraint("ck_tool_calls_status", "tool_calls", type_="check")
    op.create_check_constraint(
        "ck_tool_calls_status",
        "tool_calls",
        "status IN ('received', 'validating', 'rejected', 'executing', "
        "'succeeded', 'failed', 'timed_out')",
    )
    op.create_check_constraint(
        "ck_tool_calls_decision",
        "tool_calls",
        "decision IN ('allow', 'reject')",
    )
    op.create_check_constraint(
        "ck_tool_calls_status_finished_at",
        "tool_calls",
        "(status IN ('rejected', 'succeeded', 'failed', 'timed_out') "
        "AND finished_at IS NOT NULL) OR "
        "(status IN ('received', 'validating', 'executing') AND finished_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_tool_calls_status_decision",
        "tool_calls",
        "(status = 'rejected' AND decision = 'reject') OR "
        "(status <> 'rejected' AND decision = 'allow')",
    )
    op.drop_column("tool_calls", "redacted_arguments")
    op.drop_column("tool_calls", "matched_rule_ids")
    op.drop_column("tool_calls", "risk_level")

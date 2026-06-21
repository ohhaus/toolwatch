"""Create the tool registry and agent session tables.

Revision ID: 0002_tool_registry_and_sessions
Revises: 0001_bootstrap
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_tool_registry_and_sessions"
down_revision: str | Sequence[str] | None = "0001_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create trusted registry and session persistence."""

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=True),
        sa.Column("version_key", sa.String(length=255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_agents_name_nonempty"),
        sa.CheckConstraint("length(btrim(provider)) > 0", name="ck_agents_provider_nonempty"),
        sa.CheckConstraint(
            "length(btrim(model_name)) > 0",
            name="ck_agents_model_name_nonempty",
        ),
        sa.CheckConstraint(
            "version_key = coalesce(version, '')",
            name="ck_agents_version_key_consistent",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
        sa.UniqueConstraint(
            "name",
            "provider",
            "model_name",
            "version_key",
            name="uq_agents_identity",
        ),
    )
    op.create_index(
        "ix_agents_identity_lookup",
        "agents",
        ["name", "provider", "model_name", "version_key"],
        unique=False,
    )

    op.create_table(
        "tool_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("base_risk_level", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("adapter_type", sa.String(length=100), nullable=False),
        sa.Column("adapter_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(adapter_type)) > 0",
            name="ck_tool_definitions_adapter_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_tool_definitions_name_nonempty",
        ),
        sa.CheckConstraint(
            "base_risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_tool_definitions_risk_level",
        ),
        sa.CheckConstraint(
            "length(btrim(version)) > 0",
            name="ck_tool_definitions_version_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_definitions"),
        sa.UniqueConstraint("name", "version", name="uq_tool_definitions_name_version"),
    )
    op.create_index(
        "ix_tool_definitions_enabled",
        "tool_definitions",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        "ix_tool_definitions_name",
        "tool_definitions",
        ["name"],
        unique=False,
    )
    op.create_index(
        "ix_tool_definitions_risk_level",
        "tool_definitions",
        ["base_risk_level"],
        unique=False,
    )

    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_session_id", sa.String(length=255), nullable=True),
        sa.Column("user_prompt_redacted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'failed')",
            name="ck_agent_sessions_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed') AND finished_at IS NOT NULL)",
            name="ck_agent_sessions_status_finished_at",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_sessions_agent_id_agents",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_sessions"),
    )
    op.create_index(
        "ix_agent_sessions_agent_id",
        "agent_sessions",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_started_at",
        "agent_sessions",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_status",
        "agent_sessions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Drop session and registry persistence in dependency order."""

    op.drop_index("ix_agent_sessions_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_started_at", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_agent_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")

    op.drop_index("ix_tool_definitions_risk_level", table_name="tool_definitions")
    op.drop_index("ix_tool_definitions_name", table_name="tool_definitions")
    op.drop_index("ix_tool_definitions_enabled", table_name="tool_definitions")
    op.drop_table("tool_definitions")

    op.drop_index("ix_agents_identity_lookup", table_name="agents")
    op.drop_table("agents")

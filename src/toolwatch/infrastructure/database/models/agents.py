"""SQLAlchemy persistence model for agents."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from toolwatch.infrastructure.database.base import Base


class AgentModel(Base):
    """Persisted logical agent identity."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "provider",
            "model_name",
            "version_key",
            name="uq_agents_identity",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_agents_name_nonempty"),
        CheckConstraint("length(btrim(provider)) > 0", name="ck_agents_provider_nonempty"),
        CheckConstraint("length(btrim(model_name)) > 0", name="ck_agents_model_name_nonempty"),
        CheckConstraint(
            "version_key = coalesce(version, '')",
            name="ck_agents_version_key_consistent",
        ),
        Index(
            "ix_agents_identity_lookup",
            "name",
            "provider",
            "model_name",
            "version_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunModel(Base):
    """Safe persisted agent-loop lifecycle."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'running', 'completed', 'failed', 'cancelled', 'limit_reached')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("turn_count >= 0", name="ck_agent_runs_turn_count_nonnegative"),
        CheckConstraint("tool_call_count >= 0", name="ck_agent_runs_tool_call_count_nonnegative"),
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled', 'limit_reached') "
            "AND finished_at IS NOT NULL) OR "
            "(status IN ('created', 'running') AND finished_at IS NULL)",
            name="ck_agent_runs_status_finished_at",
        ),
        Index("ix_agent_runs_session_id", "session_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_started_at", "started_at"),
        Index("ix_agent_runs_status_updated_at", "status", "updated_at"),
        Index("ix_agent_runs_provider_model", "provider", "model_name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "agent_sessions.id",
            name="fk_agent_runs_session_id_agent_sessions",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False)
    final_answer_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelCallModel(Base):
    """Safe provider-call metadata without messages or responses."""

    __tablename__ = "model_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'timed_out')",
            name="ck_model_calls_status",
        ),
        CheckConstraint("turn_number > 0", name="ck_model_calls_turn_positive"),
        CheckConstraint(
            "requested_tool_count >= 0",
            name="ck_model_calls_requested_tools_nonnegative",
        ),
        CheckConstraint(
            "(status = 'started' AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed', 'timed_out') AND finished_at IS NOT NULL)",
            name="ck_model_calls_status_finished_at",
        ),
        UniqueConstraint("agent_run_id", "turn_number", name="uq_model_calls_run_turn"),
        Index("ix_model_calls_agent_run_id", "agent_run_id"),
        Index("ix_model_calls_provider_model", "provider", "model_name"),
        Index("ix_model_calls_status_started_at", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "agent_runs.id",
            name="fk_model_calls_agent_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_tool_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

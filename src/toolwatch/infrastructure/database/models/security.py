"""SQLAlchemy persistence for rules, flags, and append-only audit events."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
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


class RiskFlagModel(Base):
    """Persisted safe risk flag."""

    __tablename__ = "risk_flags"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_risk_flags_severity",
        ),
        CheckConstraint("source IN ('input', 'output')", name="ck_risk_flags_source"),
        Index("ix_risk_flags_tool_call_id", "tool_call_id"),
        Index("ix_risk_flags_code", "code"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tool_call_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "tool_calls.id",
            name="fk_risk_flags_tool_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    safe_evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlockingRuleModel(Base):
    """Persisted deterministic runtime rule."""

    __tablename__ = "blocking_rules"
    __table_args__ = (
        UniqueConstraint("name", name="uq_blocking_rules_name"),
        CheckConstraint(
            "action IN ('allow', 'flag', 'block')",
            name="ck_blocking_rules_action",
        ),
        Index("ix_blocking_rules_enabled_priority", "enabled", "priority"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    conditions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventModel(Base):
    """Append-only sanitized audit event."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_session_id_created_at", "session_id", "created_at"),
        Index("ix_audit_events_tool_call_id_created_at", "tool_call_id", "created_at"),
        Index("ix_audit_events_event_type", "event_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "agent_sessions.id",
            name="fk_audit_events_session_id_agent_sessions",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "tool_calls.id",
            name="fk_audit_events_tool_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_redacted: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

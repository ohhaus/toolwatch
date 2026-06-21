"""SQLAlchemy persistence models for tool-call lifecycles and safe result metadata."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from toolwatch.infrastructure.database.base import Base


class ToolCallModel(Base):
    """Persisted tool-call lifecycle without raw arguments or result payload."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tool_calls_idempotency_key"),
        UniqueConstraint(
            "session_id",
            "sequence_number",
            name="uq_tool_calls_session_sequence",
        ),
        CheckConstraint(
            "status IN "
            "('received', 'validating', 'rejected', 'executing', 'succeeded', 'failed', "
            "'timed_out')",
            name="ck_tool_calls_status",
        ),
        CheckConstraint(
            "decision IN ('allow', 'reject')",
            name="ck_tool_calls_decision",
        ),
        CheckConstraint("sequence_number > 0", name="ck_tool_calls_sequence_positive"),
        CheckConstraint(
            "(status IN ('rejected', 'succeeded', 'failed', 'timed_out') "
            "AND finished_at IS NOT NULL) OR "
            "(status IN ('received', 'validating', 'executing') AND finished_at IS NULL)",
            name="ck_tool_calls_status_finished_at",
        ),
        CheckConstraint(
            "(status = 'rejected' AND decision = 'reject') OR "
            "(status <> 'rejected' AND decision = 'allow')",
            name="ck_tool_calls_status_decision",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_tool_calls_duration_nonnegative",
        ),
        Index("ix_tool_calls_session_id", "session_id"),
        Index("ix_tool_calls_status", "status"),
        Index("ix_tool_calls_created_at", "created_at"),
        Index("ix_tool_calls_tool_definition_id", "tool_definition_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "agent_sessions.id",
            name="fk_tool_calls_session_id_agent_sessions",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    tool_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "tool_definitions.id",
            name="fk_tool_calls_tool_definition_id_tool_definitions",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    parent_call_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "tool_calls.id",
            name="fk_tool_calls_parent_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolResultMetadataModel(Base):
    """One-to-one safe metadata for an adapter result."""

    __tablename__ = "tool_result_metadata"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_tool_result_metadata_tool_call_id"),
        CheckConstraint("size_bytes >= 0", name="ck_tool_result_metadata_size_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tool_call_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "tool_calls.id",
            name="fk_tool_result_metadata_tool_call_id_tool_calls",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

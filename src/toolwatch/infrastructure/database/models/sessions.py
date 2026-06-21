"""SQLAlchemy persistence model for agent sessions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from toolwatch.infrastructure.database.base import Base


class AgentSessionModel(Base):
    """Persisted agent session lifecycle."""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'failed')",
            name="ck_agent_sessions_status",
        ),
        CheckConstraint(
            "(status = 'active' AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed') AND finished_at IS NOT NULL)",
            name="ck_agent_sessions_status_finished_at",
        ),
        Index("ix_agent_sessions_agent_id", "agent_id"),
        Index("ix_agent_sessions_status", "status"),
        Index("ix_agent_sessions_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", name="fk_agent_sessions_agent_id_agents", ondelete="RESTRICT"),
        nullable=False,
    )
    external_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_prompt_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False)

"""SQLAlchemy persistence model for tool definitions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from toolwatch.infrastructure.database.base import Base


class ToolDefinitionModel(Base):
    """Persisted trusted tool registry entry."""

    __tablename__ = "tool_definitions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_tool_definitions_name_version"),
        CheckConstraint(
            "base_risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_tool_definitions_risk_level",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_tool_definitions_name_nonempty"),
        CheckConstraint("length(btrim(version)) > 0", name="ck_tool_definitions_version_nonempty"),
        CheckConstraint(
            "length(btrim(adapter_type)) > 0",
            name="ck_tool_definitions_adapter_type_nonempty",
        ),
        Index("ix_tool_definitions_enabled", "enabled"),
        Index("ix_tool_definitions_risk_level", "base_risk_level"),
        Index("ix_tool_definitions_name", "name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    base_risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    adapter_type: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

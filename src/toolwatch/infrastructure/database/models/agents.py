"""SQLAlchemy persistence model for agents."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint
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

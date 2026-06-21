"""Agent entities and identity values."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from toolwatch.domain.common import (
    JSONObject,
    empty_json_object,
    require_non_empty,
    require_utc,
    utc_now,
    validate_json_object,
)


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Stable logical identity used to reuse agents across sessions."""

    name: str
    provider: str
    model_name: str
    version: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.provider, "provider")
        require_non_empty(self.model_name, "model_name")
        if self.version is not None:
            require_non_empty(self.version, "version")


@dataclass(frozen=True, slots=True)
class Agent:
    """Framework-independent agent entity."""

    identity: AgentIdentity
    metadata: JSONObject = field(default_factory=empty_json_object)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", validate_json_object(self.metadata, "metadata"))
        require_utc(self.created_at, "created_at")

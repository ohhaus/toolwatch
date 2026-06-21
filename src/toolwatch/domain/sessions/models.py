"""Agent session entity and state machine."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from toolwatch.domain.common import (
    DomainValidationError,
    JSONObject,
    empty_json_object,
    require_non_empty,
    require_utc,
    utc_now,
    validate_json_object,
)


class SessionStatus(StrEnum):
    """Allowed agent session states."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentSession:
    """A lifecycle record for one agent interaction."""

    agent_id: UUID
    external_session_id: str | None = None
    user_prompt_redacted: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    metadata: JSONObject = field(default_factory=empty_json_object)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.external_session_id is not None:
            require_non_empty(self.external_session_id, "external_session_id")
        object.__setattr__(self, "metadata", validate_json_object(self.metadata, "metadata"))
        require_utc(self.started_at, "started_at")
        if self.status is SessionStatus.ACTIVE and self.finished_at is not None:
            raise DomainValidationError("active sessions cannot have finished_at")
        if self.status is not SessionStatus.ACTIVE and self.finished_at is None:
            raise DomainValidationError("terminal sessions require finished_at")
        if self.finished_at is not None:
            require_utc(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise DomainValidationError("finished_at must not precede started_at")

    def transition_to(
        self,
        status: SessionStatus,
        *,
        finished_at: datetime | None = None,
    ) -> "AgentSession":
        """Transition an active session to a terminal state."""

        if status is SessionStatus.ACTIVE:
            raise InvalidSessionTransition("sessions cannot transition to active")
        if self.status is status:
            return self
        if self.status is not SessionStatus.ACTIVE:
            raise InvalidSessionTransition(f"cannot transition {self.status} to {status}")
        return replace(self, status=status, finished_at=finished_at or utc_now())


class InvalidSessionTransition(DomainValidationError):
    """Raised when a session state transition is not permitted."""

"""Framework-independent tool-call execution entities."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from toolwatch.domain.common import (
    DomainValidationError,
    JSONValue,
    require_non_empty,
    require_utc,
    utc_now,
)


class ToolCallStatus(StrEnum):
    """Persisted execution lifecycle states."""

    RECEIVED = "received"
    VALIDATING = "validating"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        """Return whether no further state transition is allowed."""

        return self in {
            ToolCallStatus.REJECTED,
            ToolCallStatus.SUCCEEDED,
            ToolCallStatus.FAILED,
            ToolCallStatus.TIMED_OUT,
        }


class ToolCallDecision(StrEnum):
    """Current deterministic execution decision."""

    ALLOW = "allow"
    REJECT = "reject"


_ALLOWED_TRANSITIONS = {
    ToolCallStatus.RECEIVED: {ToolCallStatus.VALIDATING},
    ToolCallStatus.VALIDATING: {ToolCallStatus.REJECTED, ToolCallStatus.EXECUTING},
    ToolCallStatus.EXECUTING: {
        ToolCallStatus.SUCCEEDED,
        ToolCallStatus.FAILED,
        ToolCallStatus.TIMED_OUT,
    },
}


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One persisted tool-call execution lifecycle."""

    session_id: UUID
    tool_definition_id: UUID
    sequence_number: int
    arguments_hash: str
    request_hash: str
    idempotency_key: UUID
    parent_call_id: UUID | None = None
    status: ToolCallStatus = ToolCallStatus.RECEIVED
    decision: ToolCallDecision = ToolCallDecision.ALLOW
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message_safe: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise DomainValidationError("sequence_number must be positive")
        _require_sha256(self.arguments_hash, "arguments_hash")
        _require_sha256(self.request_hash, "request_hash")
        require_utc(self.created_at, "created_at")
        require_utc(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise DomainValidationError("updated_at must not precede created_at")
        if self.started_at is not None:
            require_utc(self.started_at, "started_at")
        if self.finished_at is not None:
            require_utc(self.finished_at, "finished_at")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise DomainValidationError("duration_ms must not be negative")
        if self.status.terminal != (self.finished_at is not None):
            raise DomainValidationError("terminal status and finished_at must be consistent")
        if self.status is ToolCallStatus.REJECTED and self.decision is not ToolCallDecision.REJECT:
            raise DomainValidationError("rejected calls require reject decision")
        if self.status is not ToolCallStatus.REJECTED and self.decision is ToolCallDecision.REJECT:
            raise DomainValidationError("reject decision is only valid for rejected calls")
        if self.error_code is not None:
            require_non_empty(self.error_code, "error_code")
        if self.error_message_safe is not None:
            require_non_empty(self.error_message_safe, "error_message_safe")

    def transition_to(
        self,
        status: ToolCallStatus,
        *,
        now: datetime | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> "ToolCall":
        """Apply one allowed lifecycle transition."""

        if self.status.terminal:
            raise InvalidToolCallTransition("terminal tool calls cannot transition")
        if status not in _ALLOWED_TRANSITIONS.get(self.status, set()):
            raise InvalidToolCallTransition(f"cannot transition {self.status} to {status}")

        changed_at = now or utc_now()
        require_utc(changed_at, "updated_at")
        started_at = self.started_at
        if status is ToolCallStatus.EXECUTING:
            started_at = changed_at

        finished_at = changed_at if status.terminal else None
        duration_ms = self.duration_ms
        if finished_at is not None and started_at is not None:
            duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))

        decision = (
            ToolCallDecision.REJECT if status is ToolCallStatus.REJECTED else ToolCallDecision.ALLOW
        )
        return replace(
            self,
            status=status,
            decision=decision,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            error_code=error_code,
            error_message_safe=error_message_safe,
            updated_at=changed_at,
        )


@dataclass(frozen=True, slots=True)
class ToolResultMetadata:
    """Safe persisted facts about a tool result, excluding its body."""

    tool_call_id: UUID
    payload_hash: str
    content_type: str
    size_bytes: int
    schema_valid: bool
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_sha256(self.payload_hash, "payload_hash")
        require_non_empty(self.content_type, "content_type")
        if self.size_bytes < 0:
            raise DomainValidationError("size_bytes must not be negative")
        require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AdapterExecutionResult:
    """Validated in-memory adapter output returned only to the direct caller."""

    payload: JSONValue
    metadata: ToolResultMetadata


class InvalidToolCallTransition(DomainValidationError):
    """Raised when a tool call violates its state machine."""


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DomainValidationError(f"{field_name} must be a lowercase SHA-256 hex digest")

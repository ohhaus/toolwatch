"""Framework-independent agent-loop values and provider contracts."""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from toolwatch.domain.common import (
    DomainValidationError,
    JSONObject,
    require_non_empty,
    require_utc,
    utc_now,
    validate_json_object,
)


class AgentRunStatus(StrEnum):
    """Persisted lifecycle states for one bounded agent run."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LIMIT_REACHED = "limit_reached"

    @property
    def terminal(self) -> bool:
        return self in {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.LIMIT_REACHED,
        }


class ModelCallStatus(StrEnum):
    """Safe persisted status for one provider request."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class AgentMessageRole(StrEnum):
    """Roles supported by the internal conversation representation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class RequestedToolCall:
    """One untrusted provider-requested function call."""

    name: str
    arguments: JSONObject
    provider_call_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        if self.provider_call_id is not None:
            require_non_empty(self.provider_call_id, "provider_call_id")
        object.__setattr__(self, "arguments", validate_json_object(self.arguments, "arguments"))


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """Bounded in-memory message; full histories are never persisted."""

    role: AgentMessageRole
    content: str | None = None
    tool_calls: tuple[RequestedToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.tool_call_id is not None:
            require_non_empty(self.tool_call_id, "tool_call_id")
        if self.role is AgentMessageRole.TOOL and self.tool_call_id is None:
            raise DomainValidationError("tool messages require tool_call_id")
        if self.role is not AgentMessageRole.ASSISTANT and self.tool_calls:
            raise DomainValidationError("only assistant messages may contain tool calls")


@dataclass(frozen=True, slots=True)
class ProviderToolDefinition:
    """Public provider-facing function schema without adapter internals."""

    name: str
    description: str
    parameters: JSONObject

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.description, "description")
        object.__setattr__(self, "parameters", validate_json_object(self.parameters, "parameters"))


@dataclass(frozen=True, slots=True)
class AgentProviderOptions:
    """Trusted provider request controls."""

    timeout_seconds: float
    think: bool = False
    keep_alive: str | None = None
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise DomainValidationError("timeout_seconds must be positive")
        if self.max_response_bytes < 1:
            raise DomainValidationError("max_response_bytes must be positive")
        if self.keep_alive is not None:
            require_non_empty(self.keep_alive, "keep_alive")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Optional safe usage metadata returned by a provider."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_duration_ms: int | None = None
    load_duration_ms: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
            ("total_duration_ms", self.total_duration_ms),
            ("load_duration_ms", self.load_duration_ms),
        ):
            if value is not None and value < 0:
                raise DomainValidationError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class AgentProviderResponse:
    """Provider-neutral response consumed by application orchestration."""

    content: str | None
    tool_calls: tuple[RequestedToolCall, ...] = ()
    usage: ModelUsage = field(default_factory=ModelUsage)
    response_model: str | None = None
    thinking: str | None = None


class AgentProvider(Protocol):
    """Complete one model turn without executing tools."""

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[AgentMessage],
        tools: Sequence[ProviderToolDefinition],
        options: AgentProviderOptions,
    ) -> AgentProviderResponse: ...


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Safe persisted lifecycle metadata for one agent loop."""

    session_id: UUID
    provider: str
    model_name: str
    status: AgentRunStatus = AgentRunStatus.CREATED
    turn_count: int = 0
    tool_call_count: int = 0
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    final_answer_redacted: str | None = None
    error_code: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_non_empty(self.provider, "provider")
        require_non_empty(self.model_name, "model_name")
        if self.turn_count < 0 or self.tool_call_count < 0:
            raise DomainValidationError("agent run counters must not be negative")
        for name, value in (
            ("started_at", self.started_at),
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            require_utc(value, name)
        if self.finished_at is not None:
            require_utc(self.finished_at, "finished_at")
        if self.status.terminal != (self.finished_at is not None):
            raise DomainValidationError("terminal agent run and finished_at must be consistent")
        if self.status is AgentRunStatus.COMPLETED and self.error_code is not None:
            raise DomainValidationError("completed agent run cannot have error_code")

    def start(self, *, now: datetime | None = None) -> "AgentRun":
        if self.status is not AgentRunStatus.CREATED:
            raise InvalidAgentRunTransition("only created runs can start")
        changed_at = now or utc_now()
        return replace(self, status=AgentRunStatus.RUNNING, updated_at=changed_at)

    def progress(self, *, turn_count: int, tool_call_count: int) -> "AgentRun":
        if self.status is not AgentRunStatus.RUNNING:
            raise InvalidAgentRunTransition("only running runs can progress")
        return replace(
            self,
            turn_count=turn_count,
            tool_call_count=tool_call_count,
            updated_at=utc_now(),
        )

    def finish(
        self,
        status: AgentRunStatus,
        *,
        final_answer_redacted: str | None = None,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> "AgentRun":
        if self.status is not AgentRunStatus.RUNNING:
            raise InvalidAgentRunTransition("only running runs can finish")
        if not status.terminal:
            raise InvalidAgentRunTransition("finish requires a terminal status")
        changed_at = now or utc_now()
        return replace(
            self,
            status=status,
            final_answer_redacted=final_answer_redacted,
            error_code=error_code,
            finished_at=changed_at,
            updated_at=changed_at,
        )


@dataclass(frozen=True, slots=True)
class ModelCall:
    """Safe metadata for one provider call without conversation content."""

    agent_run_id: UUID
    turn_number: int
    provider: str
    model_name: str
    status: ModelCallStatus = ModelCallStatus.STARTED
    requested_tool_count: int = 0
    prompt_token_count: int | None = None
    completion_token_count: int | None = None
    total_duration_ms: int | None = None
    load_duration_ms: int | None = None
    error_code: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.turn_number < 1:
            raise DomainValidationError("turn_number must be positive")
        if self.requested_tool_count < 0:
            raise DomainValidationError("requested_tool_count must not be negative")
        require_non_empty(self.provider, "provider")
        require_non_empty(self.model_name, "model_name")
        require_utc(self.started_at, "started_at")
        if self.finished_at is not None:
            require_utc(self.finished_at, "finished_at")
        if (self.status is ModelCallStatus.STARTED) != (self.finished_at is None):
            raise DomainValidationError("model call status and finished_at are inconsistent")


@dataclass(frozen=True, slots=True)
class AgentToolCallSummary:
    """Safe tool-call facts returned by the agent API."""

    call_id: UUID | None
    tool: str
    status: str
    decision: str | None = None
    risk: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    """Safe synchronous result of a bounded run."""

    run: AgentRun
    tool_calls: tuple[AgentToolCallSummary, ...]


class InvalidAgentRunTransition(DomainValidationError):
    """Raised when an agent run violates its lifecycle."""

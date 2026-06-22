"""Application-facing persistence ports."""

from builtins import list as list_type
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from toolwatch.domain.agents import Agent, AgentIdentity, AgentRun, AgentRunStatus, ModelCall
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    BlockingRule,
    RiskFlag,
)
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tool_calls import ToolCall, ToolCallStatus, ToolResultMetadata
from toolwatch.domain.tools import RiskLevel, ToolDefinition


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One deterministic page of domain entities."""

    items: list[T]
    total: int
    limit: int
    offset: int


class RepositoryConflict(Exception):
    """A named persistence constraint rejected a write."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


class AgentRepository(Protocol):
    """Persistence operations required for agents."""

    async def get_by_id(self, agent_id: UUID) -> Agent | None: ...

    async def find_by_identity(self, identity: AgentIdentity) -> Agent | None: ...

    async def create(self, agent: Agent) -> Agent: ...


class ToolRepository(Protocol):
    """Persistence operations required for the trusted tool registry."""

    async def get_by_id(self, tool_id: UUID) -> ToolDefinition | None: ...

    async def get_by_name_and_version(self, name: str, version: str) -> ToolDefinition | None: ...

    async def list(
        self,
        *,
        enabled: bool | None,
        risk_level: RiskLevel | None,
        name: str | None,
        limit: int,
        offset: int,
    ) -> Page[ToolDefinition]: ...

    async def create(self, tool: ToolDefinition) -> ToolDefinition: ...

    async def set_enabled(self, tool: ToolDefinition) -> ToolDefinition: ...


class SessionRepository(Protocol):
    """Persistence operations required for agent sessions."""

    async def get_by_id(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentSession | None: ...

    async def list(
        self,
        *,
        agent_id: UUID | None,
        status: SessionStatus | None,
        limit: int,
        offset: int,
    ) -> Page[AgentSession]: ...

    async def create(self, session: AgentSession) -> AgentSession: ...

    async def update_status(self, session: AgentSession) -> AgentSession: ...


class ToolCallRepository(Protocol):
    """Persistence operations required for tool-call execution."""

    async def get_by_id(self, call_id: UUID) -> ToolCall | None: ...

    async def get_by_idempotency_key(self, key: UUID) -> ToolCall | None: ...

    async def list(
        self,
        *,
        session_id: UUID,
        status: ToolCallStatus | None,
        limit: int,
        offset: int,
    ) -> Page[ToolCall]: ...

    async def list_for_agent_run(self, agent_run_id: UUID) -> list_type[ToolCall]: ...

    async def next_sequence_number(self, session_id: UUID) -> int: ...

    async def create(self, call: ToolCall) -> ToolCall: ...

    async def update(self, call: ToolCall) -> ToolCall: ...


class ToolResultMetadataRepository(Protocol):
    """Persistence operations for safe result metadata."""

    async def get_by_tool_call_id(self, call_id: UUID) -> ToolResultMetadata | None: ...

    async def create(self, metadata: ToolResultMetadata) -> ToolResultMetadata: ...


class RiskFlagRepository(Protocol):
    """Persistence operations for safe risk flags."""

    async def list_for_tool_call(self, call_id: UUID) -> list[RiskFlag]: ...

    async def create_many(self, flags: list[RiskFlag]) -> list[RiskFlag]: ...


class BlockingRuleRepository(Protocol):
    """Persistence operations for deterministic runtime rules."""

    async def get_by_id(self, rule_id: UUID) -> BlockingRule | None: ...

    async def list(
        self,
        *,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[BlockingRule]: ...

    async def list_enabled(self) -> list_type[BlockingRule]: ...

    async def create(self, rule: BlockingRule) -> BlockingRule: ...

    async def update(self, rule: BlockingRule) -> BlockingRule: ...


class AuditEventRepository(Protocol):
    """Append-only persistence operations for sanitized audit events."""

    async def list(
        self,
        *,
        session_id: UUID | None,
        tool_call_id: UUID | None,
        event_type: AuditEventType | None,
        trace_id: str | None,
        correlation_id: str | None,
        limit: int,
        offset: int,
    ) -> Page[AuditEvent]: ...

    async def create(self, event: AuditEvent) -> AuditEvent: ...

    async def create_many(
        self,
        events: list_type[AuditEvent],
    ) -> list_type[AuditEvent]: ...


class AgentRunRepository(Protocol):
    """Persistence operations for bounded agent runs."""

    async def get_by_id(self, run_id: UUID) -> AgentRun | None: ...

    async def list(
        self,
        *,
        session_id: UUID | None,
        provider: str | None,
        model_name: str | None,
        status: AgentRunStatus | None,
        started_from: datetime | None,
        started_to: datetime | None,
        limit: int,
        offset: int,
    ) -> Page[AgentRun]: ...

    async def create(self, run: AgentRun) -> AgentRun: ...

    async def update(self, run: AgentRun) -> AgentRun: ...


class ModelCallRepository(Protocol):
    """Persistence operations for safe model-call metadata."""

    async def list_for_run(self, agent_run_id: UUID) -> list[ModelCall]: ...

    async def create(self, call: ModelCall) -> ModelCall: ...

    async def update(self, call: ModelCall) -> ModelCall: ...


class UnitOfWork(Protocol):
    """Transaction boundary owned by an application use case."""

    agents: AgentRepository
    tools: ToolRepository
    sessions: SessionRepository
    tool_calls: ToolCallRepository
    tool_results: ToolResultMetadataRepository
    risk_flags: RiskFlagRepository
    rules: BlockingRuleRepository
    audit_events: AuditEventRepository
    agent_runs: AgentRunRepository
    model_calls: ModelCallRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]

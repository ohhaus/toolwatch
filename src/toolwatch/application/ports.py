"""Application-facing persistence ports."""

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from toolwatch.domain.agents import Agent, AgentIdentity
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

    async def next_sequence_number(self, session_id: UUID) -> int: ...

    async def create(self, call: ToolCall) -> ToolCall: ...

    async def update(self, call: ToolCall) -> ToolCall: ...


class ToolResultMetadataRepository(Protocol):
    """Persistence operations for safe result metadata."""

    async def get_by_tool_call_id(self, call_id: UUID) -> ToolResultMetadata | None: ...

    async def create(self, metadata: ToolResultMetadata) -> ToolResultMetadata: ...


class UnitOfWork(Protocol):
    """Transaction boundary owned by an application use case."""

    agents: AgentRepository
    tools: ToolRepository
    sessions: SessionRepository
    tool_calls: ToolCallRepository
    tool_results: ToolResultMetadataRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]

"""Application use-case tests using in-memory repository fakes."""

from types import TracebackType
from typing import Self, cast
from uuid import UUID

import pytest

from toolwatch.application.errors import (
    InvalidSessionTransitionError,
    ToolVersionAlreadyExists,
)
from toolwatch.application.ports import (
    AgentRepository,
    AgentRunRepository,
    AuditEventRepository,
    BlockingRuleRepository,
    ModelCallRepository,
    Page,
    RepositoryConflict,
    RiskFlagRepository,
    SessionRepository,
    ToolCallRepository,
    ToolRepository,
    ToolResultMetadataRepository,
)
from toolwatch.application.sessions import CreateSession, SessionService
from toolwatch.application.tools import TOOL_UNIQUE_CONSTRAINT, ToolService
from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.security import AuditEvent
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tools import RiskLevel, ToolDefinition


class MemoryAgents:
    def __init__(self) -> None:
        self.items: dict[UUID, Agent] = {}

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        return self.items.get(agent_id)

    async def find_by_identity(self, identity: AgentIdentity) -> Agent | None:
        return next((item for item in self.items.values() if item.identity == identity), None)

    async def create(self, agent: Agent) -> Agent:
        existing = await self.find_by_identity(agent.identity)
        if existing is not None:
            return existing
        self.items[agent.id] = agent
        return agent


class MemoryTools:
    def __init__(self) -> None:
        self.items: dict[UUID, ToolDefinition] = {}

    async def get_by_id(self, tool_id: UUID) -> ToolDefinition | None:
        return self.items.get(tool_id)

    async def get_by_name_and_version(self, name: str, version: str) -> ToolDefinition | None:
        return next(
            (item for item in self.items.values() if (item.name, item.version) == (name, version)),
            None,
        )

    async def list(
        self,
        *,
        enabled: bool | None,
        risk_level: RiskLevel | None,
        name: str | None,
        limit: int,
        offset: int,
    ) -> Page[ToolDefinition]:
        values = [
            item
            for item in self.items.values()
            if (enabled is None or item.enabled is enabled)
            and (risk_level is None or item.base_risk_level is risk_level)
            and (name is None or item.name == name)
        ]
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def create(self, tool: ToolDefinition) -> ToolDefinition:
        if await self.get_by_name_and_version(tool.name, tool.version):
            raise RepositoryConflict(TOOL_UNIQUE_CONSTRAINT)
        self.items[tool.id] = tool
        return tool

    async def set_enabled(self, tool: ToolDefinition) -> ToolDefinition:
        self.items[tool.id] = tool
        return tool


class MemorySessions:
    def __init__(self) -> None:
        self.items: dict[UUID, AgentSession] = {}

    async def get_by_id(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentSession | None:
        del for_update
        return self.items.get(session_id)

    async def list(
        self,
        *,
        agent_id: UUID | None,
        status: SessionStatus | None,
        limit: int,
        offset: int,
    ) -> Page[AgentSession]:
        values = [
            item
            for item in self.items.values()
            if (agent_id is None or item.agent_id == agent_id)
            and (status is None or item.status is status)
        ]
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def create(self, session: AgentSession) -> AgentSession:
        self.items[session.id] = session
        return session

    async def update_status(self, session: AgentSession) -> AgentSession:
        self.items[session.id] = session
        return session


class MemoryUnitOfWork:
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

    def __init__(self) -> None:
        self.agents = MemoryAgents()
        self.tools = MemoryTools()
        self.sessions = MemorySessions()
        self.tool_calls = cast(ToolCallRepository, object())
        self.tool_results = cast(ToolResultMetadataRepository, object())
        self.risk_flags = cast(RiskFlagRepository, object())
        self.rules = cast(BlockingRuleRepository, object())
        self.audit_events = cast(AuditEventRepository, MemoryAuditEvents())
        self.agent_runs = cast(AgentRunRepository, object())
        self.model_calls = cast(ModelCallRepository, object())
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class MemoryAuditEvents:
    def __init__(self) -> None:
        self.items: list[AuditEvent] = []

    async def create(self, event: AuditEvent) -> AuditEvent:
        self.items.append(event)
        return event


def tool() -> ToolDefinition:
    return ToolDefinition(
        name="github.list_issues",
        description="List issues",
        version="1",
        input_schema={"type": "object"},
        output_schema=None,
        base_risk_level=RiskLevel.LOW,
        adapter_type="mock",
        adapter_config={},
    )


@pytest.mark.asyncio
async def test_register_tool_and_map_duplicate() -> None:
    uow = MemoryUnitOfWork()
    service = ToolService(lambda: uow)

    created = await service.register(tool())

    assert created.name == "github.list_issues"
    assert uow.commits == 1
    with pytest.raises(ToolVersionAlreadyExists):
        await service.register(tool())


@pytest.mark.asyncio
async def test_create_reuses_agent_and_session_completion_rules() -> None:
    uow = MemoryUnitOfWork()
    service = SessionService(lambda: uow)
    request = CreateSession(agent_identity=AgentIdentity("demo", "local", "model"))

    first = await service.create(request)
    second = await service.create(request)
    completed = await service.complete(first.session.id, SessionStatus.COMPLETED)
    repeated = await service.complete(first.session.id, SessionStatus.COMPLETED)

    assert first.agent.id == second.agent.id
    assert len(cast(MemoryAgents, uow.agents).items) == 1
    assert len(cast(MemorySessions, uow.sessions).items) == 2
    assert completed.session.status is SessionStatus.COMPLETED
    assert repeated.session == completed.session
    with pytest.raises(InvalidSessionTransitionError):
        await service.complete(first.session.id, SessionStatus.FAILED)

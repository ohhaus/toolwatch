"""Application tests for deterministic tool-call orchestration."""

import asyncio
from builtins import list as list_type
from collections.abc import Mapping
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from toolwatch.application.errors import (
    IdempotencyConflict,
    InvalidToolArguments,
    InvalidToolResult,
    ToolArgumentsTooLarge,
    ToolResultTooLarge,
    ToolTimeout,
)
from toolwatch.application.ports import Page, UnitOfWorkFactory
from toolwatch.application.tool_calls import (
    ExecuteToolCall,
    TerminalResponseCache,
    ToolCallService,
)
from toolwatch.config import Settings
from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.common import JSONValue
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    BlockingRule,
    RiskFlag,
)
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tool_calls import (
    ToolCall,
    ToolCallStatus,
    ToolExecutionContext,
    ToolResultMetadata,
)
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.infrastructure.adapters import AdapterRegistry


class MemoryState:
    def __init__(self) -> None:
        self.agents: dict[UUID, Agent] = {}
        self.sessions: dict[UUID, AgentSession] = {}
        self.tools: dict[UUID, ToolDefinition] = {}
        self.calls: dict[UUID, ToolCall] = {}
        self.results: dict[UUID, ToolResultMetadata] = {}
        self.flags: list[RiskFlag] = []
        self.rules: dict[UUID, BlockingRule] = {}
        self.audits: list[AuditEvent] = []


class MemoryAgents:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        return self.state.agents.get(agent_id)

    async def find_by_identity(self, identity: AgentIdentity) -> Agent | None:
        return next(
            (agent for agent in self.state.agents.values() if agent.identity == identity), None
        )

    async def create(self, agent: Agent) -> Agent:
        self.state.agents[agent.id] = agent
        return agent


class MemorySessions:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def get_by_id(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentSession | None:
        del for_update
        return self.state.sessions.get(session_id)

    async def list(
        self,
        *,
        agent_id: UUID | None,
        status: SessionStatus | None,
        limit: int,
        offset: int,
    ) -> Page[AgentSession]:
        del agent_id, status
        values = list(self.state.sessions.values())
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def create(self, session: AgentSession) -> AgentSession:
        self.state.sessions[session.id] = session
        return session

    async def update_status(self, session: AgentSession) -> AgentSession:
        self.state.sessions[session.id] = session
        return session


class MemoryTools:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def get_by_id(self, tool_id: UUID) -> ToolDefinition | None:
        return self.state.tools.get(tool_id)

    async def get_by_name_and_version(self, name: str, version: str) -> ToolDefinition | None:
        return next(
            (
                tool
                for tool in self.state.tools.values()
                if (tool.name, tool.version) == (name, version)
            ),
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
        del enabled, risk_level, name
        values = list(self.state.tools.values())
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def create(self, tool: ToolDefinition) -> ToolDefinition:
        self.state.tools[tool.id] = tool
        return tool

    async def set_enabled(self, tool: ToolDefinition) -> ToolDefinition:
        self.state.tools[tool.id] = tool
        return tool


class MemoryCalls:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def get_by_id(self, call_id: UUID) -> ToolCall | None:
        return self.state.calls.get(call_id)

    async def get_by_idempotency_key(self, key: UUID) -> ToolCall | None:
        return next(
            (call for call in self.state.calls.values() if call.idempotency_key == key), None
        )

    async def list(
        self,
        *,
        session_id: UUID,
        status: ToolCallStatus | None,
        limit: int,
        offset: int,
    ) -> Page[ToolCall]:
        values = sorted(
            (
                call
                for call in self.state.calls.values()
                if call.session_id == session_id and (status is None or call.status is status)
            ),
            key=lambda call: call.sequence_number,
        )
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def next_sequence_number(self, session_id: UUID) -> int:
        return (
            max(
                (
                    call.sequence_number
                    for call in self.state.calls.values()
                    if call.session_id == session_id
                ),
                default=0,
            )
            + 1
        )

    async def create(self, call: ToolCall) -> ToolCall:
        self.state.calls[call.id] = call
        return call

    async def update(self, call: ToolCall) -> ToolCall:
        self.state.calls[call.id] = call
        return call


class MemoryResults:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def get_by_tool_call_id(self, call_id: UUID) -> ToolResultMetadata | None:
        return self.state.results.get(call_id)

    async def create(self, metadata: ToolResultMetadata) -> ToolResultMetadata:
        self.state.results[metadata.tool_call_id] = metadata
        return metadata


class MemoryRiskFlags:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def list_for_tool_call(self, call_id: UUID) -> list[RiskFlag]:
        return [flag for flag in self.state.flags if flag.tool_call_id == call_id]

    async def create_many(self, flags: list[RiskFlag]) -> list[RiskFlag]:
        self.state.flags.extend(flags)
        return flags


class MemoryRules:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def get_by_id(self, rule_id: UUID) -> BlockingRule | None:
        return self.state.rules.get(rule_id)

    async def list(
        self,
        *,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[BlockingRule]:
        values = [
            rule for rule in self.state.rules.values() if enabled is None or rule.enabled is enabled
        ]
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def list_enabled(self) -> list_type[BlockingRule]:
        return [rule for rule in self.state.rules.values() if rule.enabled]

    async def create(self, rule: BlockingRule) -> BlockingRule:
        self.state.rules[rule.id] = rule
        return rule

    async def update(self, rule: BlockingRule) -> BlockingRule:
        self.state.rules[rule.id] = rule
        return rule


class MemoryAuditEvents:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    async def list(
        self,
        *,
        session_id: UUID | None,
        tool_call_id: UUID | None,
        event_type: AuditEventType | None,
        limit: int,
        offset: int,
    ) -> Page[AuditEvent]:
        values = [
            event
            for event in self.state.audits
            if (session_id is None or event.session_id == session_id)
            and (tool_call_id is None or event.tool_call_id == tool_call_id)
            and (event_type is None or event.event_type is event_type)
        ]
        return Page(values[offset : offset + limit], len(values), limit, offset)

    async def create(self, event: AuditEvent) -> AuditEvent:
        self.state.audits.append(event)
        return event

    async def create_many(
        self,
        events: list_type[AuditEvent],
    ) -> list_type[AuditEvent]:
        self.state.audits.extend(events)
        return events


class MemoryUow:
    def __init__(self, state: MemoryState) -> None:
        self.agents = MemoryAgents(state)
        self.sessions = MemorySessions(state)
        self.tools = MemoryTools(state)
        self.tool_calls = MemoryCalls(state)
        self.tool_results = MemoryResults(state)
        self.risk_flags = MemoryRiskFlags(state)
        self.rules = MemoryRules(state)
        self.audit_events = MemoryAuditEvents(state)

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
        return None


class CountingAdapter:
    def __init__(self, result: JSONValue, *, delay: float = 0) -> None:
        self.result = result
        self.delay = delay
        self.calls = 0

    async def execute(
        self,
        *,
        arguments: Mapping[str, JSONValue],
        context: ToolExecutionContext,
    ) -> JSONValue:
        del arguments, context
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


def setup_service(
    adapter: CountingAdapter,
    *,
    output_schema: dict[str, JSONValue] | None = None,
    timeout: float = 1,
    max_arguments_bytes: int = 65_536,
    max_result_bytes: int = 524_288,
) -> tuple[ToolCallService, MemoryState, AgentSession, ToolDefinition]:
    state = MemoryState()
    agent = Agent(identity=AgentIdentity("demo", "local", "model"))
    session = AgentSession(agent_id=agent.id)
    tool = ToolDefinition(
        name="demo.execute",
        description="Demo",
        version="1",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema=output_schema,
        base_risk_level=RiskLevel.LOW,
        adapter_type="test",
        adapter_config={},
    )
    state.agents[agent.id] = agent
    state.sessions[session.id] = session
    state.tools[tool.id] = tool
    service = ToolCallService(
        cast(UnitOfWorkFactory, lambda: MemoryUow(state)),
        AdapterRegistry({"test": adapter}),
        Settings(
            default_tool_timeout_seconds=timeout,
            max_tool_arguments_bytes=max_arguments_bytes,
            max_tool_result_bytes=max_result_bytes,
        ),
        TerminalResponseCache(),
    )
    return service, state, session, tool


@pytest.mark.asyncio
async def test_success_and_idempotent_retry_execute_once() -> None:
    adapter = CountingAdapter({"ok": True})
    service, state, session, _ = setup_service(adapter)
    key = uuid4()
    request = ExecuteToolCall(
        session_id=session.id,
        tool_name="demo.execute",
        tool_version="1",
        arguments={"value": "Bearer unit-secret-argument"},
        idempotency_key=key,
    )

    first = await service.execute(request)
    second = await service.execute(request)

    assert first.call.status is ToolCallStatus.SUCCEEDED
    assert second.replayed is True
    assert adapter.calls == 1
    assert len(state.calls) == 1
    assert all("unit-secret-argument" not in repr(item) for item in state.calls.values())


@pytest.mark.asyncio
async def test_invalid_arguments_do_not_reach_adapter() -> None:
    adapter = CountingAdapter({"ok": True})
    service, state, session, _ = setup_service(adapter)

    with pytest.raises(InvalidToolArguments):
        await service.execute(
            ExecuteToolCall(
                session_id=session.id,
                tool_name="demo.execute",
                tool_version="1",
                arguments={"wrong": "value"},
                idempotency_key=uuid4(),
            )
        )

    assert adapter.calls == 0
    assert next(iter(state.calls.values())).status is ToolCallStatus.REJECTED


@pytest.mark.asyncio
async def test_timeout_is_terminal() -> None:
    adapter = CountingAdapter({"ok": True}, delay=0.05)
    service, state, session, _ = setup_service(adapter, timeout=0.001)

    with pytest.raises(ToolTimeout):
        await service.execute(
            ExecuteToolCall(
                session_id=session.id,
                tool_name="demo.execute",
                tool_version="1",
                arguments={"value": "x"},
                idempotency_key=uuid4(),
            )
        )

    assert next(iter(state.calls.values())).status is ToolCallStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_invalid_output_is_not_returned() -> None:
    adapter = CountingAdapter({"raw_secret": "result-secret"})
    service, state, session, _ = setup_service(
        adapter,
        output_schema={
            "type": "object",
            "properties": {"ok": {"const": True}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    )

    with pytest.raises(InvalidToolResult):
        await service.execute(
            ExecuteToolCall(
                session_id=session.id,
                tool_name="demo.execute",
                tool_version="1",
                arguments={"value": "x"},
                idempotency_key=uuid4(),
            )
        )

    assert "result-secret" not in repr(state.calls)
    assert next(iter(state.calls.values())).status is ToolCallStatus.FAILED


@pytest.mark.asyncio
async def test_idempotency_key_conflict() -> None:
    service, _, session, _ = setup_service(CountingAdapter({"ok": True}))
    key = uuid4()
    await service.execute(
        ExecuteToolCall(
            session_id=session.id,
            tool_name="demo.execute",
            tool_version="1",
            arguments={"value": "first"},
            idempotency_key=key,
        )
    )

    with pytest.raises(IdempotencyConflict):
        await service.execute(
            ExecuteToolCall(
                session_id=session.id,
                tool_name="demo.execute",
                tool_version="1",
                arguments={"value": "second"},
                idempotency_key=key,
            )
        )


@pytest.mark.asyncio
async def test_oversized_arguments_do_not_execute() -> None:
    adapter = CountingAdapter({"ok": True})
    service, state, session, _ = setup_service(adapter, max_arguments_bytes=20)

    with pytest.raises(ToolArgumentsTooLarge):
        await service.execute(
            ExecuteToolCall(
                session_id=session.id,
                tool_name="demo.execute",
                tool_version="1",
                arguments={"value": "x" * 100},
                idempotency_key=uuid4(),
            )
        )

    assert adapter.calls == 0
    assert state.calls == {}


@pytest.mark.asyncio
async def test_oversized_result_is_failed_and_not_returned() -> None:
    adapter = CountingAdapter({"value": "x" * 100})
    service, state, session, _ = setup_service(adapter, max_result_bytes=20)

    with pytest.raises(ToolResultTooLarge):
        await service.execute(
            ExecuteToolCall(
                session_id=session.id,
                tool_name="demo.execute",
                tool_version="1",
                arguments={"value": "x"},
                idempotency_key=uuid4(),
            )
        )

    assert next(iter(state.calls.values())).status is ToolCallStatus.FAILED

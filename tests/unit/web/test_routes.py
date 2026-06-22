"""HTTP-level tests for the dashboard router."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from toolwatch.api.dependencies import get_uow_factory
from toolwatch.application.ports import (
    AgentRepository,
    AuditEventRepository,
    BlockingRuleRepository,
    Page,
    RiskFlagRepository,
    SessionRepository,
    ToolCallRepository,
    ToolRepository,
    ToolResultMetadataRepository,
)
from toolwatch.config import get_settings
from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    BlockingRule,
    RiskFlag,
    RiskFlagCode,
    RuleAction,
)
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tool_calls import (
    ToolCall,
    ToolCallDecision,
    ToolCallStatus,
    ToolResultMetadata,
)
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.main import create_app


def _empty_agents() -> dict[UUID, Agent]:
    return {}


def _empty_tools() -> dict[UUID, ToolDefinition]:
    return {}


def _empty_sessions() -> dict[UUID, AgentSession]:
    return {}


def _empty_calls() -> dict[UUID, ToolCall]:
    return {}


def _empty_results() -> dict[UUID, ToolResultMetadata]:
    return {}


def _empty_flags() -> dict[UUID, list[RiskFlag]]:
    return {}


def _empty_rules() -> dict[UUID, BlockingRule]:
    return {}


def _empty_audit() -> list[AuditEvent]:
    return []


@dataclass
class _State:
    agents: dict[UUID, Agent] = field(default_factory=_empty_agents)
    tools: dict[UUID, ToolDefinition] = field(default_factory=_empty_tools)
    sessions: dict[UUID, AgentSession] = field(default_factory=_empty_sessions)
    tool_calls: dict[UUID, ToolCall] = field(default_factory=_empty_calls)
    results: dict[UUID, ToolResultMetadata] = field(default_factory=_empty_results)
    flags: dict[UUID, list[RiskFlag]] = field(default_factory=_empty_flags)
    rules: dict[UUID, BlockingRule] = field(default_factory=_empty_rules)
    audit: list[AuditEvent] = field(default_factory=_empty_audit)


class _AgentRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        return self._state.agents.get(agent_id)

    async def find_by_identity(self, identity: object) -> Agent | None:  # pragma: no cover
        return None

    async def create(self, agent: Agent) -> Agent:  # pragma: no cover
        self._state.agents[agent.id] = agent
        return agent


class _ToolRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_by_id(self, tool_id: UUID) -> ToolDefinition | None:
        return self._state.tools.get(tool_id)

    async def get_by_name_and_version(
        self, name: str, version: str
    ) -> ToolDefinition | None:  # pragma: no cover
        for tool in self._state.tools.values():
            if tool.name == name and tool.version == version:
                return tool
        return None

    async def list(
        self,
        *,
        enabled: bool | None,
        risk_level: RiskLevel | None,
        name: str | None,
        limit: int,
        offset: int,
    ) -> Page[ToolDefinition]:  # pragma: no cover
        items = list(self._state.tools.values())
        return Page(items, len(items), limit, offset)

    async def create(self, tool: ToolDefinition) -> ToolDefinition:  # pragma: no cover
        self._state.tools[tool.id] = tool
        return tool

    async def set_enabled(self, tool: ToolDefinition) -> ToolDefinition:  # pragma: no cover
        self._state.tools[tool.id] = tool
        return tool


class _SessionRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_by_id(self, session_id: UUID, *, for_update: bool = False) -> AgentSession | None:
        return self._state.sessions.get(session_id)

    async def list(
        self,
        *,
        agent_id: UUID | None,
        status: SessionStatus | None,
        limit: int,
        offset: int,
    ) -> Page[AgentSession]:
        items = list(self._state.sessions.values())
        if agent_id is not None:
            items = [s for s in items if s.agent_id == agent_id]
        if status is not None:
            items = [s for s in items if s.status is status]
        items.sort(key=lambda s: s.started_at, reverse=True)
        return Page(items[offset : offset + limit], len(items), limit, offset)

    async def create(self, session: AgentSession) -> AgentSession:  # pragma: no cover
        self._state.sessions[session.id] = session
        return session

    async def update_status(self, session: AgentSession) -> AgentSession:  # pragma: no cover
        self._state.sessions[session.id] = session
        return session


class _ToolCallRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_by_id(self, call_id: UUID) -> ToolCall | None:
        return self._state.tool_calls.get(call_id)

    async def get_by_idempotency_key(self, key: UUID) -> ToolCall | None:  # pragma: no cover
        for call in self._state.tool_calls.values():
            if call.idempotency_key == key:
                return call
        return None

    async def list(
        self,
        *,
        session_id: UUID,
        status: ToolCallStatus | None,
        limit: int,
        offset: int,
    ) -> Page[ToolCall]:
        items = [call for call in self._state.tool_calls.values() if call.session_id == session_id]
        if status is not None:
            items = [call for call in items if call.status is status]
        items.sort(key=lambda c: c.sequence_number)
        return Page(items[offset : offset + limit], len(items), limit, offset)

    async def next_sequence_number(self, session_id: UUID) -> int:  # pragma: no cover
        return 1

    async def create(self, call: ToolCall) -> ToolCall:  # pragma: no cover
        self._state.tool_calls[call.id] = call
        return call

    async def update(self, call: ToolCall) -> ToolCall:  # pragma: no cover
        self._state.tool_calls[call.id] = call
        return call


class _ResultRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_by_tool_call_id(self, call_id: UUID) -> ToolResultMetadata | None:
        return self._state.results.get(call_id)

    async def create(self, metadata: ToolResultMetadata) -> ToolResultMetadata:  # pragma: no cover
        self._state.results[metadata.tool_call_id] = metadata
        return metadata


class _FlagRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def list_for_tool_call(self, call_id: UUID) -> list[RiskFlag]:
        return list(self._state.flags.get(call_id, []))

    async def create_many(self, flags: list[RiskFlag]) -> list[RiskFlag]:  # pragma: no cover
        return flags


class _RuleRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_by_id(self, rule_id: UUID) -> BlockingRule | None:
        return self._state.rules.get(rule_id)

    async def list(self, *, enabled: bool | None, limit: int, offset: int) -> Page[BlockingRule]:
        items = list(self._state.rules.values())
        if enabled is not None:
            items = [r for r in items if r.enabled is enabled]
        return Page(items[offset : offset + limit], len(items), limit, offset)

    async def list_enabled(self) -> list[BlockingRule]:  # pragma: no cover
        return [r for r in self._state.rules.values() if r.enabled]

    async def create(self, rule: BlockingRule) -> BlockingRule:  # pragma: no cover
        self._state.rules[rule.id] = rule
        return rule

    async def update(self, rule: BlockingRule) -> BlockingRule:  # pragma: no cover
        self._state.rules[rule.id] = rule
        return rule


class _AuditRepo:
    def __init__(self, state: _State) -> None:
        self._state = state

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
    ) -> Page[AuditEvent]:
        items = list(self._state.audit)
        if session_id is not None:
            items = [e for e in items if e.session_id == session_id]
        if tool_call_id is not None:
            items = [e for e in items if e.tool_call_id == tool_call_id]
        if event_type is not None:
            items = [e for e in items if e.event_type is event_type]
        if trace_id is not None:
            items = [e for e in items if e.trace_id == trace_id]
        if correlation_id is not None:
            items = [e for e in items if e.correlation_id == correlation_id]
        return Page(items[offset : offset + limit], len(items), limit, offset)

    async def create(self, event: AuditEvent) -> AuditEvent:  # pragma: no cover
        self._state.audit.append(event)
        return event

    async def create_many(self, events: list[AuditEvent]) -> list[AuditEvent]:  # pragma: no cover
        self._state.audit.extend(events)
        return events


class _Uow:
    def __init__(self, state: _State) -> None:
        self._state = state
        self.agents: AgentRepository = _AgentRepo(state)
        self.tools: ToolRepository = _ToolRepo(state)
        self.sessions: SessionRepository = _SessionRepo(state)
        self.tool_calls: ToolCallRepository = _ToolCallRepo(state)
        self.tool_results: ToolResultMetadataRepository = _ResultRepo(state)
        self.risk_flags: RiskFlagRepository = _FlagRepo(state)
        self.rules: BlockingRuleRepository = _RuleRepo(state)
        self.audit_events: AuditEventRepository = _AuditRepo(state)

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:  # pragma: no cover
        return None


def _build_state() -> _State:
    state = _State()
    agent = Agent(
        identity=AgentIdentity(
            name="dashboard-agent",
            provider="test",
            model_name="deterministic",
            version="1",
        ),
        metadata={},
    )
    state.agents[agent.id] = agent
    tool = ToolDefinition(
        name="github.list_issues",
        description="List issues.",
        version="1.0.0",
        input_schema={"type": "object", "properties": {"state": {"type": "string"}}},
        output_schema=None,
        base_risk_level=RiskLevel.LOW,
        adapter_type="mock_github",
        adapter_config={},
    )
    state.tools[tool.id] = tool
    session = AgentSession(agent_id=agent.id, status=SessionStatus.ACTIVE)
    state.sessions[session.id] = session
    base_call = ToolCall(
        session_id=session.id,
        tool_definition_id=tool.id,
        sequence_number=1,
        arguments_hash="a" * 64,
        request_hash="b" * 64,
        idempotency_key=uuid4(),
    )
    validating = base_call.transition_to(ToolCallStatus.VALIDATING)
    evaluating = validating.transition_to(
        ToolCallStatus.EVALUATING,
        decision=ToolCallDecision.ALLOW,
        risk_level=RiskLevel.LOW,
    )
    executing = evaluating.transition_to(ToolCallStatus.EXECUTING)
    call = executing.transition_to(ToolCallStatus.SUCCEEDED)
    state.tool_calls[call.id] = call
    state.results[call.id] = ToolResultMetadata(
        tool_call_id=call.id,
        redacted_payload={"input": "<script>alert('xss')</script>"},
        payload_hash="c" * 64,
        content_type="application/json",
        size_bytes=10,
        schema_valid=True,
    )
    flag = RiskFlag(
        code=RiskFlagCode.SENSITIVE_INPUT,
        severity=RiskLevel.HIGH,
        message="Sensitive input found.",
        safe_evidence={"label": "<img src=x onerror=alert(1)>"},
        tool_call_id=call.id,
    )
    state.flags[call.id] = [flag]
    state.audit.append(
        AuditEvent(
            session_id=session.id,
            tool_call_id=call.id,
            event_type=AuditEventType.TOOL_CALL_COMPLETED,
            payload_redacted={"status": "succeeded"},
            trace_id="0123456789abcdef0123456789abcdef",
            correlation_id=str(uuid4()),
        )
    )
    state.rules[uuid4()] = BlockingRule(
        name="block-destructive-sql",
        description="Block destructive SQL.",
        enabled=True,
        priority=100,
        tool_pattern="database.query",
        conditions={"has_flag": "destructive_sql"},
        action=RuleAction.BLOCK,
    )
    return state


@pytest.fixture
def app_with_fake_state(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _State]:
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    monkeypatch.setenv("ATTACK_LAB_ENABLED", "true")
    monkeypatch.setenv("JAEGER_UI_PUBLIC_URL", "http://localhost:16686")
    get_settings.cache_clear()
    application = create_app()
    state = _build_state()
    application.dependency_overrides[get_uow_factory] = lambda: lambda: _Uow(state)
    return application, state


@asynccontextmanager
async def _client(app: Any) -> AsyncGenerator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_dashboard_home_renders_summary_and_sets_security_headers(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response = await client.get("/ui")

    assert response.status_code == 200
    assert "Dashboard" in response.text
    csp = response.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_sessions_list_supports_status_filter(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response = await client.get("/ui/sessions?status=active&limit=10")
        fragment = await client.get("/ui/sessions/table?status=active&limit=10")

    assert response.status_code == 200
    assert "dashboard-agent" in response.text
    assert fragment.status_code == 200
    assert "data-table" in fragment.text


@pytest.mark.asyncio
async def test_session_detail_includes_call_and_audit_timeline(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, state = app_with_fake_state
    session_id = next(iter(state.sessions))
    async with _client(application) as client:
        response = await client.get(f"/ui/sessions/{session_id}")

    assert response.status_code == 200
    assert "github.list_issues" in response.text
    assert "tool_call.completed" in response.text


@pytest.mark.asyncio
async def test_tool_call_detail_escapes_xss_and_links_jaeger(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, state = app_with_fake_state
    call_id = next(iter(state.tool_calls))
    async with _client(application) as client:
        response = await client.get(f"/ui/tool-calls/{call_id}")

    assert response.status_code == 200
    body = response.text
    # Raw <script> from the sanitized result must NOT remain executable.
    assert "<script>alert('xss')</script>" not in body
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in body or (
        "&lt;script&gt;alert('xss')&lt;/script&gt;" in body
    )
    # Risk flag evidence is also escaped.
    assert "<img src=x onerror" not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body
    # Jaeger trace ID link is rendered with the configured base URL.
    assert "http://localhost:16686/trace/0123456789abcdef0123456789abcdef" in body
    assert 'rel="noopener noreferrer"' in body


@pytest.mark.asyncio
async def test_rules_list_renders_safe_condition_summary(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response = await client.get("/ui/rules")

    assert response.status_code == 200
    assert "block-destructive-sql" in response.text
    assert "has_flag=destructive_sql" in response.text


@pytest.mark.asyncio
async def test_audit_list_filters_and_validates_trace(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response_valid = await client.get(
            "/ui/audit-events?trace_id=0123456789abcdef0123456789abcdef"
        )
        response_invalid = await client.get("/ui/audit-events?trace_id=not-hex")

    assert response_valid.status_code == 200
    assert "tool_call.completed" in response_valid.text
    assert response_invalid.status_code == 200


@pytest.mark.asyncio
async def test_attack_index_lists_static_scenarios(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response = await client.get("/ui/attacks")

    assert response.status_code == 200
    assert "Destructive SQL" in response.text
    assert "Indirect prompt injection" in response.text


@pytest.mark.asyncio
async def test_missing_session_returns_safe_html_error(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response = await client.get(f"/ui/sessions/{uuid4()}")

    assert response.status_code == 404
    assert "Session not found" in response.text
    assert "Correlation ID" in response.text


@pytest.mark.asyncio
async def test_missing_tool_call_returns_safe_html_error(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        response = await client.get(f"/ui/tool-calls/{uuid4()}")

    assert response.status_code == 404
    assert "Tool call not found" in response.text


@pytest.mark.asyncio
async def test_static_assets_served_locally_with_security_headers(
    app_with_fake_state: tuple[Any, _State],
) -> None:
    application, _state = app_with_fake_state
    async with _client(application) as client:
        css = await client.get("/ui/static/toolwatch.css")
        js = await client.get("/ui/static/htmx.min.js")

    assert css.status_code == 200
    assert "toolwatch" in css.text or "summary-card" in css.text
    assert js.status_code == 200
    assert "htmx-lite" in js.text
    assert css.headers["x-content-type-options"] == "nosniff"
    assert css.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_dashboard_disabled_returns_404_on_ui_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHBOARD_ENABLED", "false")
    get_settings.cache_clear()
    application = create_app()
    async with _client(application) as client:
        response = await client.get("/ui")
        static_response = await client.get("/ui/static/toolwatch.css")

    assert response.status_code == 404
    assert static_response.status_code == 404


@pytest.mark.asyncio
async def test_attack_lab_disabled_hides_attack_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    monkeypatch.setenv("ATTACK_LAB_ENABLED", "false")
    get_settings.cache_clear()
    application = create_app()
    async with _client(application) as client:
        response = await client.get("/ui/attacks")
        home = await client.get("/ui")

    assert response.status_code == 404
    assert home.status_code == 200
    assert "/ui/attacks" not in home.text

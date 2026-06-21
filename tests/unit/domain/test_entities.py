"""Unit tests for registry and session domain invariants."""

from datetime import UTC, datetime

import pytest

from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.common import DomainValidationError
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.sessions.models import InvalidSessionTransition
from toolwatch.domain.tools import RiskLevel, ToolDefinition


def valid_tool(**overrides: object) -> ToolDefinition:
    """Build a valid tool definition with focused overrides."""

    values: dict[str, object] = {
        "name": "github.list_issues",
        "description": "List issues",
        "version": "1.0.0",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": None,
        "base_risk_level": RiskLevel.LOW,
        "adapter_type": "mock",
        "adapter_config": {"fixture": "issues"},
    }
    values.update(overrides)
    return ToolDefinition(**values)  # type: ignore[arg-type]


def test_valid_tool_definition() -> None:
    tool = valid_tool()

    assert tool.name == "github.list_issues"
    assert tool.enabled is True
    assert tool.created_at.tzinfo is UTC


@pytest.mark.parametrize("name", ["GitHub.list", "github list", "github", "github..list", ""])
def test_invalid_tool_name(name: str) -> None:
    with pytest.raises(DomainValidationError):
        valid_tool(name=name)


def test_invalid_risk_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        RiskLevel("extreme")


def test_malformed_schema_is_rejected() -> None:
    with pytest.raises(DomainValidationError):
        valid_tool(input_schema={"type": "object", "properties": []})


def test_secret_material_key_in_adapter_config_is_rejected() -> None:
    with pytest.raises(DomainValidationError):
        valid_tool(adapter_config={"api_key": "not-a-real-secret"})


def test_session_creation_is_active() -> None:
    agent = Agent(identity=AgentIdentity("demo", "local", "model"))
    session = AgentSession(agent_id=agent.id)

    assert session.status is SessionStatus.ACTIVE
    assert session.finished_at is None


def test_valid_terminal_transition_and_idempotence() -> None:
    session = AgentSession(agent_id=Agent(identity=AgentIdentity("demo", "local", "m")).id)
    finished_at = datetime(2026, 6, 22, tzinfo=UTC)

    completed = session.transition_to(SessionStatus.COMPLETED, finished_at=finished_at)

    assert completed.status is SessionStatus.COMPLETED
    assert completed.finished_at == finished_at
    assert completed.transition_to(SessionStatus.COMPLETED) is completed


def test_invalid_terminal_transition_is_rejected() -> None:
    session = AgentSession(agent_id=Agent(identity=AgentIdentity("demo", "local", "m")).id)
    completed = session.transition_to(SessionStatus.COMPLETED)

    with pytest.raises(InvalidSessionTransition):
        completed.transition_to(SessionStatus.FAILED)

    with pytest.raises(InvalidSessionTransition):
        session.transition_to(SessionStatus.ACTIVE)

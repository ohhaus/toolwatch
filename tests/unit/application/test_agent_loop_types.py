"""Pure deterministic tests for provider translation and safe agent-loop values."""

import pytest

from toolwatch.application.agent_runs import (
    SYSTEM_PROMPT,
    build_provider_tools,
    deterministic_agent_idempotency_key,
)
from toolwatch.application.errors import AgentToolSchemaError
from toolwatch.domain.agents import (
    AgentMessage,
    AgentMessageRole,
    AgentProviderOptions,
    AgentProviderResponse,
    RequestedToolCall,
)
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.infrastructure.agents import FakeAgentProvider


def _tool(name: str, version: str = "1") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Public description for {name}.",
        version=version,
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema=None,
        base_risk_level=RiskLevel.LOW,
        adapter_type="secret_adapter_type",
        adapter_config={"fixture": "private"},
    )


def test_tool_translation_is_sorted_public_and_non_mutating() -> None:
    first = _tool("zeta.read")
    second = _tool("alpha.read")
    original = dict(second.input_schema)

    definitions, bindings = build_provider_tools([first, second], max_tools=4)

    assert [item.name for item in definitions] == ["alpha_read", "zeta_read"]
    assert definitions[0].parameters == original
    assert bindings["alpha_read"].tool.name == "alpha.read"
    assert "adapter" not in repr(definitions)
    assert second.input_schema == original


def test_tool_translation_rejects_normalization_collision_and_ambiguous_versions() -> None:
    with pytest.raises(AgentToolSchemaError):
        build_provider_tools([_tool("demo.read"), _tool("demo_read")], max_tools=4)
    with pytest.raises(AgentToolSchemaError):
        build_provider_tools([_tool("demo.read", "1"), _tool("demo.read", "2")], max_tools=4)


def test_idempotency_key_is_stable_and_distinguishes_call_index() -> None:
    from uuid import uuid4

    run_id = uuid4()
    first = deterministic_agent_idempotency_key(
        run_id=run_id,
        turn_number=1,
        call_index=1,
        provider_call_id="provider-1",
        tool_name="demo.read",
        arguments={"value": "x"},
    )
    repeated = deterministic_agent_idempotency_key(
        run_id=run_id,
        turn_number=1,
        call_index=1,
        provider_call_id="provider-1",
        tool_name="demo.read",
        arguments={"value": "x"},
    )
    second = deterministic_agent_idempotency_key(
        run_id=run_id,
        turn_number=1,
        call_index=2,
        provider_call_id="provider-1",
        tool_name="demo.read",
        arguments={"value": "x"},
    )

    assert first == repeated
    assert first != second


@pytest.mark.asyncio
async def test_scripted_fake_provider_is_deterministic_and_records_only_count() -> None:
    scripted = AgentProviderResponse(
        content=None,
        tool_calls=(RequestedToolCall("demo_read", {"value": "safe"}, "call-1"),),
        thinking="UNIQUE_THINKING_SECRET",
    )
    provider = FakeAgentProvider([scripted])

    response = await provider.complete(
        model="fake-v1",
        messages=[
            AgentMessage(AgentMessageRole.SYSTEM, SYSTEM_PROMPT),
            AgentMessage(AgentMessageRole.USER, "safe"),
        ],
        tools=(),
        options=AgentProviderOptions(timeout_seconds=1),
    )

    assert response is scripted
    assert provider.invocation_count == 1
    assert not hasattr(provider, "messages")

"""Deterministic tests for trusted in-process mock adapters."""

from uuid import uuid4

import pytest

from toolwatch.domain.tool_calls import AdapterExecutionError, ToolExecutionContext
from toolwatch.infrastructure.adapters import (
    MockDatabaseAdapter,
    MockEmailAdapter,
    MockGitHubAdapter,
)
from toolwatch.security.payloads import canonicalize_json


def context() -> ToolExecutionContext:
    return ToolExecutionContext(
        call_id=uuid4(),
        session_id=uuid4(),
        tool_name="demo.tool",
        tool_version="1",
        adapter_config={},
    )


@pytest.mark.asyncio
async def test_github_adapter_is_deterministic_and_json_compatible() -> None:
    adapter = MockGitHubAdapter()

    first = await adapter.execute(
        arguments={"repository": "demo/backend", "state": "open"},
        context=context(),
    )
    second = await adapter.execute(
        arguments={"repository": "demo/backend", "state": "open"},
        context=context(),
    )

    assert first == second
    canonicalize_json(first, max_bytes=10000, max_depth=20, max_string_length=1000)


@pytest.mark.asyncio
async def test_email_adapter_returns_deterministic_call_scoped_id() -> None:
    adapter = MockEmailAdapter()
    execution_context = context()

    first = await adapter.execute(arguments={}, context=execution_context)
    second = await adapter.execute(arguments={}, context=execution_context)

    assert first == second


@pytest.mark.asyncio
async def test_database_adapter_only_accepts_exact_allowlist() -> None:
    adapter = MockDatabaseAdapter()

    result = await adapter.execute(
        arguments={"query": "SELECT id, name FROM projects"},
        context=context(),
    )
    assert isinstance(result, dict)

    with pytest.raises(AdapterExecutionError) as error:
        await adapter.execute(arguments={"query": "DROP TABLE projects"}, context=context())
    assert error.value.code == "mock_query_not_supported"

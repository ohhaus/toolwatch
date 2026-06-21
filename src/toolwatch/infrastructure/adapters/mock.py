"""Deterministic mock adapters with no network or external service access."""

import asyncio
import hashlib
from collections.abc import Mapping

from toolwatch.domain.common import JSONValue
from toolwatch.domain.tool_calls import AdapterExecutionError, ToolExecutionContext


class MockGitHubAdapter:
    """Return fixture issues for an already schema-validated request."""

    async def execute(
        self,
        *,
        arguments: Mapping[str, JSONValue],
        context: ToolExecutionContext,
    ) -> JSONValue:
        await _trusted_delay(context)
        state = arguments.get("state")
        if state not in {"open", "closed"}:
            raise AdapterExecutionError
        return {
            "issues": [
                {"number": 1, "title": "Add health endpoint", "state": state},
                {"number": 2, "title": "Improve test coverage", "state": state},
            ]
        }


class MockEmailAdapter:
    """Simulate one accepted email side effect deterministically."""

    async def execute(
        self,
        *,
        arguments: Mapping[str, JSONValue],
        context: ToolExecutionContext,
    ) -> JSONValue:
        del arguments
        await _trusted_delay(context)
        identifier = hashlib.sha256(context.call_id.bytes).hexdigest()[:20]
        return {"message_id": f"msg_{identifier}", "status": "accepted"}


class MockDatabaseAdapter:
    """Return fixture rows for a tiny exact-query allowlist; never execute SQL."""

    _QUERIES: Mapping[str, JSONValue] = {
        "SELECT id, name FROM projects": {
            "rows": [
                {"id": 1, "name": "ToolWatch"},
                {"id": 2, "name": "Demo"},
            ]
        }
    }

    async def execute(
        self,
        *,
        arguments: Mapping[str, JSONValue],
        context: ToolExecutionContext,
    ) -> JSONValue:
        await _trusted_delay(context)
        query = arguments.get("query")
        if not isinstance(query, str) or query not in self._QUERIES:
            raise AdapterExecutionError("mock_query_not_supported")
        return self._QUERIES[query]


async def _trusted_delay(context: ToolExecutionContext) -> None:
    delay = context.adapter_config.get("delay_seconds")
    if isinstance(delay, int | float) and not isinstance(delay, bool) and 0 < delay <= 60:
        await asyncio.sleep(float(delay))

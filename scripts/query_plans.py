"""Capture PostgreSQL plans for lifecycle and recovery indexes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.config import get_settings

QUERIES = {
    "sessions_status_started": (
        "SELECT id FROM agent_sessions WHERE status = 'active' ORDER BY started_at DESC LIMIT 25"
    ),
    "tool_calls_session_sequence": (
        "SELECT id FROM tool_calls WHERE session_id = "
        "(SELECT id FROM agent_sessions LIMIT 1) ORDER BY sequence_number LIMIT 100"
    ),
    "audit_session_created": (
        "SELECT id FROM audit_events WHERE session_id = "
        "(SELECT id FROM agent_sessions LIMIT 1) ORDER BY created_at DESC LIMIT 100"
    ),
    "agent_runs_status_started": (
        "SELECT id FROM agent_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 25"
    ),
    "stale_tool_calls": (
        "SELECT id FROM tool_calls WHERE status = 'executing' "
        "AND updated_at < now() - interval '5 minutes' "
        "ORDER BY updated_at LIMIT 100 FOR UPDATE SKIP LOCKED"
    ),
    "stale_agent_runs": (
        "SELECT id FROM agent_runs WHERE status = 'running' "
        "AND updated_at < now() - interval '5 minutes' "
        "ORDER BY updated_at LIMIT 100 FOR UPDATE SKIP LOCKED"
    ),
    "stale_model_calls": (
        "SELECT id FROM model_calls WHERE status = 'started' "
        "AND started_at < now() - interval '3 minutes' "
        "ORDER BY started_at LIMIT 100 FOR UPDATE SKIP LOCKED"
    ),
}


async def run() -> dict[str, object]:
    engine = create_async_engine(get_settings().database_url)
    result: dict[str, object] = {}
    try:
        async with engine.connect() as connection:
            for name, query in QUERIES.items():
                plan = await connection.scalar(
                    text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}")
                )
                result[name] = plan
    finally:
        await engine.dispose()
    return result


def main() -> int:
    output = Path("artifacts/query-plans.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asyncio.run(run()), indent=2, default=str) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

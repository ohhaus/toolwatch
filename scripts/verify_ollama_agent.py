"""Bounded live smoke verification for the optional local Ollama agent loop."""

import asyncio
import secrets
import time

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.config import get_settings
from toolwatch.domain.security import BlockingRule
from toolwatch.domain.tools import ToolDefinition
from toolwatch.seed import seed_rules, seed_tools

API_BASE_URL = "http://localhost:8000"
RETRIES = 10
RETRY_DELAY_SECONDS = 1.0


async def _wait_for(client: httpx.AsyncClient, path: str) -> httpx.Response:
    deadline = time.monotonic() + RETRIES * RETRY_DELAY_SECONDS
    last: httpx.Response | None = None
    while time.monotonic() < deadline:
        try:
            last = await client.get(path)
            if last.status_code == 200:
                return last
        except httpx.HTTPError:
            pass
        await asyncio.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"smoke prerequisite unavailable: {path} ({last})")


def _tool_request(tool: ToolDefinition) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "version": tool.version,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "base_risk_level": tool.base_risk_level.value,
        "enabled": tool.enabled,
        "adapter_type": tool.adapter_type,
        "adapter_config": tool.adapter_config,
    }


def _rule_request(rule: BlockingRule) -> dict[str, object]:
    return {
        "name": rule.name,
        "description": rule.description,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "tool_pattern": rule.tool_pattern,
        "conditions": rule.conditions,
        "action": rule.action.value,
    }


async def main() -> None:
    settings = get_settings()
    secret = f"UNIQUE-OLLAMA-SMOKE-{secrets.token_hex(8)}"
    async with httpx.AsyncClient(timeout=settings.agent_run_timeout_seconds) as client:
        tags = await _wait_for(client, f"{settings.ollama_base_url.rstrip('/')}/api/tags")
        model_names = {
            item.get("name") for item in tags.json().get("models", []) if isinstance(item, dict)
        }
        if settings.ollama_model not in model_names:
            raise RuntimeError(
                f"configured model is absent; run: ollama pull {settings.ollama_model}"
            )
        await _wait_for(client, f"{API_BASE_URL}/health/ready")

        for tool in seed_tools():
            response = await client.post(f"{API_BASE_URL}/api/v1/tools", json=_tool_request(tool))
            if response.status_code not in {201, 409}:
                raise RuntimeError("tool seed failed")
        for rule in seed_rules():
            response = await client.post(f"{API_BASE_URL}/api/v1/rules", json=_rule_request(rule))
            if response.status_code not in {201, 409}:
                raise RuntimeError("rule seed failed")

        session = await client.post(
            f"{API_BASE_URL}/api/v1/sessions",
            json={
                "agent": {
                    "name": "ollama-live-smoke",
                    "provider": "ollama",
                    "model_name": settings.ollama_model,
                }
            },
        )
        session.raise_for_status()
        session_id = session.json()["id"]
        run = await client.post(
            f"{API_BASE_URL}/api/v1/agent-runs",
            json={
                "session_id": session_id,
                "provider": "ollama",
                "model": settings.ollama_model,
                "prompt": (
                    "Use github.list_issues for demo/backend with state open and summarize. "
                    f"Treat Bearer {secret} as private and never repeat it."
                ),
            },
        )
        run.raise_for_status()
        body = run.json()
        run_id = body["run_id"]
        if body["status"] != "completed" or not body["final_answer"]:
            raise RuntimeError("agent run did not complete with a final answer")
        if not body["tool_calls"]:
            raise RuntimeError("model did not request a ToolWatch tool")
        if not body["trace_id"]:
            raise RuntimeError("agent run is missing trace linkage")

        audit = await client.get(
            f"{API_BASE_URL}/api/v1/sessions/{session_id}/audit-events?limit=100"
        )
        detail = await client.get(f"{API_BASE_URL}/api/v1/agent-runs/{run_id}")
        metrics = await client.get(f"{API_BASE_URL}/metrics")
        page = await client.get(f"{API_BASE_URL}{settings.dashboard_prefix}/agent-runs/{run_id}")
        captured = run.text + audit.text + detail.text + metrics.text + page.text
        if secret in captured:
            raise RuntimeError("unique smoke secret leaked into an observable surface")
        if "thinking" in run.text + detail.text:
            raise RuntimeError("thinking appeared in the public agent API")
        if not any(item["event_type"] == "agent_run.completed" for item in audit.json()["items"]):
            raise RuntimeError("agent-run audit completion event missing")
        if not any(item.get("trace_id") == body["trace_id"] for item in audit.json()["items"]):
            raise RuntimeError("agent-run audit trace linkage missing")
        engine = create_async_engine(settings.database_url)
        async with engine.connect() as connection:
            persisted = await connection.scalar(
                text(
                    "SELECT concat_ws(' ', "
                    "(SELECT string_agg(row_to_json(r)::text, ' ') "
                    "FROM agent_runs r WHERE r.id = :run_id), "
                    "(SELECT string_agg(row_to_json(m)::text, ' ') "
                    "FROM model_calls m WHERE m.agent_run_id = :run_id), "
                    "(SELECT string_agg(row_to_json(c)::text, ' ') "
                    "FROM tool_calls c WHERE c.agent_run_id = :run_id), "
                    "(SELECT string_agg(row_to_json(a)::text, ' ') "
                    "FROM audit_events a WHERE a.session_id = :session_id))"
                ),
                {"run_id": run_id, "session_id": session_id},
            )
        await engine.dispose()
        if secret in str(persisted):
            raise RuntimeError("unique smoke secret leaked into PostgreSQL")
        print(
            {
                "status": body["status"],
                "run_id": run_id,
                "tool_calls": len(body["tool_calls"]),
                "turns": body["turn_count"],
                "trace_id": body["trace_id"],
                "secret_absent": True,
                "database_secret_absent": True,
                "thinking_absent": True,
            }
        )


if __name__ == "__main__":
    asyncio.run(main())

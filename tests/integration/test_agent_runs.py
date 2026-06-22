"""PostgreSQL/API regression tests for Ollama Agent Loop v1."""

from collections.abc import Mapping

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.api.dependencies import get_agent_providers
from toolwatch.config import get_settings
from toolwatch.domain.agents import AgentProvider, AgentProviderResponse, RequestedToolCall
from toolwatch.infrastructure.agents import FakeAgentProvider
from toolwatch.infrastructure.database.engine import get_engine, get_session_factory
from toolwatch.main import create_app
from toolwatch.seed import seed_tools
from toolwatch.telemetry.testing import build_in_memory_runtime

pytestmark = pytest.mark.integration


def _configure(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AGENT_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_AGENT_MODEL", "fake-v1")
    monkeypatch.setenv("FAKE_AGENT_ALLOWED_MODELS", "fake-v1")
    monkeypatch.setenv("REDACTION_FINGERPRINT_KEY", "agent-loop-integration-redaction-key")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _tool_request(index: int) -> dict[str, object]:
    tool = seed_tools()[index]
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


async def _session(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/sessions",
        json={
            "agent": {
                "name": "agent-loop-test",
                "provider": "fake",
                "model_name": "fake-v1",
            }
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.mark.asyncio
async def test_fake_agent_run_persists_only_safe_metadata_and_renders_safely(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure(monkeypatch, clean_database)
    secret = "UNIQUE-AGENT-SECRET-9f21.segmenttwo.segmentthree"
    provider = FakeAgentProvider(
        [
            AgentProviderResponse(
                content=None,
                tool_calls=(
                    RequestedToolCall(
                        "github_list_issues",
                        {"repository": f"{secret}/backend", "state": "open"},
                        "provider-call-1",
                    ),
                ),
                thinking=f"private thought {secret}",
            ),
            AgentProviderResponse(
                content=f"Summary Bearer {secret}",
                thinking=f"another private thought {secret}",
            ),
        ]
    )
    runtime, exporter = build_in_memory_runtime()
    app = create_app(runtime)
    app.dependency_overrides[get_agent_providers] = lambda: {"fake": provider}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/api/v1/tools", json=_tool_request(0))).status_code == 201
        session_id = await _session(client)
        started = await client.post(
            "/api/v1/agent-runs",
            json={
                "session_id": session_id,
                "prompt": f"Check issues with Bearer {secret}",
                "provider": "fake",
                "model": "fake-v1",
            },
        )
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        detail = await client.get(f"/api/v1/agent-runs/{run_id}")
        listed = await client.get("/api/v1/agent-runs?status=completed&limit=1")
        page = await client.get(f"/ui/agent-runs/{run_id}")
        metrics = await client.get("/metrics")

    assert started.json()["status"] == "completed"
    assert started.json()["turn_count"] == 2
    assert started.json()["tool_call_count"] == 1
    assert started.json()["tool_calls"][0]["status"] == "succeeded"
    assert started.json()["final_answer"] == "Summary [REDACTED]"
    assert detail.status_code == 200
    assert len(detail.json()["model_calls"]) == 2
    assert listed.json()["total"] == 1
    assert page.status_code == 200
    assert secret not in started.text + detail.text + listed.text + page.text + metrics.text
    assert secret not in caplog.text
    assert secret not in repr(exporter.get_finished_spans())

    engine = create_async_engine(clean_database)
    async with engine.connect() as connection:
        persisted = await connection.scalar(
            text(
                "SELECT concat_ws(' ', "
                "(SELECT string_agg(row_to_json(r)::text, ' ') FROM agent_runs r), "
                "(SELECT string_agg(row_to_json(m)::text, ' ') FROM model_calls m), "
                "(SELECT string_agg(row_to_json(c)::text, ' ') FROM tool_calls c), "
                "(SELECT string_agg(row_to_json(a)::text, ' ') FROM audit_events a))"
            )
        )
        raw_columns = (
            (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name IN ('agent_runs', 'model_calls')"
                    )
                )
            )
            .scalars()
            .all()
        )
    await engine.dispose()
    assert secret not in str(persisted)
    assert not {"prompt", "thinking", "messages", "raw_response"} & set(raw_columns)
    runtime.shutdown()


@pytest.mark.asyncio
async def test_blocked_model_tool_call_returns_safe_message_and_never_retries(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    _configure(monkeypatch, clean_database)
    provider = FakeAgentProvider(
        [
            AgentProviderResponse(
                content=None,
                tool_calls=(
                    RequestedToolCall(
                        "database_query",
                        {"query": "DROP TABLE projects"},
                        "blocked-1",
                    ),
                ),
            ),
            AgentProviderResponse(content="The action was not completed."),
        ]
    )
    app = create_app()
    providers: Mapping[str, AgentProvider] = {"fake": provider}
    app.dependency_overrides[get_agent_providers] = lambda: providers
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/api/v1/tools", json=_tool_request(2))).status_code == 201
        rule = await client.post(
            "/api/v1/rules",
            json={
                "name": "block-destructive-sql-agent",
                "description": "Block destructive SQL.",
                "enabled": True,
                "priority": 100,
                "tool_pattern": "database.query",
                "conditions": {"has_flag": "destructive_sql"},
                "action": "block",
            },
        )
        assert rule.status_code == 201, rule.text
        session_id = await _session(client)
        response = await client.post(
            "/api/v1/agent-runs",
            json={"session_id": session_id, "prompt": "Delete the projects table."},
        )

    assert response.status_code == 200, response.text
    assert response.json()["tool_calls"][0]["status"] == "blocked"
    assert response.json()["tool_calls"][0]["error_code"] == "tool_call_blocked"
    assert provider.invocation_count == 2


@pytest.mark.asyncio
async def test_multiple_tool_calls_preserve_order_and_disallowed_model_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    _configure(monkeypatch, clean_database)
    provider = FakeAgentProvider(
        [
            AgentProviderResponse(
                content=None,
                tool_calls=(
                    RequestedToolCall(
                        "github_list_issues",
                        {"repository": "demo/backend", "state": "open"},
                        "ordered-1",
                    ),
                    RequestedToolCall(
                        "email_send",
                        {
                            "recipient": "demo@example.com",
                            "subject": "Summary",
                            "body": "Two issues.",
                        },
                        "ordered-2",
                    ),
                ),
            ),
            AgentProviderResponse(content="Done."),
        ]
    )
    app = create_app()
    app.dependency_overrides[get_agent_providers] = lambda: {"fake": provider}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for index in (0, 1):
            created = await client.post("/api/v1/tools", json=_tool_request(index))
            assert created.status_code == 201
        session_id = await _session(client)
        denied = await client.post(
            "/api/v1/agent-runs",
            json={
                "session_id": session_id,
                "prompt": "test",
                "model": "not-allowlisted",
            },
        )
        response = await client.post(
            "/api/v1/agent-runs",
            json={"session_id": session_id, "prompt": "List and email issues."},
        )

    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "agent_model_not_allowed"
    assert response.status_code == 200, response.text
    assert [call["tool"] for call in response.json()["tool_calls"]] == [
        "github.list_issues",
        "email.send",
    ]


@pytest.mark.asyncio
async def test_provider_error_is_sanitized_and_thinking_never_returned(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    _configure(monkeypatch, clean_database)
    secret = "UNIQUE-PROVIDER-ERROR-SECRET-51c2"
    app = create_app()
    app.dependency_overrides[get_agent_providers] = lambda: {"fake": FakeAgentProvider([])}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        session_id = await _session(client)
        response = await client.post(
            "/api/v1/agent-runs",
            json={"session_id": session_id, "prompt": f"Bearer {secret}"},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_provider_error"
    assert secret not in response.text
    assert "thinking" not in response.text

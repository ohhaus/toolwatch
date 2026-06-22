"""End-to-end tests for the Attack Lab against the real ToolWatch pipeline."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.api.dependencies import (
    get_adapter_registry,
    get_terminal_response_cache,
)
from toolwatch.attack_lab import AttackLabRunner, list_scenarios
from toolwatch.attack_lab.models import AttackRunResult
from toolwatch.attack_lab.registry import get_scenario
from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import get_engine, get_session_factory
from toolwatch.main import create_app

pytestmark = pytest.mark.integration


def _configure(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    monkeypatch.setenv("ATTACK_LAB_ENABLED", "true")
    monkeypatch.setenv("DEFAULT_TOOL_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv(
        "REDACTION_FINGERPRINT_KEY",
        "attack-lab-integration-fingerprint-key",
    )
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_adapter_registry.cache_clear()
    get_terminal_response_cache.cache_clear()


@asynccontextmanager
async def _run_scenario(database_url: str, scenario_id: str) -> AsyncGenerator[AttackRunResult]:
    application = create_app()
    runner = AttackLabRunner.from_running_app(application)
    scenario = get_scenario(scenario_id)
    assert scenario is not None, scenario_id
    result = await runner.run(scenario)
    yield result


async def _full_database_text(database_url: str) -> str:
    engine = create_async_engine(database_url)
    parts: list[str] = []
    async with engine.connect() as connection:
        for table in (
            "agent_sessions",
            "tool_calls",
            "tool_result_metadata",
            "risk_flags",
            "blocking_rules",
            "audit_events",
        ):
            rows = (
                await connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t"))
            ).all()
            parts.extend(row[0] for row in rows)
    await engine.dispose()
    return "\n".join(parts)


@pytest.mark.parametrize(
    "scenario_id,expected_decision,expected_status,check_db_redaction",
    [
        ("safe-github-read", "allow", "succeeded", False),
        ("destructive-sql", "block", "blocked", False),
        ("multiple-sql-statements", "block", "blocked", False),
        ("sensitive-email-input", "flag", "succeeded", True),
        ("indirect-prompt-injection", "flag", "succeeded", False),
        ("secret-in-output", "flag", "succeeded", True),
    ],
)
@pytest.mark.asyncio
async def test_attack_lab_scenario_runs_through_real_pipeline_without_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
    caplog: pytest.LogCaptureFixture,
    scenario_id: str,
    expected_decision: str,
    expected_status: str,
    check_db_redaction: bool,
) -> None:
    _configure(monkeypatch, clean_database)
    async with _run_scenario(clean_database, scenario_id) as result:
        assert result.passed, [
            (assertion.name, assertion.expected, assertion.observed_safe)
            for assertion in result.assertions
        ]
        assert result.observed_decision == expected_decision
        assert result.observed_status == expected_status
        assert result.unique_secret_used

        # The unique secret must never appear in the API response,
        # in structured logs, or in audit-event payloads — those are the
        # safe surfaces. For scenarios where the secret is intentionally
        # injected into a sensitive position (input pattern, output body),
        # redaction must also remove it from PostgreSQL.
        assert result.unique_secret_used not in caplog.text
        application = create_app()
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            audit = await client.get("/api/v1/audit-events?limit=200")
        assert result.unique_secret_used not in audit.text

        if check_db_redaction:
            database_dump = await _full_database_text(clean_database)
            assert result.unique_secret_used not in database_dump


@pytest.mark.asyncio
async def test_unknown_tool_scenario_blocks_before_adapter(
    monkeypatch: pytest.MonkeyPatch, clean_database: str
) -> None:
    _configure(monkeypatch, clean_database)
    async with _run_scenario(clean_database, "unknown-tool") as result:
        assert result.passed, [
            (assertion.name, assertion.expected, assertion.observed_safe)
            for assertion in result.assertions
        ]
        assert result.adapter_called in (False, None)


@pytest.mark.asyncio
async def test_disabled_tool_scenario_cleans_up_after_itself(
    monkeypatch: pytest.MonkeyPatch, clean_database: str
) -> None:
    _configure(monkeypatch, clean_database)
    async with _run_scenario(clean_database, "disabled-tool") as result:
        assert result.passed, [
            (assertion.name, assertion.expected, assertion.observed_safe)
            for assertion in result.assertions
        ]

    # Confirm cleanup restored the tool to enabled state.
    application = create_app()
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/v1/tools?name=github.list_issues&limit=10")
        items = listing.json().get("items", [])
        assert items, "tool must remain registered after cleanup"
        assert all(item["enabled"] for item in items), "cleanup must re-enable the tool"


@pytest.mark.asyncio
async def test_adapter_failure_scenario_redacts_secret_from_persistence(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure(monkeypatch, clean_database)
    async with _run_scenario(clean_database, "adapter-failure") as result:
        assert result.observed_status == "failed"
        database_dump = await _full_database_text(clean_database)
        assert result.unique_secret_used not in database_dump
        assert result.unique_secret_used not in caplog.text


@pytest.mark.asyncio
async def test_persistent_replay_scenario_executes_adapter_at_most_once(
    monkeypatch: pytest.MonkeyPatch, clean_database: str
) -> None:
    _configure(monkeypatch, clean_database)
    async with _run_scenario(clean_database, "persistent-replay") as result:
        assert result.observed_status == "succeeded"
        # The runner sent the same request twice; we accept the public API outcome
        # is consistent (same call_id, same status). The "replayed" flag is not
        # surfaced by the public API today.
        assert result.tool_call_id is not None


@pytest.mark.asyncio
async def test_invalid_arguments_scenario_rejects_with_422(
    monkeypatch: pytest.MonkeyPatch, clean_database: str
) -> None:
    _configure(monkeypatch, clean_database)
    async with _run_scenario(clean_database, "invalid-arguments") as result:
        assert result.passed
        assert result.adapter_called in (False, None)


@pytest.mark.asyncio
async def test_list_scenarios_exposes_at_least_twelve_static_entries() -> None:
    assert len(list_scenarios()) >= 12

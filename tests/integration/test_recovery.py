"""PostgreSQL recovery regressions for interrupted execution state."""

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.application.recovery import RecoveryService
from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import get_engine, get_session_factory
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork
from toolwatch.main import create_app
from toolwatch.seed import seed_tools
from toolwatch.telemetry.testing import build_in_memory_runtime

pytestmark = pytest.mark.integration


def _configure(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AGENT_PROVIDER", "fake")
    monkeypatch.setenv("TOOL_CALL_STALE_AFTER_SECONDS", "60")
    monkeypatch.setenv("AGENT_RUN_STALE_AFTER_SECONDS", "60")
    monkeypatch.setenv("MODEL_CALL_STALE_AFTER_SECONDS", "60")
    monkeypatch.setenv("RECOVERY_BATCH_SIZE", "2")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _tool_request() -> dict[str, object]:
    tool = seed_tools()[0]
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


@pytest.mark.asyncio
async def test_recovery_is_conservative_idempotent_and_concurrency_safe(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    _configure(monkeypatch, clean_database)
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/api/v1/tools", json=_tool_request())).status_code == 201
        session = await client.post(
            "/api/v1/sessions",
            json={
                "agent": {
                    "name": "recovery-agent",
                    "provider": "fake",
                    "model_name": "fake-v1",
                }
            },
        )
        session_id = session.json()["id"]
        run = await client.post(
            "/api/v1/agent-runs",
            json={"session_id": session_id, "prompt": "List issues."},
        )
        assert run.status_code == 200, run.text
        run_id = run.json()["run_id"]
        call_id = run.json()["tool_calls"][0]["call_id"]
        model_call_id = run.json()["model_calls"][0]["id"]
        fresh = await client.post(
            "/api/v1/tool-calls",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "session_id": session_id,
                "tool": "github.list_issues",
                "tool_version": "1.0.0",
                "arguments": {"repository": "demo/backend", "state": "closed"},
            },
        )
        assert fresh.status_code == 200, fresh.text
        fresh_call_id = fresh.json()["call_id"]

    stale_at = datetime.now(UTC) - timedelta(minutes=10)
    created_at = stale_at - timedelta(minutes=1)
    engine = create_async_engine(clean_database)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE tool_calls SET status = 'executing', finished_at = NULL, "
                "duration_ms = NULL, error_code = NULL, error_message_safe = NULL, "
                "created_at = :created, started_at = :stale, updated_at = :stale "
                "WHERE id = :id"
            ),
            {"id": call_id, "created": created_at, "stale": stale_at},
        )
        await connection.execute(
            text(
                "UPDATE model_calls SET status = 'started', finished_at = NULL, "
                "error_code = NULL, started_at = :stale WHERE id = :id"
            ),
            {"id": model_call_id, "stale": stale_at},
        )
        await connection.execute(
            text(
                "UPDATE agent_runs SET status = 'running', finished_at = NULL, "
                "error_code = NULL, created_at = :created, started_at = :created, "
                "updated_at = :stale WHERE id = :id"
            ),
            {"id": run_id, "created": created_at, "stale": stale_at},
        )
        await connection.execute(
            text(
                "UPDATE tool_calls SET status = 'executing', finished_at = NULL, "
                "duration_ms = NULL, error_code = NULL, error_message_safe = NULL, "
                "started_at = now(), updated_at = now() WHERE id = :id"
            ),
            {"id": fresh_call_id},
        )

    runtime, _exporter = build_in_memory_runtime()
    settings = get_settings()
    uow_factory = partial(SqlAlchemyUnitOfWork, get_session_factory())
    first = RecoveryService(
        uow_factory=uow_factory,
        settings=settings,
        telemetry=runtime,
    )
    second = RecoveryService(
        uow_factory=uow_factory,
        settings=settings,
        telemetry=runtime,
    )
    results = await asyncio.gather(first.run(), second.run())
    assert sum(result.total for result in results) == 3
    assert (await first.run()).total == 0

    async with engine.connect() as connection:
        tool_row = (
            await connection.execute(
                text("SELECT status, error_code, started_at FROM tool_calls WHERE id = :id"),
                {"id": call_id},
            )
        ).one()
        run_row = (
            await connection.execute(
                text("SELECT status, error_code FROM agent_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).one()
        model_row = (
            await connection.execute(
                text("SELECT status, error_code FROM model_calls WHERE id = :id"),
                {"id": model_call_id},
            )
        ).one()
        audit_types = set(
            (
                await connection.execute(
                    text("SELECT event_type FROM audit_events WHERE event_type LIKE '%.recovered'")
                )
            )
            .scalars()
            .all()
        )
        fresh_status = await connection.scalar(
            text("SELECT status FROM tool_calls WHERE id = :id"),
            {"id": fresh_call_id},
        )
    await engine.dispose()
    runtime.shutdown()

    assert tool_row == ("failed", "execution_state_unknown", stale_at)
    assert run_row == ("failed", "agent_run_interrupted")
    assert model_row == ("failed", "model_call_interrupted")
    assert fresh_status == "executing"
    assert audit_types == {
        "tool_call.recovered",
        "agent_run.recovered",
        "model_call.recovered",
    }
    metrics = runtime.metrics.render().decode()
    assert 'operation="tool_call"' in metrics
    assert 'operation="agent_run"' in metrics
    assert 'operation="model_call"' in metrics

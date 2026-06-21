"""End-to-end API and PostgreSQL tests for milestone 2."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import get_engine, get_session_factory
from toolwatch.main import create_app

pytestmark = pytest.mark.integration

TOOL_REQUEST = {
    "name": "github.list_issues",
    "description": "List issues",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {"repository": {"type": "string"}},
        "required": ["repository"],
        "additionalProperties": False,
    },
    "output_schema": {"type": "array", "items": {"type": "object"}},
    "base_risk_level": "low",
    "enabled": True,
    "adapter_type": "mock",
    "adapter_config": {"fixture": "issues"},
}


def configure_database(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    """Point all controlled database dependencies at the disposable PostgreSQL."""

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORE_PROMPTS", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def client_for_app() -> httpx.AsyncClient:
    """Create an in-process client that exercises sanitized exception handlers."""

    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_tool_registry_crud_filters_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    configure_database(monkeypatch, clean_database)

    async with client_for_app() as client:
        created = await client.post("/api/v1/tools", json=TOOL_REQUEST)
        duplicate = await client.post("/api/v1/tools", json=TOOL_REQUEST)
        tool_id = created.json()["id"]
        detail = await client.get(f"/api/v1/tools/{tool_id}")
        disabled = await client.patch(f"/api/v1/tools/{tool_id}", json={"enabled": False})
        filtered = await client.get("/api/v1/tools?enabled=false&risk_level=low&limit=1")
        missing = await client.get(f"/api/v1/tools/{uuid4()}")

    assert created.status_code == 201
    assert "adapter_config" not in created.json()
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "tool_version_already_exists"
    assert detail.status_code == 200
    assert disabled.json()["enabled"] is False
    assert filtered.json()["total"] == 1
    assert filtered.json()["limit"] == 1
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "tool_not_found"


@pytest.mark.asyncio
async def test_malformed_schema_and_secret_config_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    configure_database(monkeypatch, clean_database)
    malformed: dict[str, object] = {
        **TOOL_REQUEST,
        "input_schema": {"type": "object", "properties": list[object]()},
    }
    secret_config = {**TOOL_REQUEST, "adapter_config": {"token": "raw-test-secret"}}

    async with client_for_app() as client:
        malformed_response = await client.post("/api/v1/tools", json=malformed)
        secret_response = await client.post("/api/v1/tools", json=secret_config)

    assert malformed_response.status_code == 422
    assert malformed_response.json()["error"]["code"] == "invalid_request"
    assert "raw-test-secret" not in secret_response.text


@pytest.mark.asyncio
async def test_session_creation_reuses_agent_omits_prompt_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_database(monkeypatch, clean_database)
    raw_prompt = "Bearer raw-prompt-test-secret"
    request = {
        "agent": {
            "name": "demo",
            "provider": "local",
            "model_name": "model",
            "version": "1",
        },
        "external_session_id": "client-1",
        "user_prompt": raw_prompt,
        "metadata": {"source": "test"},
    }

    async with client_for_app() as client:
        first = await client.post("/api/v1/sessions", json=request)
        second = await client.post("/api/v1/sessions", json={**request, "external_session_id": "2"})
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        session_id = first.json()["id"]
        listed = await client.get("/api/v1/sessions?status=active&limit=1&offset=0")
        detail = await client.get(f"/api/v1/sessions/{session_id}")
        completed = await client.post(
            f"/api/v1/sessions/{session_id}/complete",
            json={"status": "completed"},
        )
        repeated = await client.post(
            f"/api/v1/sessions/{session_id}/complete",
            json={"status": "completed"},
        )
        invalid = await client.post(
            f"/api/v1/sessions/{session_id}/complete",
            json={"status": "failed"},
        )

    assert first.json()["agent"]["id"] == second.json()["agent"]["id"]
    assert listed.json()["total"] == 2
    assert detail.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["finished_at"] is not None
    assert repeated.status_code == 200
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "invalid_session_transition"
    assert raw_prompt not in caplog.text

    engine = create_async_engine(clean_database)
    async with engine.connect() as connection:
        prompts = (
            (await connection.execute(text("SELECT user_prompt_redacted FROM agent_sessions")))
            .scalars()
            .all()
        )
        agent_count = await connection.scalar(text("SELECT count(*) FROM agents"))
    await engine.dispose()
    assert prompts == [None, None]
    assert agent_count == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_tool_registration_has_one_winner(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    configure_database(monkeypatch, clean_database)

    async def register() -> httpx.Response:
        async with client_for_app() as client:
            return await client.post("/api/v1/tools", json=TOOL_REQUEST)

    first, second = await asyncio.gather(register(), register())

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["error"]["code"] == "tool_version_already_exists"


@pytest.mark.asyncio
async def test_concurrent_sessions_reuse_one_logical_agent(
    monkeypatch: pytest.MonkeyPatch,
    clean_database: str,
) -> None:
    configure_database(monkeypatch, clean_database)
    request = {
        "agent": {
            "name": "concurrent-agent",
            "provider": "local",
            "model_name": "model",
            "version": None,
        }
    }

    async def create_session() -> httpx.Response:
        async with client_for_app() as client:
            return await client.post("/api/v1/sessions", json=request)

    first, second = await asyncio.gather(create_session(), create_session())

    assert first.status_code == second.status_code == 201
    assert first.json()["agent"]["id"] == second.json()["agent"]["id"]

    engine = create_async_engine(clean_database)
    async with engine.connect() as connection:
        agent_count = await connection.scalar(text("SELECT count(*) FROM agents"))
        session_count = await connection.scalar(text("SELECT count(*) FROM agent_sessions"))
    await engine.dispose()
    assert agent_count == 1
    assert session_count == 2


@pytest.mark.asyncio
async def test_foreign_key_and_jsonb_are_enforced(
    clean_database: str,
) -> None:
    engine = create_async_engine(clean_database)
    async with engine.connect() as connection:
        jsonb_type = await connection.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'tool_definitions' AND column_name = 'input_schema'"
            )
        )
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO agent_sessions "
                    "(id, agent_id, status, started_at, metadata) "
                    "VALUES (:id, :agent_id, 'active', now(), '{}'::jsonb)"
                ),
                {"id": uuid4(), "agent_id": uuid4()},
            )
        await connection.rollback()
    await engine.dispose()
    assert jsonb_type == "jsonb"


@pytest.mark.asyncio
async def test_unexpected_database_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = "postgresql+asyncpg://private_user:private_password@127.0.0.1:1/private_db"
    configure_database(monkeypatch, unavailable)

    async with client_for_app() as client:
        response = await client.get("/api/v1/tools")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private_password" not in response.text
    assert unavailable not in response.text

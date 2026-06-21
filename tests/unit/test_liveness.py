"""Unit tests for process liveness."""

import httpx
import pytest

from toolwatch.main import create_app


@pytest.mark.asyncio
async def test_liveness_does_not_require_database() -> None:
    """The live probe succeeds without opening a PostgreSQL connection."""

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "toolwatch"}

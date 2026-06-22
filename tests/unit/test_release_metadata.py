"""Release-version and HTTP hardening regressions."""

from pathlib import Path

import httpx
import pytest

from toolwatch import __version__
from toolwatch.config import get_settings
from toolwatch.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_release_version_has_one_authoritative_python_source() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert __version__ == "0.1.0"
    assert 'dynamic = ["version"]' in pyproject
    assert 'path = "src/toolwatch/__init__.py"' in pyproject
    assert "ARG VERSION=0.1.0" in dockerfile
    assert get_settings().app_version == __version__


@pytest.mark.asyncio
async def test_docs_switch_request_limit_and_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCS_ENABLED", "false")
    monkeypatch.setenv("MAX_HTTP_REQUEST_BYTES", "16")
    get_settings.cache_clear()
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/health/live")
        docs = await client.get("/docs")
        oversized = await client.post(
            "/api/v1/sessions",
            content=b"x" * 17,
            headers={"content-type": "application/json"},
        )
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["referrer-policy"] == "no-referrer"
    assert docs.status_code == 404
    assert oversized.status_code == 413

"""Bounded graceful-shutdown coordination tests."""

import asyncio

import pytest

from toolwatch.infrastructure.agents import OllamaAgentProvider
from toolwatch.shutdown import ShutdownManager


@pytest.mark.asyncio
async def test_shutdown_waits_for_cooperative_in_flight_work() -> None:
    manager = ShutdownManager(grace_period_seconds=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def request() -> None:
        async with manager.track() as accepted:
            assert accepted
            started.set()
            await release.wait()

    task = asyncio.create_task(request())
    await started.wait()
    draining = asyncio.create_task(manager.drain())
    await asyncio.sleep(0)
    assert not manager.accepting
    release.set()
    await draining
    await task


@pytest.mark.asyncio
async def test_shutdown_cancels_work_after_bounded_timeout() -> None:
    manager = ShutdownManager(grace_period_seconds=0.01)
    started = asyncio.Event()

    async def request() -> None:
        async with manager.track() as accepted:
            assert accepted
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(request())
    await started.wait()
    await manager.drain()
    assert task.cancelled()
    async with manager.track() as accepted:
        assert not accepted


@pytest.mark.asyncio
async def test_ollama_provider_closes_owned_http_client() -> None:
    provider = OllamaAgentProvider("http://localhost:11434")
    assert not provider.is_closed
    await provider.aclose()
    assert provider.is_closed

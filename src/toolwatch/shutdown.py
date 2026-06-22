"""Bounded graceful-shutdown coordination for application-owned work."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Receive, Scope, Send


def _task_set() -> set[asyncio.Task[object]]:
    return set()


@dataclass(slots=True)
class ShutdownManager:
    """Stop new work, then wait briefly before cancelling remaining request tasks."""

    grace_period_seconds: float
    _accepting: bool = True
    _tasks: set[asyncio.Task[object]] = field(default_factory=_task_set)
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    @property
    def accepting(self) -> bool:
        return self._accepting

    @asynccontextmanager
    async def track(self) -> AsyncGenerator[bool]:
        task = asyncio.current_task()
        if not self._accepting or task is None:
            yield False
            return
        async with self._condition:
            if not self._accepting:
                yield False
                return
            self._tasks.add(task)
        try:
            yield True
        finally:
            async with self._condition:
                self._tasks.discard(task)
                self._condition.notify_all()

    async def drain(self) -> None:
        """Reject new requests and bound the wait for existing application work."""

        async with self._condition:
            self._accepting = False
            try:
                async with asyncio.timeout(self.grace_period_seconds):
                    await self._condition.wait_for(lambda: not self._tasks)
                    return
            except TimeoutError:
                tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class ShutdownMiddleware:
    """Return a fixed 503 after shutdown draining begins."""

    def __init__(self, app: ASGIApp, manager: ShutdownManager) -> None:
        self._app = app
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        async with self._manager.track() as accepted:
            if not accepted:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"error":{"code":"application_shutting_down"}}',
                    }
                )
                return
            await self._app(scope, receive, send)

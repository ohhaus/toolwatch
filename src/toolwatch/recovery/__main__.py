"""CLI for conservative recovery of interrupted execution state."""

from __future__ import annotations

import argparse
import asyncio

from toolwatch.application.recovery import RecoveryService
from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import dispose_engine, get_session_factory
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork
from toolwatch.telemetry import build_telemetry_runtime


async def _run() -> int:
    settings = get_settings()
    telemetry = build_telemetry_runtime(settings)
    try:
        result = await RecoveryService(
            uow_factory=lambda: SqlAlchemyUnitOfWork(get_session_factory()),
            settings=settings,
            telemetry=telemetry,
        ).run()
        print(
            f"recovered tool_calls={result.tool_calls} agent_runs={result.agent_runs} "
            f"model_calls={result.model_calls} total={result.total}"
        )
        return 0
    finally:
        telemetry.shutdown()
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run",))
    parser.parse_args()
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

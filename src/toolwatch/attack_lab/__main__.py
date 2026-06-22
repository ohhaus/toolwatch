"""Command-line entry point for the Attack Lab."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime

from toolwatch.attack_lab.models import AttackRunResult
from toolwatch.attack_lab.registry import get_scenario, list_scenarios
from toolwatch.attack_lab.runner import AttackLabRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolwatch.attack_lab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List static Attack Lab scenarios.")

    run = subparsers.add_parser("run", help="Run one Attack Lab scenario.")
    run.add_argument("scenario_id", help="Identifier of a registered scenario.")

    subparsers.add_parser("run-all", help="Run every registered scenario in order.")

    return parser


def _print_scenarios() -> int:
    for scenario in list_scenarios():
        print(
            f"{scenario.id:<28}  [{scenario.severity:<8}] {scenario.tool_name}@"
            f"{scenario.tool_version}  — {scenario.name}"
        )
    return 0


def _serialize(result: AttackRunResult) -> str:
    payload = asdict(result)

    def default(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    return json.dumps(payload, indent=2, ensure_ascii=False, default=default)


async def _run_one(scenario_id: str) -> int:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        print(f"unknown scenario: {scenario_id}", file=sys.stderr)
        return 2
    from toolwatch.main import create_app

    app = create_app()
    runner = AttackLabRunner.from_running_app(app)
    result = await runner.run(scenario)
    print(_serialize(result))
    return 0 if result.passed else 1


async def _run_all() -> int:
    from toolwatch.main import create_app

    app = create_app()
    runner = AttackLabRunner.from_running_app(app)
    exit_code = 0
    for scenario in list_scenarios():
        result = await runner.run(scenario)
        summary = "PASS" if result.passed else "FAIL"
        print(
            f"{summary}  {scenario.id:<28}  duration={result.duration_ms}ms  "
            f"observed_status={result.observed_status or '—'}  "
            f"observed_decision={result.observed_decision or '—'}"
        )
        if not result.passed:
            exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        return _print_scenarios()
    if args.command == "run":
        return asyncio.run(_run_one(args.scenario_id))
    if args.command == "run-all":
        return asyncio.run(_run_all())
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

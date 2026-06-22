"""Reproducible HTTPX load scenarios for a running local ToolWatch stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import uuid4

import httpx


@dataclass(slots=True)
class Samples:
    durations: list[float] = field(default_factory=list)
    errors: int = 0


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index] * 1000


async def _request(
    client: httpx.AsyncClient,
    samples: dict[str, Samples],
    name: str,
    method: str,
    path: str,
    **kwargs: object,
) -> httpx.Response:
    started = time.perf_counter()
    response = await client.request(method, path, **kwargs)
    sample = samples[name]
    sample.durations.append(time.perf_counter() - started)
    if response.status_code >= 500:
        sample.errors += 1
    return response


async def _create_session(client: httpx.AsyncClient, index: int) -> str:
    response = await client.post(
        "/api/v1/sessions",
        json={
            "agent": {
                "name": f"load-agent-{index % 100}",
                "provider": "fake",
                "model_name": "fake-v1",
            }
        },
    )
    response.raise_for_status()
    return str(response.json()["id"])


async def run(base_url: str, requests: int, concurrency: int) -> dict[str, object]:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    samples: dict[str, Samples] = defaultdict(Samples)
    async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits) as client:
        session_id = await _create_session(client, 0)
        duplicate_key = str(uuid4())
        scenarios = (
            ("health", "GET", "/health/live", {}),
            ("sessions", "GET", "/api/v1/sessions?limit=25", {}),
            ("tool_calls", "GET", f"/api/v1/sessions/{session_id}/tool-calls", {}),
            ("audit", "GET", "/api/v1/audit-events?limit=25", {}),
            ("dashboard", "GET", "/ui", {}),
            (
                "safe_tool",
                "POST",
                "/api/v1/tool-calls",
                {
                    "headers": {"Idempotency-Key": str(uuid4())},
                    "json": {
                        "session_id": session_id,
                        "tool": "github.list_issues",
                        "tool_version": "1.0.0",
                        "arguments": {"repository": "demo/backend", "state": "open"},
                    },
                },
            ),
            (
                "idempotent_duplicate",
                "POST",
                "/api/v1/tool-calls",
                {
                    "headers": {"Idempotency-Key": duplicate_key},
                    "json": {
                        "session_id": session_id,
                        "tool": "github.list_issues",
                        "tool_version": "1.0.0",
                        "arguments": {"repository": "demo/backend", "state": "open"},
                    },
                },
            ),
            (
                "flagged_tool",
                "POST",
                "/api/v1/tool-calls",
                {
                    "headers": {"Idempotency-Key": str(uuid4())},
                    "json": {
                        "session_id": session_id,
                        "tool": "email.send",
                        "tool_version": "1.0.0",
                        "arguments": {
                            "recipient": "load@example.com",
                            "subject": "Load",
                            "body": "Safe fixture",
                        },
                    },
                },
            ),
            (
                "blocked_tool",
                "POST",
                "/api/v1/tool-calls",
                {
                    "headers": {"Idempotency-Key": str(uuid4())},
                    "json": {
                        "session_id": session_id,
                        "tool": "database.query",
                        "tool_version": "1.0.0",
                        "arguments": {"query": "DROP TABLE projects"},
                    },
                },
            ),
            (
                "fake_agent",
                "POST",
                "/api/v1/agent-runs",
                {
                    "json": {
                        "session_id": session_id,
                        "provider": "fake",
                        "model": "fake-v1",
                        "prompt": "No tool is needed; answer briefly.",
                    }
                },
            ),
        )
        semaphore = asyncio.Semaphore(concurrency)

        async def one(index: int) -> None:
            name, method, path, kwargs = scenarios[index % len(scenarios)]
            async with semaphore:
                await _request(client, samples, name, method, path, **kwargs)

        started = time.perf_counter()
        await asyncio.gather(*(one(index) for index in range(requests)))
        elapsed = time.perf_counter() - started

    report: dict[str, object] = {
        "requests": requests,
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(requests / elapsed, 2),
        "client_connection_limit": concurrency,
        "scenarios": {},
    }
    for name, sample in sorted(samples.items()):
        report["scenarios"][name] = {
            "count": len(sample.durations),
            "p50_ms": round(_percentile(sample.durations, 0.50), 2),
            "p95_ms": round(_percentile(sample.durations, 0.95), 2),
            "p99_ms": round(_percentile(sample.durations, 0.99), 2),
            "error_rate": round(sample.errors / max(1, len(sample.durations)), 4),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.base_url, args.requests, args.concurrency)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

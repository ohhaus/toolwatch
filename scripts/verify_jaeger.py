#!/usr/bin/env python3
"""Bounded Jaeger smoke verification used by ToolWatch demos and CI smoke runs.

The script issues a small, deterministic mix of allowed and blocked tool calls
against a running ToolWatch API, polls the Jaeger query API with bounded retries
and a hard timeout, then prints a structured pass/fail report.

It must not run in default CI; it requires a developer-started Compose
``observability`` profile.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from uuid import uuid4

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_JAEGER_URL = "http://localhost:16686"
SERVICE = "toolwatch"


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _http_request(
    method: str,
    url: str,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, object]]:
    data = None
    request_headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as http_error:
        raw = http_error.read() or b""
        status_code = http_error.code
    else:
        with response:
            raw = response.read()
            status_code = response.status
    if not raw:
        return status_code, {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}
    return status_code, payload if isinstance(payload, dict) else {}


def _create_session(api_url: str) -> str:
    status_code, body = _http_request(
        "POST",
        f"{api_url}/api/v1/sessions",
        body={
            "agent": {
                "name": "verify-jaeger-agent",
                "provider": "smoke",
                "model_name": "deterministic",
            }
        },
    )
    if status_code != 201 or "id" not in body:
        raise RuntimeError(f"unable to create session (status={status_code})")
    return str(body["id"])


def _execute_call(
    api_url: str,
    *,
    session_id: str,
    tool: str,
    arguments: dict[str, object],
) -> tuple[int, dict[str, object]]:
    return _http_request(
        "POST",
        f"{api_url}/api/v1/tool-calls",
        body={
            "session_id": session_id,
            "tool": tool,
            "tool_version": "1.0.0",
            "arguments": arguments,
        },
        headers={"Idempotency-Key": str(uuid4())},
    )


def _jaeger_operations(jaeger_url: str) -> set[str]:
    encoded_service = urllib.parse.quote(SERVICE)
    status_code, body = _http_request(
        "GET",
        f"{jaeger_url}/api/operations?service={encoded_service}",
    )
    if status_code != 200:
        return set()
    operations = {
        str(item["name"])
        for item in body.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    return operations


def _wait_for_operations(jaeger_url: str, expected: set[str], *, timeout: float) -> set[str]:
    deadline = time.monotonic() + timeout
    last: set[str] = set()
    while time.monotonic() < deadline:
        last = _jaeger_operations(jaeger_url)
        if expected.issubset(last):
            return last
        time.sleep(2.0)
    return last


def _search_trace_for_secret(jaeger_url: str, secret: str) -> bool:
    encoded_service = urllib.parse.quote(SERVICE)
    status_code, body = _http_request(
        "GET",
        f"{jaeger_url}/api/traces?service={encoded_service}&limit=50&lookback=15m",
    )
    if status_code != 200:
        return False
    return secret in json.dumps(body, ensure_ascii=False)


def _ensure_seeded(api_url: str) -> None:
    status_code, body = _http_request("GET", f"{api_url}/api/v1/tools?limit=10")
    if status_code == 200 and body.get("total", 0) >= 3:
        return
    print("Tools are not seeded; refusing to run smoke check.", file=sys.stderr)
    sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ToolWatch Jaeger smoke verification.")
    parser.add_argument("--api-url", default=os.environ.get("VERIFY_API_URL", DEFAULT_API_URL))
    parser.add_argument(
        "--jaeger-url", default=os.environ.get("VERIFY_JAEGER_URL", DEFAULT_JAEGER_URL)
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    results: list[CheckResult] = []
    try:
        _ensure_seeded(args.api_url)
        session_id = _create_session(args.api_url)
        unique_secret = f"VERIFY-JAEGER-{secrets.token_hex(6)}"
        allowed_status, allowed_body = _execute_call(
            args.api_url,
            session_id=session_id,
            tool="github.list_issues",
            arguments={"repository": "demo/backend", "state": "open"},
        )
        blocked_status, _blocked_body = _execute_call(
            args.api_url,
            session_id=session_id,
            tool="database.query",
            arguments={"query": f"DROP TABLE smoke_{unique_secret}"},
        )
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"smoke setup failed: {exc}", file=sys.stderr)
        return 2

    results.append(
        CheckResult(
            "allowed_call_succeeded",
            allowed_status == 200 and allowed_body.get("status") == "succeeded",
            f"http={allowed_status} status={allowed_body.get('status')}",
        )
    )
    results.append(
        CheckResult(
            "blocked_call_blocked",
            blocked_status == 403,
            f"http={blocked_status}",
        )
    )

    operations = _wait_for_operations(
        args.jaeger_url,
        {"execute_tool github.list_issues", "toolwatch.execute_tool_call"},
        timeout=args.timeout,
    )
    results.append(
        CheckResult(
            "jaeger_allowed_adapter_span",
            "execute_tool github.list_issues" in operations,
            f"operations={sorted(operations)[:6]}…",
        )
    )
    results.append(
        CheckResult(
            "jaeger_no_blocked_adapter_span",
            "execute_tool database.query" not in operations,
            "execute_tool database.query absent"
            if "execute_tool database.query" not in operations
            else "execute_tool database.query PRESENT",
        )
    )
    secret_leaked = _search_trace_for_secret(args.jaeger_url, unique_secret)
    results.append(
        CheckResult(
            "no_secret_in_jaeger",
            not secret_leaked,
            "absent" if not secret_leaked else "PRESENT",
        )
    )

    exit_code = 0
    for check in results:
        marker = "PASS" if check.passed else "FAIL"
        print(f"{marker}  {check.name:<32}  {check.detail}")
        if not check.passed:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

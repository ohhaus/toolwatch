"""Smoke-test the tagged release image against disposable PostgreSQL."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4

IMAGE = "toolwatch:0.1.0"
PORT = 18080


def _run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(command, check=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
    with response:
        return response.status, response.read().decode()


def main() -> int:
    suffix = uuid4().hex[:8]
    network = f"toolwatch-smoke-{suffix}"
    postgres = f"toolwatch-postgres-{suffix}"
    api = f"toolwatch-api-{suffix}"
    database_url = "postgresql+asyncpg://toolwatch:toolwatch@postgres:5432/toolwatch"
    try:
        _run(["docker", "network", "create", network])
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                postgres,
                "--network",
                network,
                "--network-alias",
                "postgres",
                "-e",
                "POSTGRES_DB=toolwatch",
                "-e",
                "POSTGRES_USER=toolwatch",
                "-e",
                "POSTGRES_PASSWORD=toolwatch",
                "postgres:17-alpine",
            ]
        )
        for _ in range(30):
            ready = subprocess.run(
                ["docker", "exec", postgres, "pg_isready", "-U", "toolwatch", "-d", "toolwatch"],
                check=False,
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("PostgreSQL did not become ready")

        common = ["--network", network, "-e", f"DATABASE_URL={database_url}"]
        _run(["docker", "run", "--rm", *common, IMAGE, "alembic", "upgrade", "head"])
        _run(["docker", "run", "--rm", *common, IMAGE, "python", "-m", "toolwatch.seed"])
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                api,
                *common,
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--security-opt",
                "no-new-privileges",
                "-p",
                f"{PORT}:8000",
                IMAGE,
            ]
        )
        for _ in range(30):
            try:
                status, _ = _request("GET", "/health/live")
            except (OSError, urllib.error.URLError):
                status = 0
            if status == 200:
                break
            time.sleep(1)
        else:
            logs = _run(["docker", "logs", api], capture=True)
            raise RuntimeError(f"release API did not become healthy: {logs[-2000:]}")

        user = _run(["docker", "inspect", "-f", "{{.Config.User}}", api], capture=True)
        if user in {"", "0", "root"}:
            raise RuntimeError("release image is not configured as non-root")
        session_status, session_body = _request(
            "POST",
            "/api/v1/sessions",
            body={
                "agent": {
                    "name": "image-smoke",
                    "provider": "fake",
                    "model_name": "fake-v1",
                }
            },
        )
        if session_status != 201:
            raise RuntimeError("session creation failed")
        session_id = json.loads(session_body)["id"]
        secret = "UNIQUE-IMAGE-SMOKE-SECRET"
        calls = (
            (
                "github.list_issues",
                {"repository": "demo/backend", "state": "open"},
                200,
            ),
            (
                "email.send",
                {
                    "recipient": "smoke@example.com",
                    "subject": "Smoke",
                    "body": f"Bearer {secret}",
                },
                200,
            ),
            ("database.query", {"query": "DROP TABLE projects"}, 403),
        )
        captured = ""
        for tool, arguments, expected in calls:
            status, body = _request(
                "POST",
                "/api/v1/tool-calls",
                body={
                    "session_id": session_id,
                    "tool": tool,
                    "tool_version": "1.0.0",
                    "arguments": arguments,
                },
                headers={"Idempotency-Key": str(uuid4())},
            )
            if status != expected:
                raise RuntimeError(f"{tool} returned {status}, expected {expected}")
            captured += body
        dashboard_status, dashboard = _request("GET", "/ui")
        if dashboard_status != 200:
            raise RuntimeError("dashboard failed")
        captured += dashboard
        if secret in captured:
            raise RuntimeError("unique image-smoke secret leaked")
        print(f"PASS image={IMAGE} user={user} safe=200 flagged=200 blocked=403")
        return 0
    finally:
        subprocess.run(["docker", "rm", "-f", api, postgres], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())

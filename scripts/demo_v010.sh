#!/usr/bin/env bash
set -euo pipefail

cleanup=false
ollama=false
for argument in "$@"; do
  case "$argument" in
    --cleanup) cleanup=true ;;
    --ollama) ollama=true ;;
    *) echo "unknown argument: $argument" >&2; exit 2 ;;
  esac
done

docker compose --profile observability up -d postgres jaeger
uv run alembic upgrade head
uv run python -m toolwatch.seed

if ! curl --fail --silent http://localhost:8000/health/live >/dev/null; then
  echo "Start the API in another terminal with: make run" >&2
  exit 2
fi

session_id="$(
  curl --fail --silent -X POST http://localhost:8000/api/v1/sessions \
    -H 'Content-Type: application/json' \
    -d '{"agent":{"name":"v010-demo","provider":"fake","model_name":"fake-v1"}}' |
    uv run python -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)"

call() {
  local key="$1"
  local payload="$2"
  curl --silent -X POST http://localhost:8000/api/v1/tool-calls \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $key" \
    -d "$payload"
  echo
}

call "11111111-1111-4111-8111-111111111111" \
  "{\"session_id\":\"$session_id\",\"tool\":\"github.list_issues\",\"tool_version\":\"1.0.0\",\"arguments\":{\"repository\":\"demo/backend\",\"state\":\"open\"}}"
call "22222222-2222-4222-8222-222222222222" \
  "{\"session_id\":\"$session_id\",\"tool\":\"email.send\",\"tool_version\":\"1.0.0\",\"arguments\":{\"recipient\":\"demo@example.com\",\"subject\":\"Sensitive demo\",\"body\":\"Bearer UNIQUE-DEMO-V010-SECRET\"}}"
call "33333333-3333-4333-8333-333333333333" \
  "{\"session_id\":\"$session_id\",\"tool\":\"database.query\",\"tool_version\":\"1.0.0\",\"arguments\":{\"query\":\"DROP TABLE projects\"}}"

uv run python -m toolwatch.attack_lab run destructive-sql
uv run python -m toolwatch.attack_lab run indirect-prompt-injection

if "$ollama"; then
  uv run python scripts/verify_ollama_agent.py
fi

echo "Dashboard: http://localhost:8000/ui"
echo "API docs:  http://localhost:8000/docs"
echo "Metrics:   http://localhost:8000/metrics"
echo "Jaeger:    http://localhost:16686"

if "$cleanup"; then
  docker compose --profile observability down
else
  echo "Stack left running. Pass --cleanup to stop it after the demo."
fi

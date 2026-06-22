# ToolWatch

ToolWatch is an observability and runtime-safety proxy for AI-agent tool calls. It is
designed to validate calls, apply deterministic safety controls, redact sensitive data,
and provide auditability before trusted adapters reach downstream services. The current
milestone implements Security Pipeline v1 for three trusted in-process mock adapters:
recursive redaction, deterministic risk/rules, sanitized persistence, audit events, and
PostgreSQL-backed replay. Ollama Agent Loop v1 optionally connects a developer-managed
local model while keeping every model-requested tool call inside the same ToolWatch
execution pipeline. It does not connect to any real GitHub, email, database, or other
external service.

Observability v1 adds OpenTelemetry request and execution traces, safe structured-log
correlation, append-only audit correlation, and Prometheus-compatible metrics. Telemetry
contains metadata only: prompts, arguments, results, rule evidence, adapter configuration,
authorization data, exception messages, and stack traces are excluded.

ToolWatch is experimental and is not production-ready.

## Architecture

The application is a modular monolith with dependency direction
`API → Application → Domain`; infrastructure implements domain-facing ports. The API
exposes health checks, registry/session APIs, and `/api/v1/tool-calls`. Application use
cases own short transaction boundaries; adapter I/O runs outside PostgreSQL transactions.
Only sanitized arguments and result bodies cross the persistence, audit, logging, and
read-API boundary. Raw values exist transiently inside validated execution only.

See [the architecture guide](docs/architecture.md), [product specification](docs/product-spec.md),
and [threat model](docs/threat-model.md).

## Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose

Ollama is optional. On macOS it runs directly on the developer machine, outside the
application containers:

```bash
brew install ollama
ollama serve
ollama pull qwen3:4b
```

## Local development

Create the environment file and install dependencies:

```bash
cp .env.example .env
uv sync --frozen
```

Start PostgreSQL and Jaeger, apply migrations, and run the API:

```bash
make infra-up
make migrate
make run
```

The API is available at <http://localhost:8000>. Health endpoints:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/health/ollama
```

Register and list tools:

```bash
curl -X POST http://localhost:8000/api/v1/tools \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "github.list_issues",
    "description": "List issues",
    "version": "1.0.0",
    "input_schema": {"type": "object", "properties": {}},
    "base_risk_level": "low",
    "adapter_type": "mock",
    "adapter_config": {"fixture": "issues"}
  }'

curl http://localhost:8000/api/v1/tools
```

Create and complete an agent session:

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "agent": {
      "name": "local-demo-agent",
      "provider": "ollama",
      "model_name": "qwen3:4b",
      "version": "1"
    },
    "user_prompt": "Check open issues",
    "metadata": {"source": "demo"}
  }'

curl -X POST http://localhost:8000/api/v1/sessions/<session-id>/complete \
  -H 'Content-Type: application/json' \
  -d '{"status": "completed"}'
```

Prompt storage is disabled by default (`STORE_PROMPTS=false`), so raw prompts are not
persisted. Tool adapter configuration is not returned by read APIs. Registering a tool
does not make any downstream call.

Seed the three reviewed mock definitions and four default development rules explicitly:

```bash
make seed
```

Execute each mock tool using the created session ID:

```bash
curl -X POST http://localhost:8000/api/v1/tool-calls \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 11111111-1111-4111-8111-111111111111' \
  -d '{"session_id":"<session-id>","tool":"github.list_issues","tool_version":"1.0.0","arguments":{"repository":"demo/backend","state":"open"}}'

curl -X POST http://localhost:8000/api/v1/tool-calls \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 22222222-2222-4222-8222-222222222222' \
  -d '{"session_id":"<session-id>","tool":"email.send","tool_version":"1.0.0","arguments":{"recipient":"user@example.com","subject":"Summary","body":"Two open issues."}}'

curl -X POST http://localhost:8000/api/v1/tool-calls \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 33333333-3333-4333-8333-333333333333' \
  -d '{"session_id":"<session-id>","tool":"database.query","tool_version":"1.0.0","arguments":{"query":"SELECT id, name FROM projects"}}'
```

An email body containing `Bearer example-secret` is persisted and returned as
`[REDACTED]`, with `sensitive_input` and HMAC-derived internal fingerprint metadata.
Production deployments must set a strong independent `REDACTION_FINGERPRINT_KEY`; the
checked-in value is development-only.

The seeded destructive-SQL and multiple-statement rules return `403 tool_call_blocked`
before the adapter runs. Email side effects are flagged, while the read-only GitHub
fixture is normally allowed. Rules are available under `/api/v1/rules`.

Audit events can be read from:

```bash
curl http://localhost:8000/api/v1/audit-events
curl http://localhost:8000/api/v1/sessions/<session-id>/audit-events
curl http://localhost:8000/api/v1/tool-calls/<call-id>/audit-events
```

Repeating a terminal request with the same idempotency key and identical body reconstructs
the sanitized response from PostgreSQL, including after process restart, without invoking
the adapter. Reusing the key for a different request returns `409 idempotency_conflict`;
an overlapping duplicate returns `409 execution_in_progress`.

The indirect prompt-injection detector is a conservative string heuristic. It flags
suspicious tool output but is not a guarantee and does not itself prove malicious intent.
Ollama remains optional and is contacted only when an Ollama agent run is requested.

## Local agent loop

The fake provider is deterministic and is the default:

```bash
make seed
make agent-demo PROVIDER=fake PROMPT="Check open issues in demo/backend"
```

Run the optional local Ollama provider:

```bash
export AGENT_PROVIDER=ollama
export OLLAMA_MODEL=qwen3:4b
export OLLAMA_ALLOWED_MODELS=qwen3:4b
make agent-demo PROVIDER=ollama PROMPT="Check open issues in demo/backend"
```

Or call the synchronous API with an existing active session:

```bash
curl -X POST http://localhost:8000/api/v1/agent-runs \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<session-id>","provider":"ollama","model":"qwen3:4b","prompt":"Check open issues in demo/backend and summarize."}'

curl http://localhost:8000/api/v1/agent-runs/<run-id>
curl http://localhost:8000/api/v1/agent-runs
```

Agent runs are visible at <http://localhost:8000/ui/agent-runs>. The loop is synchronous
and bounded by configured turn, tool-call, payload, model-call, and total-run limits.
Multiple tool calls execute sequentially in model order.

Tool definitions come only from enabled trusted registry entries. Provider/model
selection is allowlisted. Tool arguments still pass through schema validation, redaction,
risk classification, blocking rules, timeout handling, audit, and telemetry.

Full prompts, conversation history, raw provider responses, raw tool arguments/results,
and model thinking are never persisted. Thinking is not returned by the API or dashboard.
Only redacted final content and safe run/model metadata are stored.

Live smoke verification requires the API, PostgreSQL, and local Ollama to be running:

```bash
make verify-ollama-agent
```

The script never pulls a model automatically. If Ollama reports the configured model is
missing, run `ollama pull qwen3:4b` manually.

Stop local infrastructure with:

```bash
make infra-down
```

## Docker Compose

Build and start the API and PostgreSQL:

```bash
make docker-up
```

The API container applies Alembic migrations before starting Uvicorn. To include Jaeger:

```bash
docker compose --profile observability up -d --build
```

Open <http://localhost:16686>, select the `toolwatch` service, and search after executing
a seeded tool call. An allowed trace contains the HTTP server span,
application/security spans, and `execute_tool <tool name>`. A blocked call deliberately
has no adapter-execution span.

Metrics and coarse telemetry health are available at:

```bash
curl http://localhost:8000/metrics
curl http://localhost:8000/health/telemetry
```

Every response includes `X-Correlation-ID`. A canonical UUID is reused; malformed or
oversized values are replaced. Audit events can be joined to traces:

```bash
curl 'http://localhost:8000/api/v1/audit-events?trace_id=<32-lowercase-hex>'
curl 'http://localhost:8000/api/v1/audit-events?correlation_id=<uuid>'
```

Jaeger is optional. If it is unavailable, execution and database readiness continue.
Local development samples all traces. Non-development deployments should set
`OTEL_TRACE_SAMPLE_RATIO` deliberately while retaining audit events as the authoritative
security history.

Stop the stack with:

```bash
make docker-down
```

## Dashboard and Attack Lab

ToolWatch ships a server-rendered operational dashboard mounted at `/ui`. It uses
Jinja2 templates, a small locally vendored HTMX subset, and hand-written CSS. There
is no Node.js, npm, or CDN dependency.

```bash
make demo                 # start infrastructure, apply migrations, seed tools and rules
make run                  # in another terminal, start the API with reload
open http://localhost:8000/ui
```

The dashboard provides:

- a summary of total/active sessions, total/blocked/flagged/failed/timed-out/replayed
  calls, risk-flag counts, and redaction-event counts;
- a sessions list with status, agent identity, started time, tool-call count, highest
  observed risk, and blocked/flagged/failed counters;
- session detail with chronological tool-call and audit timelines;
- tool-call detail with sanitized arguments, sanitized result, risk flags, matched
  rules, audit history, correlation IDs, and a strictly validated Jaeger trace link
  when `JAEGER_UI_PUBLIC_URL` is configured;
- a read-only rules list;
- a paginated audit-event list with filters by event type, trace ID, and correlation
  ID;
- the Attack Lab.

The dashboard is read-only. It never displays raw prompts, raw arguments, raw
results, secrets, HMAC fingerprints, adapter configuration, internal hostnames, or
exception messages. The only state-changing route is `POST /ui/attacks/{id}/run`,
gated by `ATTACK_LAB_ENABLED`. Every UI response sets a strict
`Content-Security-Policy` with `default-src 'self'`, `frame-ancestors 'none'`, and
`form-action 'self'`, plus `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Permissions-Policy`, and `Cache-Control: no-store`.

The dashboard does **not** implement authentication. Do not expose it to the public
Internet.

The Attack Lab ships a static, immutable registry of twelve reproducible scenarios.
Each scenario runs through the real ToolWatch execution pipeline (sessions API,
tool-call API, security pipeline, audit, telemetry); arbitrary user-submitted tools
or payloads are not supported. The Attack Lab can be driven from the dashboard, from
Make targets, or directly through the module:

```bash
make attack-list
make attack-run SCENARIO=destructive-sql
make attack-run-all

uv run python -m toolwatch.attack_lab list
uv run python -m toolwatch.attack_lab run sensitive-email-input
```

Once an attack scenario completes, follow the rendered link to inspect the resulting
sanitized session, tool-call detail, and audit timeline. Critical and high-risk
calls also appear on the dashboard home.

Run the live Jaeger smoke verification after starting the observability profile:

```bash
make verify-jaeger
```

The script issues a deterministic allowed call (`github.list_issues`) and a blocked
call (`DROP TABLE …` against `database.query`), polls Jaeger for the
`execute_tool github.list_issues` span, confirms there is no `execute_tool
database.query` span, and verifies that a unique synthetic secret never appears in
any captured trace. It uses bounded retries and a hard timeout.

## Verification

```bash
make test-unit
make test-domain
make test-api
make test-integration
make lint
make typecheck
make check
```

Integration tests require Docker and start an isolated PostgreSQL container. Tests marked
`local_llm` are excluded from normal test and CI runs. See [the testing guide](docs/testing.md).

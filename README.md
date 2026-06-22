# ToolWatch

ToolWatch is an observability and runtime-safety proxy for AI-agent tool calls. It is
designed to validate calls, apply deterministic safety controls, redact sensitive data,
and provide auditability before trusted adapters reach downstream services. The current
milestone implements Security Pipeline v1 for three trusted in-process mock adapters:
recursive redaction, deterministic risk/rules, sanitized persistence, audit events, and
PostgreSQL-backed replay. It does not connect to Ollama or any real GitHub, email,
database, or other external service.

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

Ollama is not required for this milestone. Future local-LLM demos will run Ollama
directly on the developer machine, outside the application containers.

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
Ollama remains disconnected and optional.

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

Stop the stack with:

```bash
make docker-down
```

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

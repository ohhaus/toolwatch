# ToolWatch

ToolWatch is an observability and runtime-safety proxy for AI-agent tool calls. It is
designed to validate calls, apply deterministic safety controls, redact sensitive data,
and provide auditability before trusted adapters reach downstream services. The current
milestone implements a trusted Tool Registry and Agent Sessions backed by PostgreSQL. It
does not implement tool execution, adapters, LLM integration, risk evaluation, blocking
rules, audit events, or a dashboard.

ToolWatch is experimental and is not production-ready.

## Architecture

The application is a modular monolith with dependency direction
`API → Application → Domain`; infrastructure implements domain-facing ports. The API
exposes health checks plus `/api/v1/tools` and `/api/v1/sessions`. Application use cases
own transaction boundaries; SQLAlchemy repositories do not leak persistence models into
the domain.

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

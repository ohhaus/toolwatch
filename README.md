# ToolWatch

ToolWatch is an observability and runtime-safety proxy for AI-agent tool calls. It is
designed to validate calls, apply deterministic safety controls, redact sensitive data,
and provide auditability before trusted adapters reach downstream services. This
repository currently contains the Milestone 1 development foundation only; it does not
yet implement the tool execution pipeline.

ToolWatch is experimental and is not production-ready.

## Architecture

The application is a modular monolith with dependency direction
`API → Application → Domain`; infrastructure implements domain-facing ports. The
bootstrap exposes a FastAPI service, PostgreSQL connectivity, and Alembic migrations.
The package uses a `src/` layout, and database connections are created lazily so module
imports and liveness checks do not depend on PostgreSQL.

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
make test-integration
make lint
make typecheck
make check
```

Integration tests require Docker and start an isolated PostgreSQL container. Tests marked
`local_llm` are excluded from normal test and CI runs. See [the testing guide](docs/testing.md).

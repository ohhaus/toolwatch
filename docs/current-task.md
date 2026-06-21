# Current Task: Bootstrap the ToolWatch Repository

> Implementation status: implemented on 2026-06-22; verification results are recorded in
> the completing agent's report. This file remains the acceptance contract for
> Milestone 1.

## Role

You are bootstrapping the ToolWatch codebase from the existing repository.

The current repository contains:

```text
.
├── AGENTS.md
├── docs
│   ├── architecture.md
│   ├── current-task.md
│   ├── product-spec.md
│   └── threat-model.md
├── main.py
├── Makefile
├── pyproject.toml
├── README.md
├── SECURITY.md
└── uv.lock
```

Read the following files before changing anything:

1. `AGENTS.md`
2. `docs/product-spec.md`
3. `docs/architecture.md`
4. `docs/threat-model.md`
5. `README.md`
6. `pyproject.toml`
7. `Makefile`
8. the existing `main.py`

Treat `AGENTS.md` and `docs/product-spec.md` as authoritative.

---

## Goal

Create a clean, production-oriented development foundation for ToolWatch.

The result must include:

* a Python `src` package layout;
* a minimal FastAPI application;
* application configuration;
* PostgreSQL;
* Alembic;
* Dockerfile;
* Docker Compose;
* liveness and readiness endpoints;
* unit and integration test foundations;
* linting, formatting, and type checking;
* GitHub Actions CI;
* updated Makefile and documentation.

The task is repository bootstrap only.

Do not implement ToolWatch business features yet.

---

## Required architecture

Create this initial structure:

```text
.
├── AGENTS.md
├── README.md
├── SECURITY.md
├── Makefile
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
├── alembic.ini
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── src/
│   └── toolwatch/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       │
│       ├── api/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   └── health.py
│       │
│       ├── application/
│       │   └── __init__.py
│       │
│       ├── domain/
│       │   └── __init__.py
│       │
│       ├── security/
│       │   └── __init__.py
│       │
│       ├── infrastructure/
│       │   ├── __init__.py
│       │   └── database/
│       │       ├── __init__.py
│       │       ├── base.py
│       │       ├── engine.py
│       │       └── health.py
│       │
│       └── telemetry/
│           └── __init__.py
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   └── test_liveness.py
│   └── integration/
│       └── test_database_readiness.py
│
├── docs/
│   ├── architecture.md
│   ├── current-task.md
│   ├── product-spec.md
│   ├── testing.md
│   ├── threat-model.md
│   └── adr/
│       └── 0001-modular-monolith.md
│
└── .github/
    └── workflows/
        └── ci.yml
```

Small adjustments are allowed only when justified by the existing repository or tooling.

Do not create placeholder modules beyond the listed architecture.

---

## Application requirements

### Application factory

Move the application from root `main.py` into:

```text
src/toolwatch/main.py
```

Implement:

```python
def create_app() -> FastAPI:
    ...
```

Also expose:

```python
app = create_app()
```

Configure:

* title: `ToolWatch`;
* version from package metadata or a single project constant;
* API router;
* no database connection during module import;
* no global mutable service objects.

Remove root `main.py` after its functionality has been migrated.

### Health endpoints

Implement:

```http
GET /health/live
GET /health/ready
```

#### Liveness

`GET /health/live` must:

* return HTTP 200 while the process is running;
* avoid checking PostgreSQL or external services;
* return:

```json
{
  "status": "ok",
  "service": "toolwatch"
}
```

#### Readiness

`GET /health/ready` must:

* execute a lightweight PostgreSQL query such as `SELECT 1`;
* return HTTP 200 when PostgreSQL is available;
* return HTTP 503 with a sanitized response when unavailable;
* never expose the database URL or raw exception.

Example success:

```json
{
  "status": "ready",
  "database": "available"
}
```

Example failure:

```json
{
  "status": "not_ready",
  "database": "unavailable"
}
```

---

## Configuration

Use `pydantic-settings`.

Create a typed settings object supporting:

```text
APP_NAME
APP_VERSION
ENVIRONMENT
LOG_LEVEL
DATABASE_URL
DATABASE_POOL_SIZE
DATABASE_MAX_OVERFLOW
DATABASE_CONNECT_TIMEOUT_SECONDS
```

Requirements:

* load values from environment variables;
* support local `.env`;
* do not commit `.env`;
* provide safe defaults only for non-sensitive development settings;
* keep `.env.example` free of real credentials;
* cache settings using a controlled dependency function;
* do not access environment variables throughout arbitrary modules.

Suggested local URL:

```text
postgresql+asyncpg://toolwatch:toolwatch@localhost:5432/toolwatch
```

Suggested container URL:

```text
postgresql+asyncpg://toolwatch:toolwatch@postgres:5432/toolwatch
```

---

## Database

Use:

* PostgreSQL;
* SQLAlchemy 2 async engine;
* asyncpg;
* Alembic.

Implement:

* declarative base;
* async engine factory;
* async session factory;
* database readiness check;
* proper engine disposal;
* no application-domain models yet.

Create an initial empty or metadata bootstrap migration only if Alembic requires it. Do not invent ToolWatch entities during this task.

Integration tests must use real PostgreSQL, preferably through Testcontainers.

Do not use SQLite.

---

## Dockerfile

Create a secure multi-stage or otherwise minimal Dockerfile.

Requirements:

* use an official slim Python image compatible with Python 3.13;
* install dependencies from `uv.lock`;
* use `uv sync --frozen`;
* copy dependency metadata before application code for build caching;
* run as a non-root user;
* do not bake `.env` or secrets into the image;
* set sensible Python environment variables;
* expose the API port;
* start Uvicorn without `--reload`;
* include a container healthcheck or rely on the Compose healthcheck;
* keep the final image free of unnecessary build tools where practical.

Expected application command:

```text
uvicorn toolwatch.main:app --host 0.0.0.0 --port 8000
```

Do not install Ollama in the API image.

---

## Docker Compose

Create `compose.yaml` with:

### `api`

* built from the local Dockerfile;
* depends on healthy PostgreSQL;
* reads development settings from environment;
* publishes port `8000`;
* has a healthcheck against `/health/live`;
* connects to the application network.

### `postgres`

* use a current official PostgreSQL image;
* configure a development-only database, user, and password;
* store data in a named volume;
* publish port `5432` for local development;
* include a `pg_isready` healthcheck.

### `jaeger`

* use the all-in-one Jaeger image;
* expose the UI and OTLP endpoints needed later;
* do not require application telemetry implementation in this task.

### Profiles

Jaeger may use an `observability` profile if that makes the default stack lighter.

Do not add:

* Ollama container;
* Redis;
* Kafka;
* Prometheus;
* Grafana;
* mock tools.

Ollama will run directly on macOS in future milestones.

---

## Makefile

Provide at least these commands:

```text
install
infra-up
infra-down
run
migrate
test
test-unit
test-integration
lint
format
typecheck
check
docker-build
docker-up
docker-down
```

Behavior:

* `infra-up` starts PostgreSQL and optional local infrastructure;
* `run` starts local FastAPI with reload;
* `migrate` applies Alembic migrations;
* `test` excludes `local_llm`;
* `check` runs lint, formatting check, type checking, and tests;
* commands must fail when an underlying command fails.

Keep commands short and predictable.

---

## Python tooling

Configure `pyproject.toml` for:

* Python 3.13;
* FastAPI;
* Uvicorn;
* Pydantic Settings;
* SQLAlchemy 2;
* asyncpg;
* Alembic;
* HTTPX;
* pytest;
* pytest-asyncio;
* Testcontainers PostgreSQL;
* Ruff;
* Pyright.

Configure Ruff for:

* linting;
* import sorting;
* formatting;
* a practical line length.

Configure pytest markers:

```text
integration
local_llm
```

Configure asyncio behavior explicitly.

Do not add Ollama dependencies in this bootstrap task unless required only as an optional dependency group.

---

## Tests

### Unit test

Test `/health/live` using the FastAPI application and an HTTPX ASGI transport or equivalent.

It must not require:

* Docker;
* PostgreSQL;
* Ollama;
* network access.

### Integration test

Test `/health/ready` against PostgreSQL started through Testcontainers.

Cover:

* ready database returns HTTP 200;
* unavailable database returns HTTP 503;
* failure response is sanitized.

Integration tests may be marked `integration`.

Do not mock PostgreSQL in the integration test.

---

## CI

Create `.github/workflows/ci.yml`.

Run on:

* pushes to the default branch;
* pull requests.

Required jobs or steps:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not local_llm"
```

Requirements:

* use Python 3.13;
* cache uv dependencies when practical;
* do not install or run Ollama;
* do not require cloud credentials;
* support Testcontainers or provide a PostgreSQL service for integration tests;
* fail on lint, type, migration, or test failures.

Also verify that Alembic can upgrade an empty database.

---

## Documentation

Update `README.md` with:

* one-paragraph product explanation;
* architecture summary;
* prerequisites;
* local development commands;
* Docker Compose commands;
* test commands;
* links to the product specification and threat model;
* explicit statement that the project is experimental and not production-ready.

Create or update:

### `docs/architecture.md`

Document:

* modular-monolith decision;
* dependency direction;
* development topology;
* container topology;
* why Ollama remains outside Docker during development.

### `docs/testing.md`

Document:

* unit versus integration tests;
* Testcontainers requirements;
* `local_llm` marker;
* required verification commands.

### `docs/adr/0001-modular-monolith.md`

Record:

* context;
* decision;
* consequences;
* rejected early microservices approach.

Do not rewrite `docs/product-spec.md` unless correcting a direct inconsistency discovered during implementation.

---

## Files to create

At minimum:

```text
Dockerfile
compose.yaml
.dockerignore
.env.example
.gitignore
alembic.ini
alembic/*
src/toolwatch/*
tests/*
docs/testing.md
docs/adr/0001-modular-monolith.md
.github/workflows/ci.yml
```

Update:

```text
pyproject.toml
uv.lock
Makefile
README.md
docs/architecture.md
```

Move or remove:

```text
main.py
```

after migrating its behavior.

---

## Non-goals

Do not implement:

* Agent entities;
* ToolDefinition;
* sessions;
* tool-call endpoints;
* tool adapters;
* mock GitHub, email, or database tools;
* secret redaction;
* risk classification;
* blocking rules;
* audit events;
* OpenTelemetry instrumentation;
* dashboard;
* CLI;
* Ollama integration;
* MCP support.

Creating empty package boundaries is allowed. Implementing their behavior is not.

---

## Acceptance criteria

The task is complete only when all conditions hold:

1. `uv sync --frozen` succeeds.
2. The package imports from `src/toolwatch`.
3. Root `main.py` is no longer the application entry point.
4. `make run` starts FastAPI locally.
5. `GET /health/live` returns HTTP 200 without PostgreSQL.
6. `GET /health/ready` returns HTTP 200 with PostgreSQL available.
7. `GET /health/ready` returns sanitized HTTP 503 when PostgreSQL is unavailable.
8. Alembic upgrades an empty PostgreSQL database.
9. Unit tests run without Docker or PostgreSQL.
10. Integration tests use real PostgreSQL.
11. `make lint` passes.
12. `make typecheck` passes.
13. `make test` passes.
14. `make check` passes.
15. `docker compose up --build` starts a healthy API and PostgreSQL.
16. The API container runs as a non-root user.
17. No real secrets are committed.
18. README instructions work from a clean checkout.
19. CI is green.
20. No product business functionality outside this task was added.

---

## Required implementation process

Before writing code:

1. inspect every existing repository file;
2. summarize the current state;
3. identify inconsistencies between existing files;
4. present a concise implementation plan;
5. do not ask for confirmation unless blocked by missing information.

During implementation:

1. make incremental changes;
2. preserve the existing product specification;
3. avoid unrelated refactors;
4. run focused checks after each coherent stage;
5. fix issues instead of bypassing checks.

Before completion:

1. run all acceptance checks available in the environment;
2. inspect the final repository tree;
3. inspect Git diff;
4. verify no secrets or generated local files were added;
5. update documentation;
6. report:

   * files created;
   * files modified;
   * files removed;
   * architectural decisions;
   * commands executed;
   * test results;
   * checks that could not be run;
   * remaining risks.

Do not claim a check passed unless it was actually executed successfully.

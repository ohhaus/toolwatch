# Architecture

## Decision

ToolWatch begins as a modular monolith. The API, application orchestration, domain,
deterministic security components, infrastructure, and telemetry live in one deployable
Python package with explicit package boundaries.

The dependency direction is:

```text
API → Application → Domain
          ↓
Infrastructure implements ports owned by inner layers
```

The domain must not import FastAPI, SQLAlchemy, HTTP clients, LLM SDKs, or telemetry
SDKs. Security decisions remain deterministic and independent of an LLM. The bootstrap
contains empty package boundaries for future milestones but no premature abstractions or
business entities.

The durable rationale is recorded in
[ADR 0001](adr/0001-modular-monolith.md).

## Runtime construction

`toolwatch.main.create_app()` constructs the FastAPI application and registers the API
router. Configuration is loaded through one cached `get_settings()` dependency. The
SQLAlchemy async engine and session factory are also exposed through controlled,
lazy caches.

Importing the application does not connect to PostgreSQL. `/health/live` performs no
downstream checks. `/health/ready` obtains the engine on demand and runs `SELECT 1`;
infrastructure failures are reduced to a fixed public response without exception details
or connection strings. The application lifespan disposes the engine pool on shutdown.

## Development topology

The recommended local topology is:

```text
FastAPI    local Python process
PostgreSQL Docker
Jaeger     Docker, optional observability profile
Ollama     local macOS process in a future milestone
```

Keeping FastAPI on the host gives quick reloads while PostgreSQL remains reproducible.
Integration tests use their own PostgreSQL Testcontainer rather than sharing the
development database.

Ollama remains outside Docker because it is optional, hardware-dependent developer
software and must not become a startup or CI dependency for the core API.

## Container topology

The default Compose stack contains the API and PostgreSQL on a private application
network. PostgreSQL must pass `pg_isready` before the API starts. The API applies Alembic
migrations, starts Uvicorn as a non-root user, and reports liveness through an HTTP
healthcheck. PostgreSQL data is stored in a named development volume.

Jaeger is available through the `observability` profile and exposes its UI and OTLP
ports. Telemetry instrumentation is intentionally deferred to a later milestone.

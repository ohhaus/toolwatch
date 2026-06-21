# Testing

## Test layers

Unit tests live in `tests/unit`. They must not require Docker, PostgreSQL, Ollama,
network access, paid APIs, or real credentials. The bootstrap unit suite verifies that
the liveness endpoint works through HTTPX's in-process ASGI transport. Domain tests cover
tool validation and session transitions; application tests use repository fakes; OpenAPI
tests verify the milestone endpoints and response declarations.

Execution-pipeline unit tests cover the `ToolCall` state machine, canonical hashing,
restricted Draft 2020-12 schemas and explicit formats, payload depth/string limits,
trusted mock adapters, timeout handling, invalid output, and idempotent orchestration
with injected counters. Adapter tests perform no network I/O.

Integration tests live in `tests/integration` and carry the `integration` marker. They
use one disposable PostgreSQL 17 Testcontainer; SQLite is not an acceptable substitute.
The suite applies Alembic to an empty database, exercises downgrade/upgrade, verifies
UUID/FK/JSONB persistence, pagination, sanitized failures, prompt omission, duplicate
tool races, and concurrent logical-agent reuse.

Execution integration tests verify named idempotency and sequence constraints,
one-to-one result metadata, terminal persistence, concurrent same-key at-most-once
behavior, concurrent sequence allocation, payload-free read APIs, and absence of raw
argument and result fixtures from database rows and captured logs.

Tests requiring a developer-managed Ollama process must carry the `local_llm` marker.
That marker is excluded by `make test`, `make check`, and CI. No such tests are part of
the bootstrap milestone.

## Commands

```bash
make test-unit
make test-domain
make test-api
make test-integration
make test
make lint
make typecheck
make check
```

`make test-unit` can run without Docker. Integration and full test commands require a
working Docker daemon. `make check` is the required local verification gate and runs
Ruff linting, Ruff formatting checks, Pyright, and all non-`local_llm` tests.

To verify migrations independently:

```bash
make infra-up
make migrate
```

CI additionally applies Alembic migrations to an empty PostgreSQL service before running
the test suite.

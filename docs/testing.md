# Testing

## Test layers

Unit tests live in `tests/unit`. They must not require Docker, PostgreSQL, Ollama,
network access, paid APIs, or real credentials. The bootstrap unit suite verifies that
the liveness endpoint works through HTTPX's in-process ASGI transport. Domain tests cover
tool validation and session transitions; application tests use repository fakes; OpenAPI
tests verify the milestone endpoints and response declarations.

Integration tests live in `tests/integration` and carry the `integration` marker. They
use one disposable PostgreSQL 17 Testcontainer; SQLite is not an acceptable substitute.
The suite applies Alembic to an empty database, exercises downgrade/upgrade, verifies
UUID/FK/JSONB persistence, pagination, sanitized failures, prompt omission, duplicate
tool races, and concurrent logical-agent reuse.

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

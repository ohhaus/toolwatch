# Testing

## Test layers

Unit tests live in `tests/unit`. They must not require Docker, PostgreSQL, Ollama,
network access, paid APIs, or real credentials. The bootstrap unit suite verifies that
the liveness endpoint works through HTTPX's in-process ASGI transport.

Integration tests live in `tests/integration` and carry the `integration` marker. They
use Testcontainers to start a real PostgreSQL instance; SQLite is not an acceptable
substitute. The readiness suite checks both a successful query and a sanitized
unavailable-database response.

Tests requiring a developer-managed Ollama process must carry the `local_llm` marker.
That marker is excluded by `make test`, `make check`, and CI. No such tests are part of
the bootstrap milestone.

## Commands

```bash
make test-unit
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

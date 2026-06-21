## Mission

You are the most talented programmer of your generation, and you direct all of your talent toward building **ToolWatch**.

Produce secure, clear, maintainable code. Prefer correctness and verified behavior over speed, cleverness, or unnecessary complexity.

## Project

ToolWatch is an observability and runtime-safety proxy for AI-agent tool calls.


## Security rules

- Unknown or disabled tools must never execute.
- Security decisions must be deterministic and must not depend on an LLM.
- Redact data before logging, tracing, persistence, or rendering.
- Never store raw secrets.
- Invalid arguments must never reach adapters.
- Blocked calls must never reach downstream services.
- Treat LLM and tool outputs as untrusted input.
- Add a regression test for every security bug fix.
- Never weaken validation to make tests pass.

## Commands

```bash
uv sync
make infra-up
uv run alembic upgrade head
make run
make test
make lint
make typecheck
make check
```

Tests requiring Ollama must use the `local_llm` marker and must not run in default CI.

## Coding and testing

- Use Python 3.13 and type public functions.
- Use async only for real I/O.
- Keep changes focused; avoid unrelated refactors.
- Do not add dependencies without a clear need.
- Unit tests must not require Docker, Ollama, network access, or paid APIs.
- Integration tests must use PostgreSQL, not SQLite.
- Never use real credentials or real external services in tests.
- Run focused tests and `make check` before completing a task.

## Scope limits

Do not add without an explicit task:

- OAuth server;
- RBAC/ABAC/ReBAC;
- production multi-tenancy;
- human approvals;
- Kubernetes or Kafka;
- Vault;
- arbitrary shell or outbound HTTP execution;
- real payment integrations;
- ML-based security decisions;
- production-grade MCP gateway.

## Documentation

Update the relevant file when behavior changes:

- API behavior → OpenAPI, tests, README examples;
- architecture → `docs/architecture.md` and ADRs;
- security → `docs/threat-model.md`;
- active work → `docs/current-task.md`.

Keep detailed requirements in `docs/product-spec.md`, not in this file.

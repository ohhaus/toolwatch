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

Security unit tests include Hypothesis properties for JSON compatibility and redaction
idempotence, plus deterministic coverage for key/value detectors, HMAC fingerprints,
depth/node limits, SQL risk, indirect prompt injection, finite rule conditions, priority,
and block precedence.

Observability unit tests use an in-memory span exporter and a fresh isolated Prometheus
registry per test. They verify W3C parent propagation, correlation UUID validation,
parent-child span relationships, disabled/no-op behavior, bounded labels, exporter
failure isolation, blocked calls without adapter spans, replay metrics, and safe
shutdown. Unique prompt, argument, result, exporter-exception, and rule-evidence values
are searched across spans, events, metric output, structured logs, audit fields, and
public responses.

Integration tests live in `tests/integration` and carry the `integration` marker. They
use one disposable PostgreSQL 17 Testcontainer; SQLite is not an acceptable substitute.
The suite applies Alembic to an empty database, exercises downgrade/upgrade, verifies
UUID/FK/JSONB persistence, pagination, sanitized failures, prompt omission, duplicate
tool races, and concurrent logical-agent reuse.

Execution integration tests verify named idempotency and sequence constraints,
one-to-one sanitized results, terminal persistence, concurrent same-key at-most-once
behavior, concurrent sequence allocation, restart-safe PostgreSQL replay, blocked
downstream prevention, audit ordering, and absence of unique raw input/output secrets
from database rows, logs, errors, audit payloads, and API reads.

PostgreSQL telemetry integration verifies trace/correlation persistence and indexed audit
filters while still using the in-memory exporter. CI and default tests do not require
Jaeger. The optional Compose smoke test starts the observability profile, submits allowed
and blocked calls, queries Jaeger, and inspects `/metrics` for forbidden labels.

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

Opt-in local engineering benchmarks are available without becoming a flaky CI gate:

```bash
uv run python tests/benchmarks/security_pipeline.py
```

## Dashboard, XSS regressions, and Attack Lab

Dashboard tests live in `tests/unit/web/`. They exercise the FastAPI app through
`httpx.ASGITransport` with stub repositories injected via `dependency_overrides`,
so no PostgreSQL container is required for HTML rendering checks. Coverage includes
the dashboard home, sessions list, session detail, tool-call detail, rules list,
audit list, the static Attack Lab index, the disabled-dashboard 404 path, and the
disabled-Attack-Lab path. The tests assert that every UI response sets the
documented `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`,
and `Cache-Control` headers and that locally served static assets carry the same
headers.

XSS regressions inject inert payloads through the sanitized result and risk-flag
evidence fields and assert that the rendered HTML escapes `<script>`, `<img …
onerror=…>`, and `</textarea>` constructs and that the payload is not present in
any executable position. Sanitized JSON is rendered inside `<pre>` blocks; tool
output is never used in `innerHTML` paths.

Presenter tests cover status, risk, and decision formatting, sanitized JSON
size-bounding and truncation, Jaeger link construction (only emitted for valid W3C
trace IDs with a configured base URL), pagination, and condition-summary
rendering.

Attack Lab tests are split into a unit-only registry suite and a
PostgreSQL-backed integration suite. The unit suite asserts that the registry is a
`MappingProxyType`, that all scenarios have unique alphanumeric identifiers, that
no scenario targets an adapter outside the trusted allowlist, and that lookups
return `None` for unknown identifiers. The integration suite runs each scenario
through the real ToolWatch execution pipeline, asserts the persisted outcome
matches expectations, and verifies that a unique synthetic secret never appears in
the database (for redaction-relevant scenarios), in structured logs, or in the
audit API response. The adapter-timeout scenario uses a deterministic delayed
adapter; the adapter-failure scenario injects a unique synthetic secret into the
exception body and asserts that no rendering layer leaks it.

A safety regression test confirms that no scenario can select an adapter outside
the trusted allowlist, that scenarios with `adapter_called=True` only reference
allowlisted tool names, and that scenario IDs are alphanumeric.

## Jaeger live smoke

`scripts/verify_jaeger.py` is a developer-driven smoke check that runs against a
locally started Compose `observability` profile. It issues one allowed and one
blocked tool call, polls the Jaeger query API with bounded retries and a hard
timeout, confirms the `execute_tool github.list_issues` span is present, confirms
no `execute_tool database.query` span is created for the blocked call, and
searches all returned trace JSON for a unique synthetic secret. It is excluded
from `make check` and CI. Invoke it with `make verify-jaeger`.

## Agent-loop and local Ollama tests

`FakeAgentProvider` is the CI/default provider. Scripted response sequences cover final
answers, one or several tool calls, multiple turns, blocked calls, provider failures,
ordering, persistence, audit, telemetry, and secret non-disclosure without network or
sleeping.

Local Ollama tests are marked `local_llm` and remain excluded from `make test` and CI:

```bash
ollama pull qwen3:4b
uv run pytest -m local_llm tests/integration/test_ollama_agent.py
make verify-ollama-agent
```

Local-model assertions check structure and safety (`completed`, at least one mediated
tool call, blocked calls remain blocked, final answer exists, thinking/unique secrets are
absent). They do not assert exact free-form wording.

The destructive local-model regression accepts three semantic outcomes: a destructive
database request is observed and blocked before the adapter; the model explicitly
refuses; or a configured safe loop limit is reached. Additional safe tool calls do not
fail the test. Repeat it without retries:

```bash
make test-local-llm-repeat COUNT=5
```

Recovery integration tests verify stale/fresh selection, concurrent workers, audit,
metrics, idempotence, timestamp preservation, and absence of adapter retries. Shutdown
unit tests cover cooperative drain and bounded cancellation.

Release verification commands include `make package-check`, `make image`,
`make image-smoke`, `make sbom`, `make security-scan`, `make load-test`, and
`make query-plans`.

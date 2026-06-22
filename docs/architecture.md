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
SDKs. Security decisions remain deterministic and independent of an LLM.

The durable rationale is recorded in
[ADR 0001](adr/0001-modular-monolith.md).

## Security Pipeline v1

`ToolCall` and `ToolResultMetadata` are framework-independent domain entities. A call
uses the strict lifecycle `received → validating → rejected` or
`received → validating → evaluating → blocked|executing →
succeeded|failed|timed_out`. Terminal calls cannot transition again.

Execution resolves an active session and an enabled `(tool name, version)` from the
trusted registry. Arguments are canonicalized, bounded, and validated with the restricted
JSON Schema Draft 2020-12 subset before an adapter can run. Adapter types resolve through
an immutable, explicitly constructed mapping containing only `mock_github`, `mock_email`,
and `mock_database`; database values are never treated as import paths.

Validated raw arguments exist only inside the trusted execution boundary: schema
validation, deterministic classification, and the selected allowlisted adapter. A bounded
recursive redactor runs before payload persistence, audit, logging, or read rendering.
The same boundary is applied to adapter output before storage and return.

Risk starts at the registered base level and can only rise. Input classification and
priority-ordered PostgreSQL rules run before adapter execution; `block > flag > allow`.
Output classification and result-oriented rules run after the side effect and therefore
can annotate but cannot claim prevention. No LLM participates in either decision.

### Transactions, idempotency, and sequences

The first short transaction locks the session row, verifies prerequisites, allocates the
next sequence, inserts `received`, and commits. State transitions use additional short
transactions. The adapter coroutine runs with a timeout and no open PostgreSQL
transaction. Each transition commits atomically with its sanitized audit events and safe
risk flags. Result metadata, sanitized output, and the terminal transition commit
atomically.

Per-session sequence allocation uses `SELECT ... FOR UPDATE` on the parent session before
calculating the next value. `uq_tool_calls_session_sequence` remains a database backstop.

Idempotency uses `uq_tool_calls_idempotency_key` plus the canonical request hash. A
different request with the same key conflicts. A concurrent duplicate returns
`execution_in_progress` and cannot invoke the adapter. Terminal retries reconstruct
successful, blocked, rejected, and failed outcomes from PostgreSQL. Sanitized result
payloads make replay durable across process restart without repeating a possible side
effect.

There is no distributed transaction with an adapter. A process crash after an adapter
side effect and before terminal persistence can leave an `executing` row. Adapter
cancellation after timeout is cooperative. The explicit recovery command locks stale
rows in bounded batches with `FOR UPDATE SKIP LOCKED`, changes them to failed with an
unknown/interrupted error code, and never retries a possible side effect.

The original execution choices are recorded in
[ADR 0003](adr/0003-tool-call-execution-v1.md); the security boundary is recorded in
[ADR 0004](adr/0004-security-pipeline-v1.md).

## Milestone 2 domain and persistence

The first domain entities are:

- `Agent`, identified logically by name, provider, model name, and optional version;
- `ToolDefinition`, a trusted versioned registry entry with JSON schemas, base risk,
  enabled state, and an explicit adapter type;
- `AgentSession`, with active, completed, and failed lifecycle states.

Repository protocols and the unit-of-work protocol live at the application boundary.
PostgreSQL adapters implement them with separate `agents`, `tool_definitions`, and
`agent_sessions` SQLAlchemy models. Domain entities never double as persistence models.

Each application use case opens one unit of work and owns its commit. Repository methods
flush when a database constraint must be observed but never commit. Tool uniqueness is a
named PostgreSQL constraint. Agent resolution and session creation share one transaction;
agent creation uses `ON CONFLICT DO NOTHING` followed by identity lookup so concurrent
requests reuse one logical agent. Session completion locks its row before applying the
domain transition.

The API returns domain-shaped response models and omits adapter configuration. Prompt
storage is disabled by default; the persistence column receives `NULL` unless a
developer explicitly enables temporary, deterministically sanitized storage.

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
ports.

## Observability v1

One application-owned telemetry runtime constructs the OpenTelemetry tracer provider,
OTLP HTTP exporter, and isolated Prometheus registry. Construction performs no exporter
network handshake. Shutdown attempts a bounded flush and closes the provider; failures
are sanitized and cannot make a tool request or database readiness fail.

```text
HTTP server
└── toolwatch.execute_tool_call
    ├── toolwatch.validate_arguments
    ├── toolwatch.redact_arguments
    ├── toolwatch.classify_risk
    ├── toolwatch.evaluate_rules
    ├── execute_tool <trusted tool name>
    ├── toolwatch.validate_result
    ├── toolwatch.redact_result
    └── toolwatch.persist_terminal_result
```

Replay uses `toolwatch.replay_tool_call`. A blocked call stops before the adapter span.
Persistence is represented by coarse manual spans and duration metrics; SQL text, bind
parameters, URLs, and connection strings are not captured.

Incoming W3C Trace Context is accepted by the ASGI middleware. A canonical UUID
`X-Correlation-ID` is reused or generated and returned. Context variables add
correlation, trace, and span IDs to safe JSON lifecycle logs. Audit events persist the
request trace and correlation IDs and expose strict indexed filters.

Audit remains the authoritative, transactional security history. Traces are sampled
operational data and may be absent. A strict attribute and metric-label allowlist rejects
payloads, exception messages, rule identities/evidence, prompts, destinations, and
high-cardinality IDs. Experimental GenAI attribute names are isolated behind the
telemetry attribute module. See [ADR 0005](adr/0005-observability-v1.md).

## Dashboard and Attack Lab v1

The dashboard is a presentation adapter under `src/toolwatch/web/`. Its layering is:

```text
web/router.py        FastAPI routes mounted under DASHBOARD_PREFIX
web/dependencies.py  Jinja2 environment with autoescape and filters
web/view_models.py   immutable dataclasses passed to templates
web/presenters.py    pure transforms from query/domain values to view models
web/security.py      CSP, COOP, CORP, X-Frame-Options, Cache-Control headers
web/filters.py       safe time, duration, and tone helpers used by templates
web/templates/…      Jinja2 templates
web/static/…         locally served CSS and vendored HTMX subset
```

Routes only call `DashboardQueryService` (in `application/queries.py`) and existing
application services. Templates receive view models, never SQLAlchemy entities, and
never raw domain payloads. Sanitized JSON is rendered as pretty-printed escaped text
inside `<pre>` blocks; tool output is never rendered as HTML. Jinja autoescape is on
for every `.html` template and `|safe` is not used on tool-controlled content.

The Attack Lab lives in `src/toolwatch/attack_lab/` and contains:

```text
models.py     AttackScenario, ScenarioRequest, ExpectedOutcome, AttackRunResult
registry.py   STATIC_REGISTRY (MappingProxyType built at import time)
scenarios.py  Twelve frozen scenario definitions
runner.py    Drives the real ToolWatch pipeline through ASGI HTTP
__main__.py   `python -m toolwatch.attack_lab list|run|run-all`
```

The runner instantiates the FastAPI application via `create_app()`, talks to it
through `httpx.ASGITransport`, seeds tools and rules through the public API, applies
deterministic scenario setup (disabling a tool, swapping in a slow or failing
adapter), executes the scenario, observes persisted state through the public API
(including a fall-back lookup against `GET /api/v1/sessions/{id}/tool-calls` when an
error envelope omits `call_id`), and restores adapter state on teardown. There is no
endpoint that accepts arbitrary tools or payloads. Each adapter override is scoped
to the run and the original mapping proxy is restored before the runner returns.

Jaeger links are constructed only when `JAEGER_UI_PUBLIC_URL` is configured, the
trace ID comes from a persisted audit event, and the trace ID matches the W3C
lowercase 32-hex pattern. The OTLP endpoint and exporter credentials are never
exposed to the browser.

Dashboard read paths are documented per query in `DashboardQueryService`. Bounded
pagination, deterministic ordering, and explicit per-session call limits keep the
queries predictable on local-development data volumes. No new tables or indexes are
introduced for this milestone; the existing audit, tool-call, and session indexes
support every dashboard read.

See [ADR 0006](adr/0006-dashboard-and-attack-lab-v1.md).

## Ollama Agent Loop v1

The local agent loop adds a provider boundary without changing the execution authority:

```text
API / CLI
└── AgentRunService
    ├── FakeAgentProvider or local OllamaAgentProvider
    ├── provider tool-schema translation
    ├── bounded in-memory redacted conversation
    └── ToolCallService
        └── existing registry → validation → redaction → risk/rules → adapter pipeline
```

Only enabled registry tools are exposed. Provider names are normalized deterministically
and mapped back to one unambiguous registered name/version; collisions and duplicate
enabled versions fail before a model request. Calls execute sequentially in model order.

The application-controlled system prompt is versioned as
`toolwatch-agent-system-v1`. User and assistant content is redacted before retention;
tool messages contain sanitized ToolWatch output or fixed safe errors. Provider thinking
is discarded. Conversation history remains in memory and is bounded by per-message and
cumulative byte limits.

`agent_runs` stores lifecycle counters, safe error codes, trace/correlation IDs, and an
optional redacted final answer. `model_calls` stores turn, status, token counts, and
durations. Neither table has prompt, message, response, argument, result, or thinking
columns. `tool_calls.agent_run_id` links every mediated call. See
[ADR 0007](adr/0007-ollama-agent-loop-v1.md).

## Release hardening v0.1.0

`RecoveryService` processes stale tool calls, agent runs, and model calls in separate
short PostgreSQL transactions. Composite status/time indexes support the selection path.
Every transition is terminal, idempotent, audited, and metered.

The shutdown coordinator rejects new HTTP work, waits for in-flight request tasks up to
`SHUTDOWN_GRACE_PERIOD_SECONDS`, then cancels remaining coroutines. It closes the
reusable Ollama HTTPX client, flushes telemetry, and disposes SQLAlchemy last.
Cancellation cannot roll back an external side effect; ambiguous persisted state is
handled by the recovery command.

The release image runs as `toolwatch`, supports a read-only root filesystem with `/tmp`
tmpfs, sets OCI labels and a healthcheck, and uses `SIGTERM`. Wheel metadata takes its
version from `toolwatch.__version__`; wheel and sdist include dashboard assets.

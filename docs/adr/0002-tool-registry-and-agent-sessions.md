# ADR 0002: Tool Registry and Agent Sessions

- Status: accepted
- Date: 2026-06-22
- Milestone: Tool Registry and Agent Sessions

## Context

The repository bootstrap established a modular monolith, FastAPI, async SQLAlchemy,
PostgreSQL, and Alembic. The second milestone required the first durable business
entities and APIs while explicitly excluding tool execution, adapters, risk evaluation,
blocking rules, audit events, Ollama integration, and the dashboard.

The registry will become a security boundary for later execution. Consequently, tool
identity, enabled state, schemas, and adapter selection must be persisted as trusted
server-side data. Agent sessions must reuse a stable logical agent identity and enforce
their lifecycle without exposing persistence details to the domain.

## Decision

### Domain model

Introduce framework-independent domain entities:

- `Agent`, with logical identity `(name, provider, model_name, version)`;
- `ToolDefinition`, uniquely identified by `(name, version)`;
- `AgentSession`, with `active`, `completed`, and `failed` states.

The domain validates non-empty identity fields, namespace-like tool names, bounded
JSON-compatible data, UTC timestamps, tool schemas, secret-like adapter configuration
keys, and session transitions. It has no FastAPI or SQLAlchemy dependencies.

Tool names require at least two lowercase namespace segments separated by `.`, `_`, or
`-`. Input schemas must be JSON objects with top-level type `object`. Schema validation
is deliberately limited to the structural subset required by this milestone.

### Persistence

Create three PostgreSQL tables:

- `agents`;
- `tool_definitions`;
- `agent_sessions`.

Use PostgreSQL UUIDs, `TIMESTAMPTZ`, JSONB, named constraints, and explicit indexes.
Foreign-key deletion uses `RESTRICT`; session history must not disappear through a
cascade.

Agent identity uses a non-null `version_key = coalesce(version, '')` column. This permits
one deterministic unique constraint for both versioned and unversioned agents, avoiding
PostgreSQL's normal treatment of `NULL` values as distinct.

Tool `(name, version)` uniqueness is enforced by
`uq_tool_definitions_name_version`. Application pre-checks are not treated as a security
or consistency boundary.

Session status and `finished_at` consistency are protected by a database check
constraint in addition to domain transition rules.

### Repository and transaction boundaries

Define explicit `AgentRepository`, `ToolRepository`, and `SessionRepository` protocols
plus a small `UnitOfWork` protocol at the application boundary. No generic base
repository is introduced.

Application use cases own transactions. Repository methods may flush to observe
constraints but never commit.

Agent resolution and session creation execute in one transaction. Agent creation uses
PostgreSQL `ON CONFLICT DO NOTHING`, followed by identity lookup. Concurrent requests
therefore reuse one logical agent while still creating their individual sessions.

Tool registration relies on the named PostgreSQL unique constraint and maps the expected
integrity violation to `tool_version_already_exists`.

Session completion selects the session row `FOR UPDATE`, applies the domain transition,
and commits the terminal status atomically. Repeating the same terminal transition is
idempotent; changing one terminal state into another is rejected.

### API

Expose:

```text
POST  /api/v1/tools
GET   /api/v1/tools
GET   /api/v1/tools/{tool_id}
PATCH /api/v1/tools/{tool_id}

POST  /api/v1/sessions
GET   /api/v1/sessions
GET   /api/v1/sessions/{session_id}
POST  /api/v1/sessions/{session_id}/complete
```

Lists use bounded pagination and deterministic ordering. Tool patching changes only the
enabled state.

Public errors have stable codes and correlation IDs. Unexpected infrastructure
exceptions become a fixed `internal_error`; raw SQLAlchemy or asyncpg messages are not
rendered.

Adapter configuration is accepted as trusted registry metadata but omitted from public
read responses.

### Prompt persistence

Add `STORE_PROMPTS`, defaulting to `false`. When disabled, session prompts are converted
to `NULL` before persistence and are not logged or returned.

When explicitly enabled for development, a temporary deterministic sanitizer removes
obvious bearer tokens, JWT-like values, and common secret assignments. This sanitizer is
not considered the final redaction engine.

### Migration

Add reviewed migration `0002_tool_registry_and_sessions` after `0001_bootstrap`.
Alembic imports all persistence models explicitly, while an explicitly configured
Alembic database URL takes precedence over application settings. This allows migrations
to target disposable integration databases safely.

## Security consequences

Positive consequences:

- duplicate tool versions and logical agents are rejected by PostgreSQL under races;
- malformed, oversized, or deeply nested registry JSON is rejected before persistence;
- obvious raw secret fields are rejected from adapter configuration;
- prompts are omitted by default;
- database exceptions do not cross the public API boundary;
- adapter configuration is not exposed through read APIs;
- no registered tool can execute because execution is outside this milestone.

Known limitations:

- JSON Schema validation is a deliberate structural subset, not full specification
  validation;
- secret detection in adapter configuration is key-name based;
- development prompt sanitization is intentionally incomplete;
- the registry API is unauthenticated until a separately approved authentication
  milestone;
- registry authorization and production multi-tenancy remain out of scope.

## Verification

The implementation was verified with:

```text
make check
uv run pytest tests/integration -q
uv run alembic check
docker compose up -d --build
```

Observed results:

- Ruff lint and formatting checks passed;
- strict Pyright passed with zero errors;
- all 28 unit and integration tests passed;
- all 10 PostgreSQL integration tests passed;
- migration upgrade, downgrade to `0001_bootstrap`, and re-upgrade passed;
- Alembic reported no metadata drift;
- concurrent duplicate tool registration produced one `201` and one stable `409`;
- concurrent session creation produced one logical agent and two sessions;
- Docker Compose started a healthy API and PostgreSQL;
- liveness and readiness endpoints returned success;
- the API container ran as the non-root `toolwatch` user.

## Consequences

The trusted registry and session persistence boundaries are now available for the later
execution pipeline. Future milestones must resolve tools only from this registry and
must reject unknown or disabled tools before any adapter invocation.

The explicit repositories and unit of work add some code compared with using SQLAlchemy
models directly in routes, but preserve the modular-monolith dependency direction and
make transaction and concurrency behavior testable.

No tool execution, adapter invocation, LLM integration, risk classification, blocking
rules, audit events, telemetry spans, or dashboard behavior was introduced.

## Rejected alternatives

### SQLAlchemy models as domain entities

Rejected because it would couple business invariants and state transitions to persistence
and violate the established dependency direction.

### Repository-level commits

Rejected because agent resolution plus session creation and session completion require
application-owned atomic boundaries.

### Query-then-insert uniqueness only

Rejected because concurrent requests could pass the pre-check and create duplicates.
PostgreSQL constraints and conflict handling are the consistency authority.

### Persist all prompts after minimal sanitization

Rejected because the full redaction engine is a later milestone. Safe omission is the
default.

### Full tool execution or adapter validation

Rejected as premature and explicitly outside this milestone. Registration records
trusted metadata only; it creates no downstream capability by itself.

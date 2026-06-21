# Current Task: Tool Registry and Agent Sessions

> Implementation status: implemented on 2026-06-22. The acceptance contract remains in
> this file; verification details are recorded in the completing agent's report.

## Context

The repository bootstrap milestone is complete.

The project already includes:

* Python `src` package layout;
* FastAPI application factory;
* PostgreSQL;
* async SQLAlchemy;
* Alembic;
* Dockerfile and Docker Compose;
* health endpoints;
* unit and integration tests;
* Ruff, Pyright, pytest, and CI.

This milestone introduces the first ToolWatch domain entities and persistence flows.

Read before changing code:

1. `AGENTS.md`
2. `docs/product-spec.md`
3. `docs/architecture.md`
4. `docs/threat-model.md`
5. `docs/testing.md`
6. the current implementation and tests

Treat `AGENTS.md` and `docs/product-spec.md` as authoritative.

---

## Goal

Implement:

1. Tool Registry;
2. Agent registration or resolution;
3. Agent Session creation;
4. read APIs for tools and sessions;
5. PostgreSQL persistence;
6. Alembic migration;
7. unit and integration tests.

This milestone must create the trusted registry that later tool-call execution will depend on.

Do not implement tool execution yet.

---

## Required domain concepts

Create framework-independent domain models for:

* `Agent`;
* `ToolDefinition`;
* `AgentSession`.

Do not use SQLAlchemy models as domain entities.

Use explicit enums and value objects where useful, but avoid unnecessary abstraction.

---

## Domain model

### Agent

Fields:

```text
id
name
provider
model_name
version
metadata
created_at
```

Requirements:

* `name` must be non-empty;
* `provider` must be non-empty;
* `model_name` must be non-empty;
* `version` is optional;
* metadata must be JSON-compatible;
* timestamps must be timezone-aware UTC.

The same logical agent may be reused across multiple sessions.

Suggested identity key:

```text
name + provider + model_name + version
```

Do not expose raw database implementation details in the domain layer.

### ToolDefinition

Fields:

```text
id
name
description
version
input_schema
output_schema
base_risk_level
enabled
adapter_type
adapter_config
created_at
updated_at
```

Requirements:

* `(name, version)` must be unique;
* name must use a stable namespace-like format;
* version must be explicit;
* input schema is required;
* output schema is optional;
* base risk level must be one of:

  * low
  * medium
  * high
  * critical
* enabled defaults to `true`;
* adapter type must be explicit;
* adapter configuration must be JSON-compatible;
* agents must not register tools through the future execution endpoint.

Recommended tool-name validation:

```text
lowercase letters
digits
underscores
dots
hyphens
```

Example:

```text
github.list_issues
email.send
database.query
```

Reject whitespace and ambiguous names.

### AgentSession

Fields:

```text
id
agent_id
external_session_id
user_prompt_redacted
status
started_at
finished_at
metadata
```

Session status:

```text
active
completed
failed
```

Requirements:

* every session references an existing agent;
* `started_at` is required;
* `finished_at` is null while active;
* completing or failing a session sets `finished_at`;
* invalid status transitions must be rejected;
* prompt persistence must use a redaction boundary even though the full security redaction engine is not implemented yet.

For this milestone, implement a minimal prompt sanitizer that protects obvious secret fields or values, or persist no prompt content by default.

Prefer safe omission over unsafe storage.

---

## Architecture

Preserve the modular-monolith dependency direction:

```text
API → Application → Domain
          ↓
    Infrastructure implements ports
```

Expected packages may include:

```text
src/toolwatch/domain/agents/
src/toolwatch/domain/tools/
src/toolwatch/domain/sessions/

src/toolwatch/application/agents/
src/toolwatch/application/tools/
src/toolwatch/application/sessions/

src/toolwatch/infrastructure/database/models/
src/toolwatch/infrastructure/repositories/

src/toolwatch/api/agents.py
src/toolwatch/api/tools.py
src/toolwatch/api/sessions.py
```

Small deviations are allowed when consistent with the existing architecture.

Do not import FastAPI or SQLAlchemy into the domain layer.

---

## Repository ports

Define repository protocols in the domain or application boundary.

### Agent repository

Required operations:

```text
get_by_id
find_by_identity
create
```

### Tool repository

Required operations:

```text
get_by_id
get_by_name_and_version
list
create
set_enabled
```

### Session repository

Required operations:

```text
get_by_id
list
create
update_status
```

Do not create a generic base repository abstraction unless it clearly reduces real duplication.

---

## Database schema

Create SQLAlchemy persistence models for:

```text
agents
tool_definitions
agent_sessions
```

### Database requirements

* use PostgreSQL UUID columns where appropriate;
* use timezone-aware timestamps;
* use JSONB for metadata and schemas;
* use explicit foreign keys;
* use explicit indexes;
* add a database unique constraint for tool `(name, version)`;
* add an identity lookup index for agents;
* index session `agent_id`, `status`, and `started_at`;
* use explicit constraint names;
* avoid cascade deletion that could remove audit-relevant history later.

Do not add:

* tool calls;
* tool results;
* risk flags;
* audit events;
* users;
* tenants.

Create a new Alembic migration after `0001_bootstrap`.

Review the generated migration manually.

The migration must upgrade and downgrade cleanly on an empty PostgreSQL database.

---

## API

Use the `/api/v1` prefix.

### Register a tool

```http
POST /api/v1/tools
```

Request:

```json
{
  "name": "github.list_issues",
  "description": "List GitHub issues for a repository",
  "version": "1.0.0",
  "input_schema": {
    "type": "object",
    "properties": {
      "repository": {
        "type": "string"
      }
    },
    "required": ["repository"],
    "additionalProperties": false
  },
  "output_schema": {
    "type": "array",
    "items": {
      "type": "object"
    }
  },
  "base_risk_level": "low",
  "enabled": true,
  "adapter_type": "mock",
  "adapter_config": {
    "fixture": "github_issues"
  }
}
```

Success:

```text
201 Created
```

Duplicate `(name, version)`:

```text
409 Conflict
```

Stable error code:

```text
tool_version_already_exists
```

Invalid schemas or invalid names:

```text
422 Unprocessable Entity
```

Do not rely only on a pre-insert query for uniqueness. Handle the database unique constraint safely.

### List tools

```http
GET /api/v1/tools
```

Support query parameters:

```text
enabled
risk_level
name
limit
offset
```

Requirements:

* deterministic ordering;
* bounded limit;
* no arbitrary sorting field in this milestone;
* return pagination metadata.

Suggested response:

```json
{
  "items": [],
  "limit": 50,
  "offset": 0,
  "total": 0
}
```

### Get a tool

```http
GET /api/v1/tools/{tool_id}
```

Missing tool:

```text
404 tool_not_found
```

### Enable or disable a tool

```http
PATCH /api/v1/tools/{tool_id}
```

Request:

```json
{
  "enabled": false
}
```

Do not support arbitrary partial updates yet.

### Create a session

```http
POST /api/v1/sessions
```

Request:

```json
{
  "agent": {
    "name": "local-demo-agent",
    "provider": "ollama",
    "model_name": "qwen3:4b",
    "version": "1"
  },
  "external_session_id": "optional-client-session-id",
  "user_prompt": "Check open issues in demo/backend",
  "metadata": {
    "source": "demo"
  }
}
```

Behavior:

* find an existing agent by its identity fields;
* create the agent if it does not exist;
* create an active session;
* do not store the raw prompt if it contains an obvious secret;
* return the session and agent identity.

Success:

```text
201 Created
```

### List sessions

```http
GET /api/v1/sessions
```

Support filters:

```text
agent_id
status
limit
offset
```

Order newest first.

### Get a session

```http
GET /api/v1/sessions/{session_id}
```

Missing session:

```text
404 session_not_found
```

### Complete a session

```http
POST /api/v1/sessions/{session_id}/complete
```

Request:

```json
{
  "status": "completed"
}
```

Allowed terminal values:

```text
completed
failed
```

Reject invalid transitions with:

```text
409 invalid_session_transition
```

Repeated completion with the same terminal state may be idempotent.

A transition from one terminal state to another must be rejected.

---

## Pydantic and JSON Schema handling

Use Pydantic request and response models at the API boundary.

Tool `input_schema` and `output_schema` are JSON Schema documents.

For this milestone:

* verify the value is a JSON object;
* require input schema top-level type to be `object`;
* validate that the schema itself is structurally acceptable using a maintained JSON Schema validation library or a deliberately limited validator;
* do not execute validation against tool arguments yet;
* reject malformed schemas at registration time;
* do not mutate user-provided schemas.

If adding a JSON Schema dependency, document why it is needed.

---

## Prompt safety boundary

The full redaction engine belongs to a later milestone.

For this task, implement one safe approach:

### Preferred approach

Store `user_prompt_redacted = null` by default, controlled by:

```text
STORE_PROMPTS=false
```

When disabled:

* do not persist the prompt;
* do not log it;
* do not include it in traces.

If prompt storage is enabled in development:

* apply a minimal deterministic sanitizer;
* redact obvious bearer tokens, JWT-like values, and common secret prefixes;
* clearly document that this is temporary and not the final redaction engine.

Default must be safe.

---

## Transactions and consistency

Application use cases must own transaction boundaries.

Requirements:

* agent lookup/create and session creation must be transactionally safe;
* concurrent identical agent-session requests must not create duplicate logical agents;
* tool uniqueness must be enforced by PostgreSQL;
* do not commit inside repository methods unless the existing architecture explicitly requires it;
* map expected integrity violations to stable application errors;
* do not expose raw database exceptions.

Add at least one concurrency-oriented test for duplicate tool registration or agent identity creation.

---

## Required tests

### Domain unit tests

Cover:

* valid tool definition;
* invalid tool name;
* invalid risk level;
* session creation;
* valid terminal transition;
* invalid terminal transition;
* already-terminal transition behavior.

### Application unit tests

Use repository fakes or stubs.

Cover:

* register tool;
* duplicate tool mapping;
* create or reuse agent;
* create session;
* complete session;
* invalid transition.

### API tests

Cover:

* tool registration;
* duplicate tool conflict;
* tool listing and filters;
* tool detail;
* enable/disable;
* session creation;
* session listing;
* session detail;
* completion;
* sanitized public errors.

### PostgreSQL integration tests

Use Testcontainers.

Cover:

* migration upgrade;
* migration downgrade and upgrade;
* unique tool `(name, version)`;
* agent identity behavior;
* foreign key from session to agent;
* JSONB persistence;
* timestamps;
* pagination;
* concurrent duplicate registration.

Do not use SQLite.

### Security-related tests

At minimum:

* prompt storage disabled by default;
* raw prompt absent from database;
* raw prompt absent from logs;
* malformed JSON Schema rejected;
* SQLAlchemy exception text not returned through API;
* adapter configuration does not permit arbitrary secret material in test fixtures.

---

## Seed data

Do not automatically insert production data during migrations.

You may add a development-only seed command for these tools:

```text
github.list_issues
email.send
database.query
```

If implemented:

* it must be explicit;
* it must be idempotent;
* it must use application services;
* it must not run automatically during API startup;
* it must not implement the adapters themselves.

This is optional for the milestone.

---

## OpenAPI

Ensure generated OpenAPI includes:

* request examples;
* response models;
* stable error responses;
* filters;
* pagination schema;
* enum values.

Do not expose internal persistence fields or adapter secrets.

---

## Documentation updates

Update:

### `README.md`

Add:

* Tool Registry API overview;
* Agent Session API overview;
* example curl commands;
* migration command;
* note that execution is not implemented yet.

### `docs/architecture.md`

Document:

* domain entities;
* repository ports;
* persistence adapters;
* transaction boundaries.

### `docs/threat-model.md`

Add or refine threats:

* malicious tool registration;
* schema abuse;
* registry poisoning;
* secret leakage through adapter configuration;
* prompt persistence;
* duplicate or conflicting agent identity.

### `docs/testing.md`

Document:

* new unit and integration test groups;
* concurrency test behavior;
* PostgreSQL requirement.

Add an ADR only if a durable design choice is made that is not already covered.

---

## Makefile

Add or update commands if needed:

```text
seed
test-domain
test-api
```

Do not make the default development startup automatically seed data.

---

## Non-goals

Do not implement:

* `POST /tool-calls`;
* tool execution;
* adapter invocation;
* mock GitHub/email/database services;
* idempotency keys for tool calls;
* full redaction engine;
* risk calculation beyond storing base risk;
* blocking rules;
* audit events;
* OpenTelemetry tool spans;
* dashboard;
* Ollama provider;
* MCP;
* authentication;
* users or tenants.

---

## Acceptance criteria

The task is complete only when:

1. Agent, ToolDefinition, and AgentSession domain models exist.
2. Domain code has no FastAPI or SQLAlchemy imports.
3. PostgreSQL tables are created by a reviewed Alembic migration.
4. Migration upgrades and downgrades successfully.
5. `(tool name, version)` is enforced by a named DB constraint.
6. Duplicate tool registration returns HTTP 409 with a stable error code.
7. Tool list supports bounded pagination and documented filters.
8. Tool enable/disable works.
9. Creating a session creates or reuses the matching agent safely.
10. Session terminal transitions are enforced.
11. Prompt storage is disabled by default.
12. Raw prompts do not appear in persistence or logs by default.
13. Unit, API, integration, and concurrency tests pass.
14. PostgreSQL is used for integration tests.
15. OpenAPI accurately describes the endpoints.
16. Documentation and threat model are updated.
17. `make check` passes.
18. Docker Compose remains healthy.
19. Existing health behavior remains unchanged.
20. No tool execution or LLM integration was added.

---

## Required implementation process

Before coding:

1. inspect the current repository and latest migration;
2. read all project instructions;
3. summarize the proposed entities, tables, ports, and transaction boundaries;
4. identify any conflicts with the current architecture;
5. proceed without waiting unless genuinely blocked.

During implementation:

1. work in small coherent stages;
2. create the migration after persistence models are defined;
3. manually inspect the migration;
4. add focused tests before expanding APIs;
5. keep the domain independent;
6. do not implement future milestones.

Before completion:

1. run focused unit tests;
2. run PostgreSQL integration tests;
3. test migration upgrade and downgrade;
4. run `make check`;
5. run the Docker Compose smoke test;
6. inspect the final Git diff;
7. verify no raw prompts or credentials were added;
8. report:

   * created and modified files;
   * migration details;
   * API endpoints;
   * transaction decisions;
   * commands executed;
   * test results;
   * unverified assumptions;
   * remaining risks.

Do not claim success for checks that were not actually executed.

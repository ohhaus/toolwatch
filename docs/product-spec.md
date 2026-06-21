# ToolWatch — Agent Implementation Specification

> **Purpose:** This document is the implementation contract for coding agents working on the ToolWatch repository.  
> **Project:** Observability and runtime-safety proxy for AI-agent tool calls.  
> **Status:** MVP specification.  
> **Primary language:** Python 3.13.

---

## 1. Product definition

ToolWatch sits between an AI agent and the tools it invokes.

It must:

1. receive a tool-call request;
2. resolve the requested tool from a trusted registry;
3. validate arguments against the tool schema;
4. redact secrets before logging, tracing, or persistence;
5. classify the call risk using deterministic rules;
6. evaluate allow, flag, or block rules;
7. execute allowed calls through a trusted adapter;
8. sanitize and store the result;
9. create audit events, metrics, and OpenTelemetry spans;
10. expose sessions and tool calls through an API and a minimal dashboard.

ToolWatch is **not** an IAM platform and does not claim to prevent every prompt-injection attack.

---

## 2. Non-negotiable security invariants

These rules override convenience and feature requests.

1. **Unknown tools must never execute.**
2. **Security decisions must not depend on an LLM.**
3. **Redaction must happen before logging, tracing, persistence, and UI rendering.**
4. **Raw secrets must never be stored.**
5. **Invalid arguments must never reach a tool adapter.**
6. **Blocked calls must never reach a downstream service.**
7. **Tool outputs are untrusted input.**
8. **Arbitrary downstream URLs are forbidden in the MVP.**
9. **Public errors must not expose stack traces, credentials, SQL connection strings, internal paths, or internal hostnames.**
10. **Unit and CI tests must not require a real LLM or paid API.**
11. **Integration tests must use PostgreSQL, not SQLite.**
12. **Every security-related bug fix must include a regression test.**

---

## 3. MVP scope

### Must have

- FastAPI application;
- PostgreSQL persistence;
- Alembic migrations;
- tool registry;
- session creation;
- tool-call execution endpoint;
- Pydantic/JSON Schema validation;
- recursive secret redaction;
- deterministic risk classification;
- deterministic blocking rules;
- append-only audit events at application level;
- OpenTelemetry traces;
- structured JSON logs;
- three mock tools;
- fake agent;
- optional Ollama demo;
- minimal dashboard;
- unit, integration, property-based, and security tests;
- Docker Compose;
- GitHub Actions;
- attack-lab scenarios.

### Explicitly out of scope

Do not implement these without a separate approved task:

- OAuth authorization server;
- RBAC, ABAC, or ReBAC platform;
- multi-tenant production isolation;
- human approval workflows;
- Kubernetes;
- Kafka;
- HashiCorp Vault;
- real payment tools;
- arbitrary shell execution;
- arbitrary outbound HTTP URLs;
- ML-based anomaly detection;
- production-grade MCP gateway;
- support for every agent framework.

---

## 4. Architecture

Use a **modular monolith**.

Dependency direction:

```text
API → Application → Domain
          ↓
    Infrastructure adapters implement ports
```

### Layer rules

#### `domain`

May contain:

- entities;
- value objects;
- enums;
- state transitions;
- policy-independent business rules;
- repository and adapter protocols.

Must not import:

- FastAPI;
- SQLAlchemy;
- HTTPX;
- Ollama SDK;
- OpenTelemetry SDK;
- framework-specific settings.

#### `application`

Contains use cases and orchestration:

- create session;
- register tool;
- execute tool;
- evaluate rules;
- persist audit events;
- retrieve sessions and calls.

May depend on domain protocols. Must not contain route-specific code.

#### `infrastructure`

Contains:

- SQLAlchemy models and repositories;
- PostgreSQL session management;
- HTTP clients;
- tool adapters;
- telemetry exporters;
- configuration implementations.

#### `api`

Contains:

- FastAPI routes;
- request and response schemas;
- dependency injection;
- HTTP error mapping;
- health endpoints.

#### `security`

Contains deterministic, framework-independent components:

- redaction;
- risk classification;
- blocking-rule evaluation;
- payload limits;
- URL and host validation;
- result sanitization.

---

## 5. Repository structure

```text
toolwatch/
├── AGENTS.md
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── pyproject.toml
├── uv.lock
├── compose.yaml
├── Dockerfile
├── Makefile
├── .env.example
├── .pre-commit-config.yaml
│
├── src/toolwatch/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   │
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── health.py
│   │   ├── sessions.py
│   │   ├── tools.py
│   │   ├── tool_calls.py
│   │   └── rules.py
│   │
│   ├── domain/
│   │   ├── agents/
│   │   ├── sessions/
│   │   ├── tools/
│   │   ├── audit/
│   │   └── rules/
│   │
│   ├── application/
│   │   ├── create_session.py
│   │   ├── register_tool.py
│   │   ├── execute_tool.py
│   │   └── evaluate_rules.py
│   │
│   ├── security/
│   │   ├── redaction.py
│   │   ├── detectors.py
│   │   ├── risk_classifier.py
│   │   ├── rule_engine.py
│   │   ├── url_validator.py
│   │   └── payload_limits.py
│   │
│   ├── infrastructure/
│   │   ├── database/
│   │   ├── repositories/
│   │   ├── adapters/
│   │   └── http/
│   │
│   ├── telemetry/
│   │   ├── tracing.py
│   │   ├── metrics.py
│   │   └── logging.py
│   │
│   ├── demo/
│   │   ├── fake_agent.py
│   │   └── ollama_agent.py
│   │
│   └── web/
│       ├── routes.py
│       └── templates/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── property/
│   └── conftest.py
│
├── attack_lab/
├── docs/
│   ├── architecture.md
│   ├── threat-model.md
│   ├── testing.md
│   ├── current-task.md
│   └── adr/
│
└── .github/
    └── workflows/
        └── ci.yml
```

Do not create empty abstractions or modules unless required by the current milestone.

---

## 6. Technology choices

### Required

- Python 3.13;
- FastAPI;
- Pydantic v2;
- SQLAlchemy 2;
- Alembic;
- asyncpg;
- PostgreSQL 16 or 17;
- HTTPX;
- OpenTelemetry;
- pytest;
- pytest-asyncio;
- Testcontainers;
- Hypothesis;
- Ruff;
- Pyright;
- uv;
- Docker Compose.

### Optional after core MVP

- Jinja2 + HTMX;
- Prometheus;
- Grafana;
- Typer CLI;
- Ollama;
- MCP adapter.

Use Jaeger for the first tracing demo. Do not introduce Redis unless a concrete requirement needs it.

---

## 7. Core domain model

Use UUID or UUIDv7-compatible identifiers internally. Public IDs may use prefixes such as `ses_` and `call_`.

### Agent

```text
id
name
provider
model_name
version
metadata
created_at
```

### ToolDefinition

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

Constraints:

- `(name, version)` must be unique;
- disabled tools cannot execute;
- agents cannot register tools through the execution endpoint.

### AgentSession

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

### ToolCall

```text
id
session_id
tool_definition_id
parent_call_id
trace_id
span_id
sequence_number
redacted_arguments
arguments_hash
risk_level
decision
status
started_at
finished_at
duration_ms
error_code
error_message_redacted
idempotency_key
request_hash
```

Do not persist raw arguments in the MVP.

### ToolResult

```text
id
tool_call_id
redacted_payload
payload_hash
truncated
content_type
size_bytes
created_at
```

### RiskFlag

```text
id
tool_call_id
code
severity
message
evidence_redacted
created_at
```

### BlockingRule

```text
id
name
enabled
priority
tool_pattern
condition
action
created_at
updated_at
```

### AuditEvent

```text
id
session_id
tool_call_id
event_type
actor_type
actor_id
payload_redacted
trace_id
created_at
```

No public update or delete endpoint is allowed for audit events.

---

## 8. Tool-call state machine

Allowed statuses:

```text
received
validating
rejected
evaluating
blocked
executing
succeeded
failed
timed_out
```

Allowed terminal paths:

```text
received → validating → rejected
received → validating → evaluating → blocked
received → validating → evaluating → executing → succeeded
received → validating → evaluating → executing → failed
received → validating → evaluating → executing → timed_out
```

Reject invalid transitions in domain code.

---

## 9. Execution pipeline

Implement the pipeline in this exact order:

```text
1. Parse request
2. Enforce request-size limit
3. Resolve session
4. Resolve tool from trusted registry
5. Reject unknown or disabled tool
6. Validate arguments against input schema
7. Redact arguments
8. Compute canonical request hash
9. Resolve idempotency
10. Classify risk
11. Evaluate blocking rules
12. Persist received/validated/evaluated audit events
13. If blocked, stop
14. Execute trusted adapter with timeout
15. Validate result when output schema exists
16. Sanitize and redact result
17. Truncate oversized result
18. Persist result and final audit event
19. Record metrics and span attributes
20. Return sanitized response
```

No logging, tracing, or persistence of raw arguments may occur before step 7.

---

## 10. API contract

Prefix all business endpoints with `/api/v1`.

### `POST /api/v1/sessions`

Creates an agent session.

Request:

```json
{
  "agent": {
    "name": "local-demo-agent",
    "provider": "ollama",
    "model": "local-tool-model",
    "version": "1"
  },
  "user_prompt": "Check open issues and email a summary"
}
```

Response: `201 Created`

```json
{
  "session_id": "ses_...",
  "status": "active"
}
```

The prompt must be redacted before persistence.

### `POST /api/v1/tool-calls`

Requires:

```http
Idempotency-Key: <uuid>
```

Request:

```json
{
  "session_id": "ses_...",
  "tool": "email.send",
  "tool_version": "1.0.0",
  "arguments": {
    "recipient": "user@example.com",
    "subject": "Summary",
    "body": "There are three open issues"
  }
}
```

Success response: `200 OK`

```json
{
  "call_id": "call_...",
  "status": "succeeded",
  "decision": "allow",
  "risk": "medium",
  "flags": ["write_operation"],
  "result": {
    "message_id": "msg_...",
    "status": "sent"
  }
}
```

Blocked response: `403 Forbidden`

```json
{
  "call_id": "call_...",
  "status": "blocked",
  "decision": "block",
  "risk": "critical",
  "flags": ["destructive_sql"],
  "error": {
    "code": "tool_call_blocked",
    "message": "The call violates a runtime safety rule.",
    "correlation_id": "..."
  }
}
```

### Read endpoints

```http
GET /api/v1/sessions
GET /api/v1/sessions/{session_id}
GET /api/v1/sessions/{session_id}/tool-calls
GET /api/v1/tool-calls/{call_id}
GET /api/v1/tools
POST /api/v1/tools
GET /api/v1/rules
POST /api/v1/rules
PATCH /api/v1/rules/{rule_id}
```

### Health endpoints

```http
GET /health/live
GET /health/ready
```

`live` must not check downstream dependencies.  
`ready` must verify at least database connectivity and completed migrations.

---

## 11. Public error codes

Use stable machine-readable codes:

```text
unknown_tool
disabled_tool
invalid_arguments
payload_too_large
tool_call_blocked
idempotency_conflict
tool_timeout
tool_unavailable
invalid_tool_result
session_not_found
internal_error
```

Every public error must include a `correlation_id`.

Never return raw exception messages from infrastructure.

---

## 12. Mock tools

Implement exactly these initial adapters.

### `github.list_issues`

- read-only;
- base risk: `low`;
- validates repository as `owner/name`;
- returns deterministic fixture data.

### `email.send`

- write side effect;
- base risk: `medium`;
- validates recipient as email;
- does not send real email;
- returns deterministic message ID.

### `database.query`

- operates only on a dedicated demo database;
- `SELECT`: low;
- DML: high;
- DDL or destructive keywords: critical and blocked;
- must never accept multiple SQL statements in the MVP.

Do not connect to a developer's personal database.

---

## 13. Risk engine

Risk levels:

```text
low < medium < high < critical
```

Risk is deterministic and based on:

- tool base risk;
- operation type;
- sensitive values;
- destination;
- payload size;
- rule-based detectors.

Examples:

- read-only registered call: low;
- email or object creation: medium;
- credentials, write SQL, internal network target: high;
- shell, destructive SQL, metadata endpoint, path traversal, unknown tool: critical.

An LLM may never lower or override risk.

---

## 14. Rule engine

Supported actions:

```text
allow
flag
block
```

Precedence:

```text
block > flag > allow
```

Higher numeric priority evaluates first. Any matching block rule terminates evaluation.

Initial rule format:

```yaml
rules:
  - name: block-destructive-sql
    enabled: true
    priority: 100
    match:
      tool: "database.query"
      argument:
        path: "query"
        regex: "(?i)\\b(drop|truncate|alter)\\b"
    action: block
```

Rules must be validated at startup. Invalid rules must fail startup in development and be rejected through the API.

Do not build a general-purpose policy language in the MVP.

---

## 15. Secret redaction

Redact recursively in dictionaries and lists.

Sensitive field-name matching must be case-insensitive and include:

```text
password
passwd
secret
token
api_key
authorization
cookie
private_key
client_secret
```

Detect at least:

- Bearer tokens;
- JWT-like values;
- private-key headers;
- credentials embedded in URLs;
- configured sensitive JSON paths.

Replacement:

```text
[REDACTED]
```

Requirements:

- idempotent;
- bounded recursion depth;
- no raw secret in logs, traces, DB, UI, or errors;
- input and output redaction;
- optional salted SHA-256 fingerprint;
- fingerprints must not be reversible.

---

## 16. Payload and timeout limits

Default settings:

```text
MAX_REQUEST_BODY_BYTES=262144
MAX_TOOL_ARGUMENTS_BYTES=65536
MAX_TOOL_RESULT_BYTES=524288
MAX_STRING_LENGTH=51200
MAX_JSON_DEPTH=20
DEFAULT_TOOL_TIMEOUT_SECONDS=10
```

Oversized requests are rejected before execution.  
Oversized results are truncated, marked with `truncated=true`, and never stored in full.

---

## 17. Network safety

For the MVP, all downstream adapters must be preconfigured. Agents cannot supply arbitrary target URLs.

If an HTTP adapter is introduced:

- allow only HTTP and HTTPS;
- enforce hostname allowlist;
- reject loopback, private, link-local, multicast, and metadata IPs;
- validate resolved IP before connection;
- restrict redirects;
- apply response-size and timeout limits;
- strip internal authentication headers;
- do not forward caller headers by default.

---

## 18. Idempotency

`POST /tool-calls` requires an idempotency key.

Behavior:

- same key + same canonical request hash → return previous terminal result;
- same key + different request hash → `409 idempotency_conflict`;
- concurrent same-key requests → execute downstream at most once;
- failed validation may be safely repeated;
- terminal blocked results are idempotent.

Enforce with a unique database constraint and transaction-safe implementation.

---

## 19. Audit events

Required event types:

```text
session.started
session.completed
tool_call.received
tool_call.validated
tool_call.flagged
tool_call.blocked
tool_call.started
tool_call.completed
tool_call.failed
tool_call.timed_out
```

Every event includes:

- timestamp;
- session ID;
- tool-call ID when applicable;
- event type;
- actor;
- sanitized payload;
- trace ID.

Audit events are append-only through application interfaces.

---

## 20. Observability

### Tracing

Create one root span per agent session where possible.

Suggested hierarchy:

```text
agent.session
├── agent.model_call
├── tool.call github.list_issues
├── agent.model_call
└── tool.call email.send
```

Required low-risk attributes:

```text
agent.name
agent.provider
agent.model
tool.name
tool.version
tool.risk_level
tool.decision
tool.status
```

Do not attach full prompts, arguments, results, secrets, arbitrary URLs, or PII by default.

### Metrics

Implement:

```text
agent_sessions_total
tool_calls_total
tool_calls_blocked_total
tool_calls_failed_total
tool_call_duration_seconds
risk_flags_total
redactions_total
validation_failures_total
tool_timeouts_total
```

Allowed labels:

```text
tool_name
status
risk_level
decision
error_code
```

Never use IDs, URLs, or free-form messages as labels.

### Logging

Use structured JSON logs with:

```text
timestamp
level
message
service
environment
correlation_id
trace_id
session_id
tool_call_id
```

Pass all structured metadata through redaction before emitting.

---

## 21. Local LLM integration

LLM integration is demo-only and must be isolated behind:

```python
class AgentProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> AgentResponse: ...
```

Implementations:

- `FakeAgentProvider`: deterministic, used by tests and CI;
- `OllamaAgentProvider`: optional, used for local demo.

Rules:

- CI must not download or run a model;
- tests must not assert exact free-form LLM text;
- local-LLM tests use `pytest -m local_llm`;
- model output is untrusted and enters the same validation pipeline;
- Ollama must not be required to start the core API.

---

## 22. Local development topology

Recommended macOS development mode:

```text
FastAPI       → local macOS process
Ollama        → local macOS process
PostgreSQL    → Docker
Jaeger        → Docker
Mock tools    → Docker or in-process adapters
```

Required commands:

```bash
uv sync
make infra-up
uv run alembic upgrade head
make run
make test
make check
```

The full application must also run through:

```bash
docker compose up --build
```

---

## 23. Testing requirements

### Unit tests

Must not require Docker or LLM.

Cover:

- state transitions;
- schema validation;
- redaction;
- risk classification;
- rule precedence;
- payload limits;
- result truncation;
- sanitized error mapping;
- request canonicalization;
- hashing.

### Property-based tests

Required properties:

- redaction is idempotent;
- original secrets do not appear in serialized redacted output;
- unknown tools never execute;
- invalid arguments never call adapters;
- a block decision cannot be weakened by lower-priority allow rules;
- oversized input never reaches adapters;
- changing a request while reusing an idempotency key creates conflict.

### Integration tests

Use Testcontainers with real PostgreSQL.

Cover:

- Alembic migrations from empty database;
- session persistence;
- tool registration;
- successful tool execution;
- blocked tool execution;
- adapter timeout;
- adapter error;
- output redaction;
- idempotent duplicate request;
- concurrent duplicate request;
- audit-event persistence;
- trace propagation.

### Security regression tests

At minimum:

1. Bearer token in input;
2. nested API key;
3. secret in result;
4. destructive SQL;
5. multiple SQL statements;
6. shell metacharacters;
7. path traversal;
8. loopback URL;
9. metadata endpoint;
10. oversized JSON;
11. excessive JSON depth;
12. malicious tool output;
13. unknown tool;
14. disabled tool;
15. public error sanitization.

### Coverage

Target at least 70% for `domain` and `security`. Do not optimize for repository-wide coverage at the expense of meaningful tests.

---

## 24. Attack lab

Create reproducible scenarios:

```text
attack_lab/
├── secret_in_arguments.json
├── secret_in_tool_result.json
├── destructive_sql.json
├── ssrf_attempt.json
├── path_traversal.json
├── prompt_injection_output.json
└── oversized_payload.json
```

Each scenario defines:

```text
name
tool
arguments
expected_decision
expected_risk
expected_flags
expected_downstream_called
```

Attack scenarios must run without Ollama.

---

## 25. Minimal dashboard

Use server-rendered HTML, Jinja2, and optional HTMX.

Required pages:

- sessions list;
- session timeline;
- tool-call detail;
- rules list, read-only initially.

The UI must display only sanitized content.

Do not introduce React or Next.js for the MVP.

---

## 26. Required CI checks

CI must run:

```bash
uv sync --frozen
ruff check .
ruff format --check .
pyright
pytest -m "not local_llm"
```

CI must not require:

- Ollama;
- paid APIs;
- Docker Compose;
- cloud credentials.

Integration tests may use Testcontainers when the runner supports Docker.

---

## 27. Definition of Done

The MVP is complete only when all conditions hold:

- repository setup works from documented commands;
- migrations apply to an empty PostgreSQL database;
- fake agent executes three tool calls;
- one safe call succeeds;
- invalid arguments are rejected;
- unknown tool is rejected;
- destructive SQL is blocked before adapter execution;
- secrets are redacted in arguments and results;
- redacted values do not appear in logs, traces, DB, or UI;
- idempotent retries do not duplicate side effects;
- all calls appear in the dashboard;
- Jaeger shows tool-call traces;
- attack-lab scenarios pass;
- CI passes;
- domain/security coverage target is met;
- README contains architecture and demo instructions;
- threat model is updated;
- Ollama demo works when enabled but remains optional;
- no paid AI API is required.

---

## 28. Implementation milestones

Work in order. Do not start later milestones before the prior milestone passes its acceptance criteria.

### Milestone 1 — Repository skeleton

Deliver:

- package structure;
- FastAPI app;
- configuration;
- PostgreSQL;
- Alembic;
- health endpoints;
- Docker Compose;
- CI;
- lint and type-check configuration.

Acceptance:

- `/health/live` returns 200;
- `/health/ready` reflects DB state;
- migration applies;
- `make check` passes.

### Milestone 2 — Tool registry and sessions

Deliver:

- domain entities;
- repositories;
- tool registration;
- session creation;
- read endpoints.

Acceptance:

- duplicate tool version rejected;
- disabled state persisted;
- prompt redacted before storage;
- integration tests pass.

### Milestone 3 — Execution pipeline

Deliver:

- trusted adapter protocol;
- three mock tools;
- argument validation;
- timeout;
- result validation;
- public error mapping.

Acceptance:

- safe tool executes;
- invalid arguments do not execute;
- timeout produces stable error;
- output schema failure is handled.

### Milestone 4 — Security controls

Deliver:

- recursive redaction;
- risk engine;
- rule engine;
- payload limits;
- destructive SQL blocker;
- URL validator.

Acceptance:

- security test suite passes;
- no raw test secrets appear in persisted or emitted artifacts;
- blocked adapters are not called.

### Milestone 5 — Audit and observability

Deliver:

- audit events;
- structured logging;
- OpenTelemetry traces;
- core metrics.

Acceptance:

- one complete session is visible in Jaeger;
- required audit events exist;
- metric labels remain low-cardinality.

### Milestone 6 — Dashboard and attack lab

Deliver:

- sessions list;
- timeline;
- call detail;
- reproducible attack scenarios.

Acceptance:

- dashboard renders sanitized data;
- all attack scenarios pass without LLM.

### Milestone 7 — Local LLM demo

Deliver:

- provider protocol;
- fake provider;
- Ollama provider;
- demo prompt and instructions.

Acceptance:

- fake provider remains default;
- core tests run without Ollama;
- local model can produce at least one valid tool call.

### Milestone 8 — Hardening and release

Deliver:

- property tests;
- concurrency idempotency test;
- load-test script;
- architecture documentation;
- threat model;
- demo recording;
- release notes.

Acceptance:

- Definition of Done is satisfied.

---

## 29. Agent workflow for every task

Before changing code:

1. read `AGENTS.md`;
2. read `docs/current-task.md`;
3. inspect relevant modules and tests;
4. identify security invariants affected;
5. avoid unrelated refactors.

While implementing:

1. make the smallest coherent change;
2. preserve layer boundaries;
3. add or update tests first for security bugs;
4. never weaken validation to make tests pass;
5. do not add dependencies without explaining the need.

Before completing:

1. run focused tests;
2. run `make check`;
3. update API docs and examples when behavior changes;
4. update threat model for new attack surfaces;
5. add an ADR for durable architecture decisions;
6. summarize changed files, tests run, and remaining risks.

---

## 30. Prohibited agent behavior

The coding agent must not:

- bypass or delete failing tests without justification;
- replace PostgreSQL integration tests with SQLite;
- log raw payloads for debugging;
- add real credentials to fixtures;
- call a real email, GitHub, database, or payment service;
- introduce shell execution;
- use an LLM as an authorization or blocking judge;
- silently change API contracts;
- add large frameworks for minor features;
- implement future-roadmap items during MVP tasks;
- claim production readiness;
- weaken security defaults for convenience.

---

## 31. Future roadmap

Only after MVP completion:

```text
0.2 → MCP transport and tool discovery
0.3 → safe dry-run replay and rule simulation
0.4 → API authentication and project isolation
0.5 → human approval for high-risk actions
1.0 → stable SDK, plugin system, deployment packaging
```

Do not pre-build these features unless the current task explicitly requests them.

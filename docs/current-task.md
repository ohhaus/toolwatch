# Current Task: Tool Call Execution Pipeline v1

> Implementation status: implemented on 2026-06-22. The acceptance contract remains in
> this file; verification details are reported by the completing agent.

## Context

The repository currently provides:

* FastAPI application;
* PostgreSQL and Alembic;
* modular-monolith architecture;
* Tool Registry;
* Agent and Agent Session lifecycle;
* repository ports and Unit of Work;
* Docker Compose and CI;
* unit and PostgreSQL integration tests.

This milestone introduces the first executable ToolWatch flow.

The system must accept a tool-call request, validate it against a trusted registered tool, execute a trusted mock adapter, and persist the execution lifecycle.

Read before changing code:

1. `AGENTS.md`
2. `docs/product-spec.md`
3. `docs/architecture.md`
4. `docs/threat-model.md`
5. `docs/testing.md`
6. existing domain, application, repository, API, and migration code

Treat `AGENTS.md` and `docs/product-spec.md` as authoritative.

---

## Goal

Implement the first complete tool-call execution flow:

```text
HTTP request
    ↓
Resolve session
    ↓
Resolve registered tool and version
    ↓
Validate arguments against JSON Schema
    ↓
Resolve trusted adapter
    ↓
Create ToolCall record
    ↓
Execute adapter with timeout
    ↓
Validate adapter result
    ↓
Persist terminal status and safe metadata
    ↓
Return result
```

This milestone must support three deterministic mock tools:

* `github.list_issues`;
* `email.send`;
* `database.query`.

Do not implement Ollama integration yet.

---

## Critical security boundary

The full redaction engine is not implemented yet.

Therefore:

* do not persist raw tool arguments;
* do not persist raw tool results;
* do not log raw arguments or results;
* do not attach raw arguments or results to traces;
* do not include arguments or results in exception messages;
* persist only canonical hashes and safe metadata;
* return the result to the direct caller only after output validation;
* tests must verify absence of raw payloads from persistence and logs.

Argument and result persistence will be introduced only after the redaction milestone.

---

## Required domain concepts

Add framework-independent domain models for:

* `ToolCall`;
* `ToolResultMetadata`;
* `ToolCallStatus`;
* `ToolCallDecision`;
* adapter execution result;
* stable execution errors.

Do not use SQLAlchemy models as domain entities.

---

## ToolCall domain model

Fields:

```text
id
session_id
tool_definition_id
parent_call_id
sequence_number
arguments_hash
request_hash
idempotency_key
status
decision
started_at
finished_at
duration_ms
error_code
error_message_safe
created_at
updated_at
```

### Status values

```text
received
validating
rejected
executing
succeeded
failed
timed_out
```

### Decision values

```text
allow
reject
```

Blocking policies are not implemented yet.

### Allowed transitions

```text
received → validating → rejected
received → validating → executing → succeeded
received → validating → executing → failed
received → validating → executing → timed_out
```

Invalid transitions must raise a domain error.

Terminal states:

```text
rejected
succeeded
failed
timed_out
```

A terminal ToolCall cannot transition again.

---

## ToolResultMetadata domain model

Persist only:

```text
id
tool_call_id
payload_hash
content_type
size_bytes
schema_valid
created_at
```

Do not persist the result body in this milestone.

---

## API

### Execute tool call

```http
POST /api/v1/tool-calls
```

Required header:

```http
Idempotency-Key: <UUID>
```

Request:

```json
{
  "session_id": "ses_...",
  "tool": "github.list_issues",
  "tool_version": "1.0.0",
  "arguments": {
    "repository": "demo/backend",
    "state": "open"
  }
}
```

Successful response:

```text
200 OK
```

```json
{
  "call_id": "call_...",
  "status": "succeeded",
  "decision": "allow",
  "tool": "github.list_issues",
  "tool_version": "1.0.0",
  "duration_ms": 12,
  "result": {
    "issues": [
      {
        "number": 1,
        "title": "Example issue",
        "state": "open"
      }
    ]
  }
}
```

Invalid arguments:

```text
422 Unprocessable Entity
```

```json
{
  "error": {
    "code": "invalid_tool_arguments",
    "message": "Tool arguments do not match the registered schema.",
    "correlation_id": "..."
  }
}
```

Unknown tool:

```text
404 Not Found
```

Error code:

```text
tool_not_found
```

Disabled tool:

```text
409 Conflict
```

Error code:

```text
tool_disabled
```

Inactive or missing session:

```text
404 session_not_found
409 session_not_active
```

Timeout:

```text
504 Gateway Timeout
```

Error code:

```text
tool_timeout
```

Adapter failure:

```text
502 Bad Gateway
```

Error code:

```text
tool_execution_failed
```

Invalid adapter result:

```text
502 Bad Gateway
```

Error code:

```text
invalid_tool_result
```

Idempotency conflict:

```text
409 Conflict
```

Error code:

```text
idempotency_conflict
```

---

## Read APIs

Implement:

```http
GET /api/v1/tool-calls/{call_id}
GET /api/v1/sessions/{session_id}/tool-calls
```

The responses must not contain raw arguments or raw results.

Example detail:

```json
{
  "id": "call_...",
  "session_id": "ses_...",
  "tool": "github.list_issues",
  "tool_version": "1.0.0",
  "sequence_number": 1,
  "status": "succeeded",
  "decision": "allow",
  "duration_ms": 12,
  "error": null,
  "started_at": "...",
  "finished_at": "..."
}
```

Session call list requirements:

* order by `sequence_number`;
* bounded pagination;
* optional status filter;
* deterministic ordering.

---

## Argument validation

Replace or extend the current limited schema validator so registered schemas can validate actual arguments.

Use a maintained JSON Schema implementation.

Required behavior:

1. validate the registered schema itself during tool registration;
2. compile or construct the validator before execution;
3. validate arguments before adapter invocation;
4. collect deterministic validation errors;
5. return only safe field paths and generic messages;
6. do not expose Python exception details;
7. do not modify input arguments.

Use JSON Schema Draft 2020-12 unless the existing codebase has already committed to another explicit draft.

### Supported subset

For the MVP execution path, support at least:

```text
type
properties
required
additionalProperties
items
enum
const
minLength
maxLength
minimum
maximum
pattern
format
```

### Restrictions

Reject or explicitly disable unsupported dangerous or overly complex features, including:

```text
remote $ref
dynamicRef
recursive external schema loading
custom executable format callbacks
```

Local schema references may remain unsupported in this milestone.

Document the supported subset.

### Format validation

Support at least:

```text
email
uri
uuid
date-time
```

Format validation must be explicit and tested.

---

## Canonicalization and hashing

Create one deterministic canonical JSON serializer.

Requirements:

* stable key ordering;
* UTF-8;
* compact separators;
* reject unsupported non-JSON values;
* preserve array ordering;
* distinguish numeric and string values correctly.

Compute:

```text
arguments_hash = SHA-256(canonical arguments)
request_hash = SHA-256(
    session_id
    + tool name
    + tool version
    + canonical arguments
)
```

Do not use Python's built-in `hash()`.

Raw arguments must not be persisted alongside the hash.

---

## Idempotency

Execution endpoints may produce side effects, so idempotency is required now.

Behavior:

### Same key and same request

```text
same Idempotency-Key
same request_hash
```

Return the previous terminal response without executing the adapter again.

### Same key and different request

Return:

```text
409 idempotency_conflict
```

### Concurrent same request

Two concurrent requests with the same key and hash must execute the adapter at most once.

### In-progress duplicate

Choose and document one behavior:

* wait briefly for the original execution and return its terminal result; or
* return `409 execution_in_progress`.

Prefer the simpler deterministic implementation.

### Database enforcement

Add a named unique constraint for the idempotency key.

Do not rely only on an application-level pre-check.

---

## Adapter architecture

Define a framework-independent adapter protocol.

Suggested contract:

```python
class ToolAdapter(Protocol):
    async def execute(
        self,
        *,
        arguments: Mapping[str, JSONValue],
        context: ToolExecutionContext,
    ) -> JSONValue:
        ...
```

Create a trusted adapter registry.

Requirements:

* adapters are registered explicitly in application startup or composition root;
* adapter type comes from the trusted ToolDefinition;
* no dynamic import paths from database values;
* no `eval`;
* no arbitrary module loading;
* unknown adapter types fail safely;
* agents cannot select an adapter independently of the registered tool;
* adapter registry is immutable after startup where practical.

Stable error:

```text
adapter_not_configured
```

---

## Mock adapters

### 1. `github.list_issues`

Adapter type:

```text
mock_github
```

Arguments:

```json
{
  "repository": "demo/backend",
  "state": "open"
}
```

Rules:

* repository must match `owner/name`;
* state is `open` or `closed`;
* returns deterministic fixture data;
* no real GitHub request;
* no network access.

Suggested result:

```json
{
  "issues": [
    {
      "number": 1,
      "title": "Add health endpoint",
      "state": "open"
    },
    {
      "number": 2,
      "title": "Improve test coverage",
      "state": "open"
    }
  ]
}
```

### 2. `email.send`

Adapter type:

```text
mock_email
```

Arguments:

```json
{
  "recipient": "user@example.com",
  "subject": "Summary",
  "body": "There are two open issues."
}
```

Rules:

* validate recipient format through schema;
* do not send real email;
* return a deterministic or safely generated message ID;
* increment a test-visible execution counter;
* support idempotency tests proving one side effect.

Suggested result:

```json
{
  "message_id": "msg_...",
  "status": "accepted"
}
```

### 3. `database.query`

Adapter type:

```text
mock_database
```

Arguments:

```json
{
  "query": "SELECT id, name FROM projects"
}
```

For this milestone:

* do not execute SQL;
* accept only a small allowlisted set of exact demo queries;
* reject any unknown query;
* do not create a SQL parser;
* do not connect to the ToolWatch database;
* return deterministic fixture rows.

Example allowlisted query:

```text
SELECT id, name FROM projects
```

Unknown query error:

```text
mock_query_not_supported
```

Destructive SQL blocking belongs to the later security milestone.

However, mock execution must never run destructive SQL.

---

## Timeouts

Add configuration:

```text
DEFAULT_TOOL_TIMEOUT_SECONDS=10
```

Allow an optional safe per-tool timeout in trusted adapter configuration:

```json
{
  "timeout_seconds": 3
}
```

Requirements:

* enforce an upper application limit;
* timeout the adapter coroutine;
* transition ToolCall to `timed_out`;
* return stable `tool_timeout`;
* do not leave the database transaction open during long adapter execution;
* do not retry automatically in this milestone.

---

## Transaction boundaries

Do not hold a PostgreSQL transaction open while awaiting tool execution.

Required high-level flow:

### Transaction 1

* resolve session;
* resolve tool;
* validate prerequisites;
* create ToolCall as `received`;
* commit.

### Application execution

* move to `validating`;
* validate arguments;
* if invalid, persist `rejected`;
* otherwise move to `executing`;
* execute adapter outside a DB transaction.

### Transaction 2

* persist result metadata;
* transition to terminal state;
* commit.

Document crash-consistency limitations.

Examples:

* process crashes after adapter side effect but before terminal persistence;
* timeout occurs while adapter cancellation is not respected.

Do not solve distributed transactions in this milestone.

Idempotency must reduce duplicate execution risk.

---

## Database schema

Create tables:

```text
tool_calls
tool_result_metadata
```

### `tool_calls`

Required constraints and indexes:

* primary key;
* foreign key to `agent_sessions`;
* foreign key to `tool_definitions`;
* optional self-reference for `parent_call_id`;
* unique named constraint on `idempotency_key`;
* unique named constraint on `(session_id, sequence_number)`;
* indexes on:

  * session ID;
  * status;
  * created time;
  * tool definition ID;
* timezone-aware timestamps;
* bounded error-code and safe-message columns.

### `tool_result_metadata`

Requirements:

* one-to-one with ToolCall;
* unique foreign key;
* payload hash;
* size;
* content type;
* schema validity;
* created time.

Do not create argument or result JSONB columns yet.

Create a reviewed Alembic migration after `0002`.

Migration must upgrade and downgrade cleanly.

---

## Sequence numbers

Every ToolCall inside a session receives a monotonically increasing sequence number starting at 1.

Concurrent calls must not receive the same number.

Use a PostgreSQL-safe implementation.

Do not calculate solely using:

```text
SELECT MAX(sequence_number) + 1
```

without appropriate locking or constraint-retry handling.

Document the chosen approach.

---

## Output validation

When `output_schema` exists:

* validate adapter output before returning it;
* if invalid, do not return the invalid payload;
* persist terminal `failed`;
* use `invalid_tool_result`;
* store only payload hash and safe metadata;
* do not expose detailed adapter output in the error.

When no output schema exists:

* require output to remain JSON-compatible;
* enforce result-size limits;
* document that schema validation was skipped.

---

## Payload limits

Use or add settings:

```text
MAX_TOOL_ARGUMENTS_BYTES=65536
MAX_TOOL_RESULT_BYTES=524288
MAX_JSON_DEPTH=20
MAX_STRING_LENGTH=51200
```

Requirements:

* measure canonical serialized size;
* reject oversized arguments before execution;
* reject excessive depth;
* reject strings over the configured maximum;
* reject non-JSON-compatible values;
* do not truncate arguments;
* do not return oversized results;
* mark execution failed with `tool_result_too_large`.

Stable codes:

```text
tool_arguments_too_large
tool_result_too_large
tool_payload_too_deep
```

---

## Public error safety

Map expected application errors to stable API responses.

Required codes:

```text
session_not_found
session_not_active
tool_not_found
tool_disabled
invalid_tool_arguments
adapter_not_configured
tool_execution_failed
tool_timeout
invalid_tool_result
tool_arguments_too_large
tool_result_too_large
tool_payload_too_deep
idempotency_conflict
execution_in_progress
```

Do not return:

* raw validation exception;
* adapter exception text;
* SQLAlchemy exception text;
* stack trace;
* raw arguments;
* raw results;
* adapter configuration.

Every public error includes:

```text
code
message
correlation_id
```

---

## Logging

Add structured lifecycle logs using IDs only:

```text
tool_call_received
tool_call_rejected
tool_call_started
tool_call_succeeded
tool_call_failed
tool_call_timed_out
```

Allowed structured fields:

```text
call_id
session_id
tool_name
tool_version
status
duration_ms
error_code
correlation_id
```

Forbidden fields:

```text
arguments
result
raw exception
adapter_config
user_prompt
```

Tests must verify raw payloads do not appear in captured logs.

---

## Metrics and tracing

Do not implement full OpenTelemetry tool semantics in this milestone unless the existing architecture makes it trivial.

Minimal optional instrumentation:

```text
tool_calls_total
tool_call_duration_seconds
```

Allowed low-cardinality labels:

```text
tool_name
status
```

Do not add session IDs, call IDs, repository names, or error messages as metric labels.

Full observability belongs to a later milestone.

---

## Seed command

Add or complete an explicit idempotent development seed command for:

```text
github.list_issues
email.send
database.query
```

Requirements:

* use application services;
* do not run on API startup;
* safe to execute repeatedly;
* create or reuse tool versions;
* schemas must match mock adapter contracts;
* adapter types must match the trusted adapter registry.

Suggested command:

```bash
make seed
```

---

## Required tests

### Domain unit tests

Cover:

* valid state transitions;
* invalid state transitions;
* terminal-state protection;
* deterministic hashes;
* canonical JSON behavior;
* decision and status enums.

### Schema-validation tests

Cover:

* valid arguments;
* missing required field;
* additional property rejection;
* invalid format;
* invalid enum;
* nested object;
* excessive depth;
* oversized string;
* unsupported schema feature.

### Adapter unit tests

Cover each mock adapter:

* deterministic success;
* invalid or unsupported input;
* no network access;
* timeout simulation;
* output JSON compatibility.

### Application tests

Cover:

* successful execution;
* inactive session;
* unknown tool;
* disabled tool;
* invalid arguments;
* missing adapter;
* adapter failure;
* timeout;
* invalid result;
* oversized arguments;
* oversized result;
* idempotent retry;
* idempotency conflict.

### API tests

Cover:

* correct HTTP status codes;
* stable error codes;
* successful result response;
* call detail without payload;
* session call listing;
* pagination;
* sanitized errors.

### PostgreSQL integration tests

Use Testcontainers.

Cover:

* migration upgrade;
* migration downgrade and upgrade;
* foreign keys;
* unique idempotency constraint;
* unique sequence constraint;
* one-to-one result metadata;
* concurrent same-key execution;
* concurrent session sequence allocation;
* terminal persistence.

### Security regression tests

At minimum:

1. raw argument secret absent from DB;
2. raw argument secret absent from logs;
3. raw result secret absent from DB;
4. raw result secret absent from logs;
5. adapter configuration absent from public API;
6. invalid arguments do not invoke adapter;
7. disabled tool does not invoke adapter;
8. duplicate idempotent request invokes adapter once;
9. adapter exception text is sanitized;
10. output-schema failure does not return invalid output.

---

## Fake execution counters

For deterministic side-effect testing, mock adapters may expose test-only counters through injected test doubles.

Do not expose execution counters through production HTTP endpoints.

Do not use global mutable counters in production composition.

---

## OpenAPI

Document:

* `Idempotency-Key` header;
* request schema;
* successful response;
* all stable errors;
* timeout response;
* pagination;
* result as JSON-compatible value.

Do not expose persistence-only fields.

---

## Documentation updates

### `README.md`

Add:

* execution pipeline overview;
* seed command;
* curl example for each mock tool;
* idempotency example;
* explicit warning that content is not persisted until redaction exists;
* note that Ollama is not connected yet.

### `docs/architecture.md`

Document:

* adapter protocol and registry;
* execution flow;
* transaction boundaries;
* idempotency;
* sequence-number allocation;
* crash-consistency limitations.

### `docs/threat-model.md`

Add or refine:

* arbitrary adapter loading;
* invalid argument execution;
* duplicate side effects;
* timeout and cancellation;
* malicious adapter output;
* schema complexity abuse;
* payload exhaustion;
* raw payload leakage;
* process crash between side effect and persistence.

### `docs/testing.md`

Document:

* adapter tests;
* idempotency/concurrency tests;
* schema validation tests;
* payload non-persistence tests.

Add ADRs for durable choices such as:

```text
trusted static adapter registry
no payload persistence before redaction
execution outside DB transaction
```

---

## Non-goals

Do not implement:

* full secret redaction;
* risk classification;
* allow/flag/block policies;
* audit-event table;
* complete OpenTelemetry GenAI spans;
* dashboard;
* Ollama provider;
* agent loop;
* MCP;
* authentication;
* real GitHub;
* real email;
* real SQL execution;
* arbitrary HTTP adapters;
* retries;
* background queues.

---

## Acceptance criteria

The milestone is complete only when:

1. ToolCall and ToolResultMetadata domain models exist.
2. Domain code remains framework-independent.
3. `POST /api/v1/tool-calls` works for trusted mock adapters.
4. Arguments are validated against the registered schema.
5. Adapter output is validated when output schema exists.
6. Unknown and disabled tools never execute.
7. Inactive sessions cannot execute tools.
8. Adapters are resolved only from a static trusted registry.
9. No dynamic imports or arbitrary adapter paths exist.
10. Raw arguments are not persisted.
11. Raw results are not persisted.
12. Raw arguments and results do not appear in logs.
13. Idempotent duplicate requests execute the adapter once.
14. Conflicting idempotency reuse returns HTTP 409.
15. Timeouts produce a terminal timed-out call.
16. Invalid adapter outputs are not returned.
17. Payload limits are enforced.
18. Sequence numbers remain unique under concurrency.
19. Migration upgrades and downgrades successfully.
20. Unit, API, integration, concurrency, and security tests pass.
21. `make check` passes.
22. Docker Compose remains healthy.
23. Existing registry, session, and health behavior remains unchanged.
24. Documentation and threat model are updated.
25. Ollama and real external tools are not integrated.

---

## Required implementation process

Before coding:

1. inspect the repository, migrations, UoW, and existing error handling;
2. summarize the proposed execution pipeline;
3. describe transaction boundaries;
4. describe idempotency behavior;
5. describe adapter registration;
6. identify security-sensitive storage and logging paths;
7. proceed without waiting unless genuinely blocked.

During implementation:

1. work in small coherent stages;
2. create domain state transitions first;
3. implement canonicalization and schema validation;
4. implement adapter protocol and mocks;
5. add persistence and migration;
6. implement application orchestration;
7. implement API last;
8. add tests at each stage;
9. never persist payloads for debugging;
10. do not implement future milestones.

Before completion:

1. run focused tests;
2. run PostgreSQL integration and concurrency tests;
3. test migration upgrade/downgrade/upgrade;
4. run `alembic check`;
5. run `make check`;
6. run Docker Compose smoke tests;
7. inspect logs for test secrets;
8. inspect database rows for payload leakage;
9. inspect Git diff;
10. report:

* created and modified files;
* migration details;
* execution pipeline;
* adapter design;
* transaction and idempotency decisions;
* commands executed;
* test results;
* checks not run;
* remaining risks.

Do not claim a check passed unless it was actually executed.

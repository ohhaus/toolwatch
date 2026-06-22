# Current Task: Security Pipeline v1

> Implementation status: implemented on 2026-06-22. This file remains the acceptance
> contract; verification details are reported by the completing agent.

## Context

The repository currently provides:

* Tool Registry;
* Agent Sessions;
* Tool Call execution pipeline;
* trusted immutable mock-adapter registry;
* JSON Schema validation;
* canonical JSON and SHA-256 hashing;
* idempotency;
* PostgreSQL-safe sequence allocation;
* payload-free ToolCall persistence;
* safe lifecycle logging;
* unit, API, integration, concurrency, and security tests.

The current execution pipeline intentionally does not persist raw arguments or results because the redaction layer does not yet exist.

This milestone introduces:

1. recursive deterministic redaction;
2. sanitized argument and result persistence;
3. risk classification;
4. risk flags;
5. runtime blocking rules;
6. append-only audit events;
7. persistent terminal-response replay.

Read before changing code:

1. `AGENTS.md`
2. `docs/product-spec.md`
3. `docs/architecture.md`
4. `docs/threat-model.md`
5. `docs/testing.md`
6. all existing domain, application, security, persistence, API, and migration code
7. ADR 0003

Treat `AGENTS.md` and `docs/product-spec.md` as authoritative.

---

## Goal

Extend the execution pipeline to:

```text
Receive tool call
    ↓
Resolve session and trusted tool
    ↓
Validate arguments
    ↓
Redact arguments
    ↓
Classify risk
    ↓
Evaluate blocking rules
    ↓
BLOCK or EXECUTE
    ↓
Redact and validate result
    ↓
Persist sanitized payloads
    ↓
Persist risk flags and audit events
    ↓
Return sanitized result
```

After this milestone, ToolWatch must be able to demonstrate:

* a normal read operation succeeding;
* an email operation being flagged;
* a destructive SQL request being blocked;
* a secret being removed before persistence;
* an indirect prompt-injection string in tool output being flagged;
* an idempotent successful response being replayed after application restart.

---

## Non-negotiable security invariants

1. Raw arguments must never be persisted.
2. Raw results must never be persisted.
3. Raw secrets must never appear in:

   * PostgreSQL;
   * logs;
   * exceptions;
   * API read endpoints;
   * audit events.
4. Redaction must run before persistence, logging, audit recording, or rendering.
5. Risk and blocking decisions must be deterministic.
6. An LLM must not participate in allow, flag, or block decisions.
7. A matching block rule must prevent adapter execution.
8. Unknown or disabled tools must still never execute.
9. Sanitized payloads must preserve useful structure without retaining secrets.
10. Public error responses must remain sanitized.

---

## Scope

### Must implement

* recursive redaction engine;
* secret detection;
* sanitized payload persistence;
* risk levels;
* risk flags;
* deterministic risk classifier;
* deterministic blocking rules;
* audit-event persistence;
* blocked ToolCall lifecycle;
* persistent response replay;
* rule management API;
* security tests;
* documentation and threat-model updates.

### Must not implement

* Ollama integration;
* MCP;
* authentication;
* users or tenants;
* human approvals;
* external policy engines;
* OPA, Cedar, or OpenFGA;
* ML anomaly detection;
* real GitHub, email, or database integrations;
* background recovery worker;
* complete OpenTelemetry GenAI instrumentation;
* dashboard.

---

## Domain additions

Add framework-independent domain concepts:

* `RiskLevel`;
* `RiskFlag`;
* `RiskFlagCode`;
* `RuleAction`;
* `BlockingRule`;
* `RuleMatch`;
* `RuleEvaluation`;
* `RedactionResult`;
* `RedactionFinding`;
* `AuditEvent`;
* `AuditEventType`.

Domain code must remain independent of FastAPI, SQLAlchemy, and telemetry SDKs.

---

## Risk levels

Define ordered levels:

```text
low
medium
high
critical
```

Ordering:

```text
low < medium < high < critical
```

A higher discovered risk may raise the effective risk level.

No detector or rule may lower the registered tool’s `base_risk_level`.

Example:

```text
registered base risk: medium
secret detected: high
effective risk: high
```

---

## Rule actions

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

Rules must not lower risk.

A block decision is terminal for rule evaluation.

---

## ToolCall changes

Extend ToolCall with:

```text
risk_level
decision
matched_rule_ids
redacted_arguments
```

Allowed decisions:

```text
allow
flag
block
reject
```

Extend statuses:

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

Required paths:

```text
received → validating → rejected

received → validating → evaluating → blocked

received → validating → evaluating → executing → succeeded

received → validating → evaluating → executing → failed

received → validating → evaluating → executing → timed_out
```

`blocked` is terminal.

A blocked call must not invoke the adapter.

---

## Tool result changes

Replace or extend `ToolResultMetadata` to support:

```text
tool_call_id
redacted_payload
payload_hash
content_type
size_bytes
schema_valid
truncated
created_at
```

Requirements:

* store only sanitized output;
* retain the existing hash of the original canonical output where safe;
* never persist original output;
* enforce result-size limits before and after redaction;
* API replay must use the persisted redacted payload;
* read endpoints must return only redacted content.

If the result is too large:

* do not persist the full result;
* return the established safe error;
* mark execution failed.

Do not silently truncate API execution results unless the product specification explicitly requires truncation.

---

# Part 1: Redaction engine

## Redaction API

Implement a framework-independent service similar to:

```python
class Redactor(Protocol):
    def redact(self, value: JSONValue) -> RedactionResult:
        ...
```

Example result:

```python
@dataclass(frozen=True)
class RedactionResult:
    value: JSONValue
    findings: tuple[RedactionFinding, ...]
```

A finding must contain only safe metadata:

```text
path
detector
category
fingerprint
```

It must not contain the original secret.

---

## Sensitive field names

Match keys case-insensitively.

At minimum:

```text
password
passwd
passphrase
secret
token
access_token
refresh_token
api_key
apikey
authorization
proxy_authorization
cookie
set_cookie
private_key
client_secret
credential
credentials
```

Support common naming variants:

```text
apiKey
accessToken
clientSecret
privateKey
```

Normalize names before matching.

Do not redact every field merely containing the substring `key`, because fields such as `monkey`, `keyboard`, or `foreign_key` would produce excessive false positives.

---

## Value-pattern detection

Detect at least:

### Authorization values

```text
Bearer <value>
Basic <value>
```

### JWT-like values

Three base64url-like dot-separated segments.

### Private keys

Headers such as:

```text
-----BEGIN PRIVATE KEY-----
-----BEGIN RSA PRIVATE KEY-----
-----BEGIN OPENSSH PRIVATE KEY-----
```

### Credentials in URLs

Example:

```text
https://username:password@example.com/path
```

Sanitized form must not retain the password.

### Configurable secret patterns

Provide configuration for additional patterns.

Do not add vendor-specific patterns unless tested and documented.

---

## Replacement format

Default replacement:

```text
[REDACTED]
```

Optional development-safe form:

```text
[REDACTED:<fingerprint-prefix>]
```

Do not expose the full fingerprint publicly.

---

## Secret fingerprints

Use keyed HMAC-SHA256 rather than plain SHA-256:

```text
HMAC-SHA256(REDACTION_FINGERPRINT_KEY, secret)
```

Requirements:

* key comes from environment configuration;
* production-like startup must reject a missing or unsafe key when fingerprints are enabled;
* fingerprinting may be disabled;
* do not persist or log the key;
* only a short prefix may appear in public sanitized data;
* full fingerprint may be stored internally if necessary;
* use constant-time comparison where fingerprints are compared.

Python’s standard `hmac` module provides keyed hashing and `compare_digest` for constant-time comparison.

---

## Recursive processing

Support:

* dictionaries;
* lists;
* strings;
* numbers;
* booleans;
* null.

Requirements:

* preserve object and array shape;
* preserve non-sensitive values;
* enforce maximum depth;
* enforce maximum number of visited nodes;
* avoid recursion exhaustion;
* behave deterministically;
* be idempotent.

Required property:

```text
redact(redact(value)) == redact(value)
```

Do not attempt to process arbitrary Python objects.

---

## Partial-string redaction

For strings containing an embedded secret, redact only the sensitive portion when safe.

Example:

Input:

```text
Authorization failed for Bearer abcdef123456
```

Output:

```text
Authorization failed for [REDACTED]
```

Do not return the original secret in finding metadata.

---

## Redaction order

Redaction must occur:

1. after structural request parsing;
2. after argument schema validation;
3. before logging arguments;
4. before persisting arguments;
5. before risk findings are persisted;
6. after adapter output is received;
7. before output logging, persistence, audit, tracing, or API replay storage.

The adapter may receive the original validated arguments because it needs them to execute.

No other downstream component should receive raw payloads unless explicitly required within the trusted execution boundary.

---

# Part 2: Risk engine

## Inputs

Risk evaluation may use:

* registered base risk;
* tool name;
* adapter type;
* validated arguments;
* redaction findings;
* payload size;
* known operation semantics;
* deterministic detectors.

It must not use:

* LLM output as authority;
* probabilistic model inference;
* user-controlled risk labels;
* tool description as a trusted instruction.

---

## Required risk flags

Implement stable codes at minimum:

```text
write_operation
external_side_effect
sensitive_input
sensitive_output
destructive_sql
write_sql
multiple_sql_statements
possible_command_injection
possible_path_traversal
possible_ssrf_target
possible_indirect_prompt_injection
oversized_payload
unknown_operation
```

Each flag contains:

```text
code
severity
message
safe_evidence
```

`safe_evidence` must not include secrets or full payloads.

Example:

```json
{
  "code": "destructive_sql",
  "severity": "critical",
  "message": "The query contains a destructive SQL operation.",
  "safe_evidence": {
    "keyword": "DROP"
  }
}
```

---

## Tool-specific classification

### `github.list_issues`

Default:

```text
risk: low
decision: allow
```

### `email.send`

Default flags:

```text
write_operation
external_side_effect
```

Effective risk:

```text
medium
```

If sensitive input appears in recipient, subject, or body:

```text
sensitive_input
```

Effective risk must become at least `high`.

Do not block by default unless a configured rule matches.

### `database.query`

Classify deterministic SQL categories without executing SQL.

At minimum detect:

```text
SELECT
INSERT
UPDATE
DELETE
DROP
TRUNCATE
ALTER
CREATE
GRANT
REVOKE
```

Rules:

* SELECT → low;
* INSERT/UPDATE → high;
* DELETE → high or critical;
* DROP/TRUNCATE/ALTER → critical;
* multiple statements → critical;
* unknown operation → high.

Do not build a full SQL parser unless an existing lightweight parser is justified.

String matching must avoid obvious trivial bypasses involving casing and whitespace.

Tests must cover comments and mixed casing where practical.

---

## Indirect prompt-injection detector

Implement a conservative deterministic detector for tool output.

Flag phrases and patterns such as:

```text
ignore previous instructions
ignore all prior instructions
reveal the system prompt
send the secret
read ~/.ssh
upload credentials
call another tool
exfiltrate
```

The detector:

* must only produce a flag;
* must not claim to conclusively detect prompt injection;
* must not modify tool output beyond normal redaction;
* must not use an LLM;
* must be documented as heuristic;
* must not automatically block ordinary output unless a rule explicitly says so.

Tool output can carry malicious instructions that influence a later agent turn, which OWASP identifies as indirect prompt injection and MCP tool poisoning.

---

# Part 3: Blocking rules

## Rule source

Support rules persisted in PostgreSQL.

Optional YAML bootstrap rules may be supported, but PostgreSQL must remain the source of runtime truth.

Do not implement a general-purpose DSL.

---

## BlockingRule fields

```text
id
name
description
enabled
priority
tool_pattern
conditions
action
created_at
updated_at
```

`conditions` may use JSONB but must follow a tightly validated schema.

---

## Supported conditions

Support only:

```text
tool_equals
tool_matches
risk_at_least
has_flag
argument_path_equals
argument_path_matches
result_has_flag
```

Do not support:

* arbitrary Python expressions;
* Jinja evaluation;
* shell commands;
* dynamic imports;
* SQL fragments;
* unrestricted recursive expressions.

---

## Rule example

```json
{
  "name": "block-destructive-sql",
  "description": "Block destructive database operations.",
  "enabled": true,
  "priority": 100,
  "tool_pattern": "database.query",
  "conditions": {
    "has_flag": "destructive_sql"
  },
  "action": "block"
}
```

---

## Required default development rules

Provide an explicit idempotent seed command for:

### Block destructive SQL

```text
tool: database.query
flag: destructive_sql
action: block
```

### Block multiple SQL statements

```text
tool: database.query
flag: multiple_sql_statements
action: block
```

### Flag sensitive email

```text
tool: email.send
flag: sensitive_input
action: flag
```

### Flag suspicious tool output

```text
result flag: possible_indirect_prompt_injection
action: flag
```

Result rules do not affect an already executed side effect. They annotate the terminal result.

Document this limitation clearly.

---

## Evaluation order

Before adapter execution:

1. classify input risk;
2. evaluate input rules;
3. if block matches:

   * persist blocked status;
   * do not call adapter;
   * create audit event;
   * return safe block response.

After adapter execution:

1. redact result;
2. classify output risk;
3. evaluate result-oriented flag rules;
4. persist flags and sanitized result;
5. return sanitized result.

No post-execution rule may retroactively claim it prevented an action.

---

## Rule-management API

Implement:

```http
GET /api/v1/rules
POST /api/v1/rules
GET /api/v1/rules/{rule_id}
PATCH /api/v1/rules/{rule_id}
```

MVP PATCH may modify only:

```text
enabled
priority
action
description
```

Changing condition structure may require creating a new rule.

Requirements:

* validated request schema;
* stable pagination;
* deterministic ordering;
* duplicate names return conflict;
* invalid conditions return 422;
* public response must not expose internal implementation details.

Do not implement delete in this milestone.

---

# Part 4: Audit events

## AuditEvent fields

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

Use JSONB for `payload_redacted`.

No update or delete repository methods.

---

## Required event types

```text
session.started
session.completed
tool_call.received
tool_call.validated
tool_call.risk_classified
tool_call.flagged
tool_call.blocked
tool_call.started
tool_call.completed
tool_call.failed
tool_call.timed_out
redaction.applied
rule.matched
```

Do not create duplicate semantic events for retries or response replay.

---

## Audit payload restrictions

Audit payload may include:

```text
tool name
tool version
status
decision
risk level
flag codes
rule IDs
redaction count
duration
safe error code
```

It must not include:

```text
raw arguments
raw result
raw secret
raw exception
full prompt
adapter credentials
database URL
```

---

## Audit API

Implement read-only endpoints:

```http
GET /api/v1/audit-events
GET /api/v1/sessions/{session_id}/audit-events
GET /api/v1/tool-calls/{call_id}/audit-events
```

Support bounded pagination and event-type filtering.

Do not expose update or delete endpoints.

---

# Part 5: Persistent idempotent replay

The current in-memory terminal response cache must be replaced or complemented with PostgreSQL-backed replay.

Requirements:

* successful terminal sanitized result is persisted;
* blocked terminal response is reconstructable;
* rejected and failed terminal responses are reconstructable from safe metadata;
* same idempotency key and same request hash returns the prior terminal response after process restart;
* adapter must not execute again;
* conflicting request hash still returns `idempotency_conflict`;
* in-progress behavior remains fail-closed.

Do not persist raw output to support replay.

---

# Database migration

Create a migration after `0003`.

Add or alter:

```text
tool_calls
tool_result_metadata
risk_flags
blocking_rules
audit_events
```

Possible changes:

### `tool_calls`

Add:

```text
risk_level
matched_rule_ids
redacted_arguments
```

### `tool_result_metadata`

Add:

```text
redacted_payload
truncated
```

### `risk_flags`

Create table with:

```text
id
tool_call_id
code
severity
message
safe_evidence
source
created_at
```

### `blocking_rules`

Create table.

### `audit_events`

Create append-only table.

Requirements:

* JSONB where appropriate;
* named constraints;
* explicit foreign keys;
* indexes for common read paths;
* timezone-aware timestamps;
* upgrade and downgrade support;
* no raw-payload columns.

Manually inspect the migration.

---

# API execution response changes

Successful response may now include:

```json
{
  "call_id": "call_...",
  "status": "succeeded",
  "decision": "allow",
  "risk": "low",
  "flags": [],
  "result": {
    "issues": []
  }
}
```

Flagged response:

```json
{
  "call_id": "call_...",
  "status": "succeeded",
  "decision": "flag",
  "risk": "high",
  "flags": [
    "sensitive_input"
  ],
  "result": {
    "message_id": "msg_...",
    "status": "accepted"
  }
}
```

Blocked response:

```text
403 Forbidden
```

```json
{
  "call_id": "call_...",
  "status": "blocked",
  "decision": "block",
  "risk": "critical",
  "flags": [
    "destructive_sql"
  ],
  "matched_rules": [
    "block-destructive-sql"
  ],
  "error": {
    "code": "tool_call_blocked",
    "message": "The tool call was blocked by a runtime safety rule.",
    "correlation_id": "..."
  }
}
```

Do not expose rule internals or sensitive evidence.

---

# Configuration

Add:

```text
REDACTION_ENABLED=true
REDACTION_REPLACEMENT=[REDACTED]
REDACTION_FINGERPRINTS_ENABLED=true
REDACTION_FINGERPRINT_KEY=<development-value>
MAX_REDACTION_DEPTH=20
MAX_REDACTION_NODES=10000
STORE_REDACTED_ARGUMENTS=true
STORE_REDACTED_RESULTS=true
```

`.env.example` may contain an explicit development-only placeholder.

Document that production deployments need a strong independent key.

---

# Required tests

## Redaction unit tests

Cover:

* sensitive key;
* camelCase sensitive key;
* nested dictionary;
* nested list;
* bearer token;
* JWT-like token;
* private key;
* credentials in URL;
* embedded secret;
* repeated secret fingerprint;
* idempotency;
* maximum depth;
* maximum nodes;
* non-sensitive similar field names;
* empty values;
* already-redacted values.

## Property-based tests

Required properties:

```text
redact(redact(x)) == redact(x)
```

```text
known secret not in serialize(redact(x))
```

```text
redaction preserves JSON compatibility
```

```text
redaction never increases nesting depth
```

## Risk-engine tests

Cover:

* base risk preserved;
* sensitive input raises risk;
* SELECT low;
* UPDATE high;
* DELETE high or critical;
* DROP critical;
* mixed case;
* whitespace;
* multiple statements;
* prompt-injection heuristic;
* unknown operation.

## Rule-engine tests

Cover:

* priority;
* block precedence;
* disabled rule ignored;
* tool exact match;
* tool pattern;
* flag match;
* risk threshold;
* argument path;
* malformed conditions;
* deterministic result;
* no arbitrary expression execution.

## Execution tests

Cover:

* redacted arguments persisted;
* redacted result persisted;
* raw payload absent;
* safe call allowed;
* medium call flagged;
* destructive SQL blocked;
* blocked adapter not invoked;
* suspicious output flagged;
* result replay after creating a new application instance;
* conflicting idempotency request still rejected.

## Audit tests

Cover:

* expected lifecycle events;
* blocked lifecycle;
* failed lifecycle;
* timeout lifecycle;
* no duplicate events on response replay;
* raw payload absent;
* stable ordering;
* pagination.

## PostgreSQL integration tests

Cover:

* migration upgrade;
* downgrade and upgrade;
* JSONB persistence;
* risk-flag foreign keys;
* rule uniqueness;
* audit-event indexes;
* persistent replay;
* concurrent same-key request;
* blocked call state.

## Logging security tests

Inject a unique test secret and assert it is absent from:

* captured logs;
* public errors;
* persisted arguments;
* persisted results;
* audit payloads;
* risk evidence.

---

# Performance requirements

Redaction and rule evaluation run in the request path.

Local engineering targets:

```text
redaction of 64 KB JSON: p95 < 15 ms
risk classification: p95 < 10 ms
rule evaluation for 100 rules: p95 < 10 ms
```

These are benchmark targets, not production SLAs.

Add benchmarks, but do not make unstable microbenchmarks block CI unless the repository already has a stable strategy.

---

# Documentation updates

## README

Add:

* redaction example;
* allowed, flagged, and blocked examples;
* rule seed command;
* audit API examples;
* persistent replay explanation;
* warning that heuristic prompt-injection detection is not a guarantee.

## Architecture

Document:

* raw trusted execution boundary;
* redaction boundary;
* risk-classification pipeline;
* pre-execution and post-execution rules;
* audit-event flow;
* persistent replay.

## Threat model

Add:

* secret leakage;
* redaction bypass;
* regex denial of service;
* misleading risk evidence;
* rule poisoning;
* rule precedence errors;
* malicious tool output;
* indirect prompt injection;
* audit-log manipulation;
* sensitive data in observability attributes.

## Testing

Document:

* property-based redaction tests;
* rule-engine tests;
* audit-event tests;
* persistent replay tests.

## ADR

Create ADRs for:

1. deterministic security decisions;
2. sanitized payload persistence;
3. HMAC-based secret fingerprints;
4. pre-execution versus post-execution rules.

Combine closely related decisions if appropriate.

---

# Non-goals

Do not implement:

* Ollama;
* model prompts;
* agent loop;
* MCP;
* OpenTelemetry GenAI spans;
* approval workflows;
* authentication;
* external policy engine;
* real tools;
* arbitrary network access;
* anomaly ML;
* recovery worker;
* retry queue.

---

# Acceptance criteria

The milestone is complete only when:

1. Recursive deterministic redaction exists.
2. Raw secrets never enter persisted sanitized payloads.
3. Raw arguments and results remain absent from logs.
4. Redacted arguments and results are stored.
5. Successful responses can be replayed after application restart.
6. Risk levels and risk flags are persisted.
7. Risk cannot be lowered below registered base risk.
8. Blocking rules are deterministic.
9. Destructive SQL is blocked before adapter execution.
10. Sensitive email calls are flagged.
11. Suspicious tool output is flagged.
12. Blocked adapters are never invoked.
13. Audit events cover the complete lifecycle.
14. Audit events expose no raw payloads.
15. Rule-management API works.
16. Audit read APIs work.
17. Migrations upgrade and downgrade successfully.
18. Unit, property, API, integration, concurrency, and security tests pass.
19. `make check` passes.
20. Docker Compose remains healthy.
21. Existing health, registry, session, and execution behavior remains compatible.
22. Documentation and threat model are updated.
23. Ollama and real external tools remain unimplemented.

---

# Required implementation process

Before coding:

1. inspect the execution pipeline and persistence boundaries;
2. inspect every logging and error path;
3. summarize the proposed redaction algorithm;
4. summarize fingerprint-key handling;
5. summarize risk detectors;
6. summarize rule evaluation and precedence;
7. summarize audit-event transaction behavior;
8. summarize persistent replay design;
9. identify compatibility changes to existing APIs;
10. proceed without waiting unless genuinely blocked.

During implementation:

1. implement redaction and tests first;
2. implement risk classification;
3. implement rule domain and evaluator;
4. add persistence migration;
5. integrate pre-execution rules;
6. integrate output redaction and post-execution flags;
7. add audit events;
8. implement persistent replay;
9. add APIs last;
10. never retain raw payloads for debugging.

Before completion:

1. run focused tests after each stage;
2. run property-based tests;
3. run PostgreSQL integration tests;
4. test migration upgrade/downgrade/upgrade;
5. run `alembic check`;
6. run `make check`;
7. run Docker Compose smoke tests;
8. inject a unique test secret and search:

   * database rows;
   * logs;
   * API output;
   * audit events;
9. inspect Git diff;
10. report:

* created and modified files;
* migration details;
* redaction design;
* risk and rule behavior;
* audit design;
* replay behavior;
* commands executed;
* test results;
* unverified checks;
* remaining risks.

Do not claim a check passed unless it actually ran successfully.

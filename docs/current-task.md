# Current Task: Observability v1

## Context

ToolWatch currently provides:

* Tool Registry;
* Agent Sessions;
* trusted tool-call execution;
* JSON Schema validation;
* deterministic redaction;
* risk classification;
* blocking rules;
* risk flags;
* audit events;
* persistent idempotent replay;
* PostgreSQL persistence;
* structured safe lifecycle logging.

This milestone introduces complete operational observability without exposing raw prompts, tool arguments, tool results, secrets, or high-cardinality data.

Read before changing code:

1. `AGENTS.md`
2. `docs/product-spec.md`
3. `docs/architecture.md`
4. `docs/threat-model.md`
5. `docs/testing.md`
6. all existing telemetry, execution, security, audit, API, and configuration code
7. relevant ADRs

Treat `AGENTS.md` and `docs/product-spec.md` as authoritative.

---

## Goal

Implement:

1. OpenTelemetry tracing;
2. application and tool-execution spans;
3. Prometheus-compatible metrics;
4. trace and correlation ID propagation;
5. correlation between traces and audit events;
6. telemetry-safe attribute filtering;
7. Jaeger integration;
8. operational documentation and tests.

The complete observable flow should be:

```text
HTTP request span
    ↓
application use-case span
    ↓
tool validation span
    ↓
risk evaluation span
    ↓
rule evaluation span
    ↓
execute_tool span
    ↓
result validation/redaction span
    ↓
persistence span
```

Do not implement Ollama, dashboard, MCP, or real external tools in this milestone.

---

## Security invariants

Telemetry must never contain:

* raw prompts;
* raw arguments;
* raw results;
* redacted payload bodies;
* secrets;
* authorization headers;
* cookies;
* database URLs;
* adapter configuration;
* arbitrary exception messages;
* arbitrary user-controlled URLs;
* audit payload bodies.

Only bounded, low-cardinality, sanitized metadata may be emitted.

A telemetry exporter failure must not cause a tool execution request to fail.

Telemetry must fail open for availability, while execution security remains fail closed.

---

## Architecture

Telemetry must remain an infrastructure concern.

Expected structure:

```text
src/toolwatch/telemetry/
├── __init__.py
├── config.py
├── provider.py
├── tracing.py
├── metrics.py
├── attributes.py
├── middleware.py
└── testing.py
```

Small deviations are allowed when consistent with the repository.

Domain code must not import OpenTelemetry.

Application code may depend on a small internal telemetry protocol or no-op abstraction, but must not depend directly on vendor exporters.

Required implementations:

* real OpenTelemetry implementation;
* no-op implementation;
* test recorder implementation where useful.

---

## Configuration

Add typed settings:

```text
OTEL_ENABLED=true
OTEL_SERVICE_NAME=toolwatch
OTEL_SERVICE_VERSION=<application version>
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=prometheus
OTEL_TRACE_SAMPLE_RATIO=1.0
OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental
METRICS_ENABLED=true
METRICS_PATH=/metrics
```

Requirements:

* telemetry can be fully disabled;
* tests default to in-memory or no-op exporters;
* CI must not require Jaeger;
* exporter configuration errors must be sanitized;
* no API startup network connection should block application readiness indefinitely;
* application shutdown must flush and close providers safely.

---

## Resource attributes

Configure low-cardinality resource attributes:

```text
service.name
service.version
deployment.environment.name
telemetry.sdk.language
```

Do not use:

* hostname when unnecessary;
* developer username;
* local filesystem path;
* database name;
* Git branch;
* session ID.

---

# Part 1: Trace propagation

## Incoming requests

Instrument FastAPI requests.

Required behavior:

* accept valid W3C Trace Context headers;
* create a server span for each request;
* propagate current trace context through application execution;
* include response correlation ID;
* return a correlation header such as:

```http
X-Correlation-ID: <value>
```

If the client provides a valid correlation ID according to a strict format, it may be reused.

Otherwise generate one.

Do not trust arbitrary unbounded correlation strings.

Recommended format:

```text
UUID
```

---

## Internal correlation

Every relevant request must expose:

```text
correlation_id
trace_id
span_id
```

Use these identifiers in:

* structured logs;
* audit events;
* safe API error responses;
* tool-call records where already supported.

Do not expose internal database IDs unnecessarily.

Trace ID must come from the active OpenTelemetry span where available.

When tracing is disabled, correlation ID must still work.

---

# Part 2: Required spans

## HTTP request spans

Use supported FastAPI/ASGI instrumentation where practical.

Avoid double instrumentation.

Capture:

* HTTP method;
* route template;
* response status;
* server duration.

Do not capture:

* raw request body;
* query parameter values unless explicitly allowlisted;
* authorization headers;
* cookies;
* arbitrary URL query strings.

---

## Application use-case spans

Create internal spans for important orchestration flows:

```text
toolwatch.create_session
toolwatch.register_tool
toolwatch.execute_tool_call
toolwatch.evaluate_risk
toolwatch.evaluate_rules
toolwatch.persist_terminal_result
toolwatch.replay_tool_call
```

Use bounded span names.

Do not include IDs in span names.

IDs may be attributes only where explicitly allowed.

---

## Tool execution spans

Create one span for every attempted adapter execution.

Span name:

```text
execute_tool {tool_name}
```

Span kind:

```text
INTERNAL
```

Required attributes:

```text
gen_ai.operation.name = execute_tool
gen_ai.tool.name
gen_ai.tool.type
toolwatch.tool.version
toolwatch.tool.adapter_type
toolwatch.risk.level
toolwatch.decision
toolwatch.call.status
toolwatch.replayed
```

Optional safe attributes:

```text
toolwatch.flag.count
toolwatch.rule.match_count
toolwatch.redaction.input_count
toolwatch.redaction.output_count
```

Do not attach:

```text
tool arguments
tool result
tool description
rule body
risk evidence body
error message
session prompt
```

Because GenAI semantic conventions are experimental, isolate attribute names behind a single telemetry attribute module.

---

## Validation and security spans

Create short internal spans:

```text
toolwatch.validate_arguments
toolwatch.redact_arguments
toolwatch.classify_risk
toolwatch.evaluate_rules
toolwatch.redact_result
toolwatch.validate_result
```

Required safe attributes may include:

```text
validation.valid
validation.error_count
redaction.finding_count
risk.level
rule.match_count
decision
```

Do not add field paths if they could disclose sensitive structure.

---

## Persistence spans

Prefer SQLAlchemy instrumentation where it is stable and compatible.

Do not manually add SQL statements to span attributes.

Do not capture bind parameters.

Ensure database instrumentation does not expose:

* SQL parameter values;
* connection strings;
* passwords;
* raw JSONB payloads.

If safe SQLAlchemy instrumentation cannot be guaranteed, keep persistence spans manual and coarse-grained.

---

## Span status and errors

Span status must reflect operation outcome:

* success → unset/OK according to SDK conventions;
* rejected validation → not an infrastructure error;
* blocked request → not an exception;
* timeout → error;
* adapter failure → error;
* database failure → error.

Record exception type where safe.

Do not record arbitrary exception messages by default.

Allowed:

```text
exception.type
toolwatch.error.code
```

Forbidden:

```text
exception.message
exception.stacktrace
```

unless a development-only explicit opt-in is enabled and sanitization is guaranteed.

Default must remain safe.

---

# Part 3: Metrics

Expose Prometheus-compatible metrics through:

```http
GET /metrics
```

The endpoint may be disabled through configuration.

Required metrics:

```text
toolwatch_http_requests_total
toolwatch_http_request_duration_seconds

toolwatch_sessions_total

toolwatch_tool_calls_total
toolwatch_tool_call_duration_seconds
toolwatch_tool_calls_blocked_total
toolwatch_tool_calls_failed_total
toolwatch_tool_calls_replayed_total
toolwatch_tool_timeouts_total

toolwatch_validation_failures_total
toolwatch_redactions_total
toolwatch_risk_flags_total
toolwatch_rule_matches_total
toolwatch_audit_events_total

toolwatch_db_operation_duration_seconds
```

Use correct metric types:

* counters for totals;
* histograms for durations;
* gauges only for meaningful current-state values.

Do not include units in metric names when metadata already defines the unit.

---

## Metric labels

Allowed bounded labels:

```text
http.method
http.route
http.status_code

tool_name
tool_version
adapter_type
status
decision
risk_level
error_code
flag_code
rule_action
replayed
```

Before adding a label, confirm that its possible values are bounded.

Forbidden labels:

```text
session_id
tool_call_id
agent_id
trace_id
correlation_id
repository
email
SQL query
URL
rule_id
rule_name
free-form exception
user prompt
model output
```

Rule names and IDs must not be labels because user-created rules can create unbounded cardinality.

---

## Histogram boundaries

Use documented explicit histogram buckets suitable for local tool execution.

Example seconds:

```text
0.001
0.005
0.01
0.025
0.05
0.1
0.25
0.5
1
2.5
5
10
30
```

Do not rely on arbitrary defaults without documenting them.

---

# Part 4: Logging correlation

Extend structured logs to consistently include:

```text
correlation_id
trace_id
span_id
service
environment
```

Existing lifecycle logs must retain safe fields:

```text
call_id
session_id
tool_name
tool_version
status
decision
risk_level
duration_ms
error_code
```

Requirements:

* missing trace context must not break logging;
* redaction processor remains active;
* raw payloads remain prohibited;
* trace fields are serialized as normalized lowercase hex strings;
* logging itself must not create additional spans.

---

# Part 5: Audit correlation

Every newly created audit event related to an active request must contain:

```text
trace_id
```

Where useful, also store:

```text
correlation_id
```

Requirements:

* replayed requests must not duplicate semantic audit events;
* audit API may expose trace ID and correlation ID;
* these identifiers must be queryable through bounded API filters;
* do not expose span ID unless needed.

Add filters:

```http
GET /api/v1/audit-events?trace_id=...
GET /api/v1/audit-events?correlation_id=...
```

Validate identifier formats strictly.

---

# Part 6: Jaeger and local infrastructure

Update Compose observability profile.

Required service:

```text
jaeger
```

Expose:

```text
16686  Jaeger UI
4317   OTLP gRPC
4318   OTLP HTTP
```

ToolWatch should use OTLP HTTP by default.

Requirements:

* Jaeger remains optional under an observability profile;
* API starts when Jaeger is unavailable;
* exporter retries must not block request completion;
* README documents how to open a trace in Jaeger;
* development telemetry data is ephemeral.

Do not add Elasticsearch.

---

# Part 7: Sampling

Implement configurable parent-based ratio sampling.

Default local development:

```text
1.0
```

Document recommended non-development behavior.

Security events must remain available through audit logs even when traces are unsampled.

Do not use tracing as the authoritative security record.

Audit remains the authoritative event history.

---

# Part 8: Telemetry self-protection

Add one internal telemetry health status.

Possible checks:

* provider initialized;
* exporter configuration valid;
* latest export failure count where available.

Do not make `/health/ready` fail merely because Jaeger is unavailable.

Optionally expose safe status:

```http
GET /health/telemetry
```

Example:

```json
{
  "status": "degraded",
  "tracing": "configured",
  "exporter": "unavailable"
}
```

Do not expose exporter URLs with embedded credentials.

---

# Testing requirements

## Unit tests

Cover:

* telemetry enabled and disabled;
* correlation ID validation;
* trace ID formatting;
* safe attribute allowlist;
* forbidden attribute rejection;
* span naming;
* metric label validation;
* no-op provider;
* provider shutdown.

---

## Trace tests

Use in-memory exporters.

Cover:

* request span exists;
* execute-tool span exists;
* correct parent-child relationships;
* safe required attributes;
* allowed operation status;
* blocked call has no adapter execution span;
* failed and timed-out calls set error status;
* replay is marked;
* tracing disabled creates no exported spans;
* trace propagation accepts valid W3C headers;
* malformed trace headers fail safely.

---

## Telemetry security tests

Inject unique secrets into:

* arguments;
* results;
* prompts;
* adapter exceptions;
* rule evidence.

Assert the secret is absent from:

* span names;
* span attributes;
* span events;
* metric labels;
* metric values where relevant;
* structured logs;
* audit correlation fields;
* exporter error logs.

---

## Metrics tests

Cover:

* successful call counter;
* blocked call counter;
* failed call counter;
* timeout counter;
* replay counter;
* redaction counter;
* risk flag counter;
* rule-match counter;
* histogram observations;
* no high-cardinality labels;
* metrics endpoint disabled;
* metrics endpoint enabled.

Avoid tests that depend on global metric state leaking between cases.

---

## Integration tests

Use PostgreSQL and in-memory telemetry exporter.

Cover:

* complete successful request trace;
* blocked request trace;
* timeout trace;
* replay trace;
* audit event trace correlation;
* trace ID persisted safely;
* no duplicate audit events;
* exporter failure does not fail request.

---

## Compose smoke test

Start:

```bash
docker compose --profile observability up --build
```

Verify:

* API healthy;
* PostgreSQL healthy;
* Jaeger healthy;
* one tool call generates a visible trace;
* trace includes execute-tool span;
* no payload body is present in Jaeger.

Do not claim Jaeger visibility unless manually or programmatically verified.

---

# Performance targets

Telemetry overhead targets for local development:

```text
tracing enabled, in-memory exporter:
p95 additional overhead < 5 ms

metrics recording:
p95 additional overhead < 1 ms
```

Use representative execution tests.

These are engineering targets, not public SLAs.

Telemetry benchmark failures should not block CI unless stable enough.

---

# OpenAPI and API changes

Document:

```text
X-Correlation-ID response header
/metrics
optional /health/telemetry
audit trace/correlation filters
```

Do not expose internal telemetry configuration through API.

---

# Documentation updates

## README

Add:

* observability architecture;
* how to start Jaeger;
* how to execute a test call;
* how to locate its trace;
* metrics endpoint;
* privacy guarantees;
* sampling notes.

## `docs/architecture.md`

Document:

* telemetry adapter boundary;
* span hierarchy;
* logs/traces/audit correlation;
* why audit is authoritative;
* failure behavior when exporter is down.

## `docs/threat-model.md`

Add:

* secret leakage through telemetry;
* high-cardinality denial of service;
* malicious trace headers;
* oversized baggage;
* exporter credential leakage;
* sensitive exception stack traces;
* spoofed correlation IDs;
* telemetry backend outage.

## `docs/testing.md`

Document:

* in-memory span exporter;
* isolated meter providers;
* telemetry security regression tests;
* Jaeger smoke test.

## ADR

Create an ADR covering:

* OpenTelemetry as the telemetry abstraction;
* audit log as authoritative security history;
* safe attribute allowlist;
* experimental GenAI semantic conventions isolated behind adapter.

---

# Non-goals

Do not implement:

* Ollama;
* LLM spans;
* model token metrics;
* MCP;
* dashboard;
* real integrations;
* authentication;
* approval workflows;
* distributed tracing across external tools;
* log backend such as Loki;
* Elasticsearch;
* production observability backend;
* alerting rules.

---

# Acceptance criteria

The milestone is complete only when:

1. OpenTelemetry can be enabled and disabled.
2. FastAPI requests produce server spans.
3. Tool execution produces `execute_tool` spans.
4. Span hierarchy is correct.
5. Blocked calls do not produce adapter execution spans.
6. Safe attributes are allowlisted.
7. Raw prompts, arguments, results, and secrets never enter telemetry.
8. Metrics endpoint exposes required metrics.
9. Metrics have bounded labels.
10. Logs include trace and correlation IDs.
11. Audit events can be correlated with traces.
12. Audit remains authoritative when sampling disables traces.
13. Exporter failure does not fail requests.
14. Jaeger works through the Compose observability profile.
15. Tool traces are visible in Jaeger.
16. Unit, trace, metrics, security, and integration tests pass.
17. `make check` passes.
18. Docker Compose remains healthy.
19. Existing execution and security behavior remains compatible.
20. Documentation and threat model are updated.
21. Ollama, dashboard, and MCP remain unimplemented.

---

# Required implementation process

Before coding:

1. inspect existing telemetry placeholders;
2. inspect all logging paths;
3. inspect audit-event creation;
4. identify every candidate span;
5. define the safe attribute allowlist;
6. define metric labels and cardinality;
7. describe provider lifecycle;
8. describe exporter-failure behavior;
9. identify GenAI semantic-convention isolation;
10. proceed without waiting unless genuinely blocked.

During implementation:

1. implement telemetry configuration and no-op providers;
2. implement safe attribute handling;
3. implement request correlation;
4. instrument tool execution;
5. instrument application operations;
6. add metrics;
7. correlate logs and audit events;
8. add Jaeger configuration;
9. implement tests before documentation;
10. never add raw payloads for debugging.

Before completion:

1. run focused telemetry tests;
2. run secret-leak regression tests;
3. run PostgreSQL integration tests;
4. run `make check`;
5. run Compose with observability profile;
6. generate one allowed and one blocked tool call;
7. inspect Jaeger spans manually or programmatically;
8. verify no payloads or secrets appear;
9. inspect `/metrics` for forbidden labels;
10. inspect Git diff;
11. report:

* files changed;
* provider and exporter design;
* span hierarchy;
* metrics and labels;
* correlation design;
* commands run;
* tests;
* Jaeger verification;
* unverified checks;
* remaining risks.

Do not claim a check passed unless it actually ran.

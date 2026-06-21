# Threat Model

ToolWatch treats agent input, LLM output, tool arguments, tool results, and
infrastructure exceptions as untrusted. Security decisions must be deterministic and
blocked or invalid calls must never reach downstream adapters.

| Threat | Example | Required mitigation |
|---|---|---|
| Secret leakage | API token in arguments or a database URL in an exception | Redact before logging, tracing, persistence, or rendering; expose fixed public errors |
| Unknown or disabled tool execution | Agent invents `shell.execute` | Resolve only from a trusted allowlisted registry and stop before adapter invocation |
| Invalid arguments | Payload does not match the registered schema | Validate before adapters receive data |
| SSRF | Tool targets a metadata or private-network endpoint | Use preconfigured targets and deterministic host/IP validation |
| Destructive operation | `DROP TABLE` submitted to a database tool | Deterministic risk and blocking rules before execution |
| Oversized or deeply nested payload | Multi-megabyte result or recursive JSON | Enforce size, depth, timeout, and truncation limits |
| Prompt injection in output | Tool result asks the agent to bypass controls | Treat output as data and route subsequent calls through the same controls |
| Readiness information disclosure | PostgreSQL connection failure contains credentials or hostnames | Collapse failures to `database: unavailable`; never return raw exceptions |
| Registry poisoning | A caller registers an ambiguous or conflicting tool identity | Validate namespace-like names and schemas; enforce `(name, version)` with a named PostgreSQL unique constraint |
| Schema abuse | Deep, oversized, or malformed JSON Schema consumes resources | Bound JSON size/depth and validate the stored structural subset at registration |
| Adapter secret leakage | Raw credentials are placed in adapter configuration | Reject secret-like keys and omit adapter configuration from public responses |
| Prompt persistence | A session prompt contains a bearer token or other secret | Store no prompt by default; explicit development storage uses a temporary minimal sanitizer |
| Conflicting agent identity | Concurrent requests create duplicate logical agents | Normalize optional version, enforce a unique identity, and use a PostgreSQL upsert |
| Infrastructure error disclosure | SQLAlchemy errors contain SQL, hosts, or credentials | Return a fixed `internal_error` with a correlation ID |
| Arbitrary adapter loading | Registry value names a Python import path | Resolve only from a static immutable adapter allowlist; never import from database values |
| Duplicate side effects | Concurrent retries send the same email twice | Unique idempotency key, canonical request hash, session lock, and fail-closed in-progress response |
| Timeout without cancellation | Adapter ignores coroutine cancellation | Mark timed out, never retry automatically, and require trusted adapters; document cooperative cancellation |
| Malicious adapter output | Output contains unexpected structure or instructions | Bound and validate output before return; persist only hash and safe metadata |
| Raw execution payload leakage | Secret appears in arguments, result, logs, or rows | No payload columns; ID-only lifecycle logs; direct validated response only |
| Payload exhaustion | Deep or oversized JSON consumes memory or storage | Canonical byte, depth, and string limits before execution and before return |
| Crash after side effect | Process exits before terminal state commits | Idempotency reduces replay risk; fail closed on unresolved keys; document lack of distributed transaction |

## Current attack surface

Milestone 2 exposes health, tool-registry, and agent-session endpoints. Liveness has no
downstream dependency. Readiness executes a constant `SELECT 1` and returns a fixed 503
body on failure. Business endpoints persist only validated domain data and use sanitized
public errors.

Development credentials in `.env.example` and Compose are local-only placeholders.
Real secrets must be supplied outside version control. The API image does not copy `.env`
and runs as a non-root user.

Tool execution is limited to three trusted in-process mock adapters with no external
network, email, or SQL effects. Full recursive redaction, risk evaluation, policy
enforcement, audit events, LLM integration, and dashboard rendering are not present yet.
Consequently raw argument and result bodies are deliberately not persisted at all.

Known execution limitations are process-local successful-response replay while result
persistence is forbidden, cooperative timeout cancellation, and no automated recovery
for calls left `executing` by a process crash.

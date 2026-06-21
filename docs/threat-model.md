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

## Current attack surface

Milestone 2 exposes health, tool-registry, and agent-session endpoints. Liveness has no
downstream dependency. Readiness executes a constant `SELECT 1` and returns a fixed 503
body on failure. Business endpoints persist only validated domain data and use sanitized
public errors.

Development credentials in `.env.example` and Compose are local-only placeholders.
Real secrets must be supplied outside version control. The API image does not copy `.env`
and runs as a non-root user.

Tool execution, adapters, LLM integration, full recursive redaction, risk evaluation,
policy enforcement, audit events, and dashboard rendering are not present yet. The
registry must not be interpreted as an execution capability.

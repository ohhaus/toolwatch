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

## Bootstrap attack surface

Milestone 1 exposes only health endpoints. Liveness has no downstream dependency.
Readiness executes a constant `SELECT 1` through the configured PostgreSQL engine and
returns a fixed 503 body on every failure. It does not log or render the exception.

Development credentials in `.env.example` and Compose are local-only placeholders.
Real secrets must be supplied outside version control. The API image does not copy `.env`
and runs as a non-root user.

Business endpoints, tool adapters, LLM integration, redaction, and policy enforcement are
not present yet; their detailed requirements remain in
[the product specification](product-spec.md).

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
| Raw execution payload leakage | Secret appears in arguments, result, logs, audit, or API reads | Bounded recursive redaction before persistence/rendering; sanitized-only payload columns; ID-only lifecycle logs |
| Redaction bypass | Unusual key spelling or embedded credential avoids field matching | Normalize exact sensitive names, scan bounded value patterns, support configured patterns, and retain omission as the safe fallback |
| Regex denial of service | A rule author submits catastrophic regular expressions | Bound regex length and reject backreferences, lookarounds, and nested quantifier constructs |
| Misleading risk evidence | Evidence copies a secret or full SQL body | Persist stable codes and small allowlisted evidence such as the first SQL keyword |
| Rule poisoning or precedence error | A low-priority allow weakens a destructive block | Validate a finite condition schema; deterministic ordering; `block > flag > allow`; risk never decreases |
| Audit-log manipulation | Untrusted payload is copied into an audit event | Construct audit payloads from server-controlled IDs, enums, counts, codes, and redacted metadata only |
| Sensitive observability attributes | Secret becomes a log or trace attribute | Keep lifecycle logs ID/status-only; full GenAI tracing remains out of scope |
| Telemetry payload leakage | Prompt, argument, result, rule evidence, or exception text enters a span or metric | Strict attribute/label allowlists; no span events or exception recording; unique-secret regression tests |
| Telemetry cardinality exhaustion | IDs, URLs, rule names, or destinations become Prometheus labels | Fixed label schema with bounded lifecycle and trusted-registry values; reject unknown labels |
| Malicious propagation headers | Forged or oversized trace/baggage headers consume resources or spoof correlation | Accept standard W3C trace headers only; do not accept baggage; canonical UUID correlation IDs with a hard length bound |
| Exporter credential disclosure | OTLP failure logs an endpoint containing credentials | Suppress exporter diagnostics and emit only fixed telemetry error codes |
| Sensitive stack trace | Adapter or database exception is recorded by automatic instrumentation | Disable exception events, messages, and stack traces; record safe exception type and stable error code only |
| Telemetry backend outage | Jaeger is unavailable during execution | Fail telemetry open, keep audit authoritative, expose safe degraded status, never fail readiness solely for Jaeger |
| Payload exhaustion | Deep or oversized JSON consumes memory or storage | Canonical byte, depth, and string limits before execution and before return |
| Crash after side effect | Process exits before terminal state commits | Idempotency reduces replay risk; fail closed on unresolved keys; document lack of distributed transaction |
| Stored XSS in dashboard | Tool output, audit evidence, or rule condition contains a `<script>` payload | Jinja autoescape stays on for every template; tool output is never rendered as HTML; sanitized JSON appears inside `<pre>` blocks; `|safe` is never used on tool- or audit-controlled content |
| Reflected XSS in dashboard | A query-string filter is echoed into HTML | Filter values are bound through Pydantic-like type narrowing in the router (trace_id, UUID, enum) and reflected only through autoescape |
| Malicious tool output in HTML | A tool returns HTML, attributes, or instructions | Result payload renders only as escaped JSON text; never used in `innerHTML` paths client-side |
| CSRF on Attack Lab | A malicious site posts to `/ui/attacks/{id}/run` from a developer browser | CSP `form-action 'self'`, Origin/Referer check, no JSON body accepted; the endpoint is disabled when `ATTACK_LAB_ENABLED=false` |
| Clickjacking | Dashboard embedded inside a hostile frame | `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY` on every UI response |
| Unsafe static assets | A compromised CDN serves a modified JavaScript bundle | HTMX is vendored locally; CSP disallows third-party script and style sources by default |
| Dashboard exposed without authentication | Operator binds `/ui` on a public interface | README and ADR document that authentication is not implemented and the dashboard must remain on a trusted network; configuration is binary (`DASHBOARD_ENABLED`) |
| Attack scenario abuse | A user uploads a custom scenario that runs arbitrary adapters | Attack Lab is a static immutable registry; no endpoint accepts arbitrary scenarios or payloads; adapter overrides are scoped to the run and restored on teardown |
| Sensitive browser history | Sensitive pages cached in HTMX history or browser back-forward cache | `Cache-Control: no-store` and `htmx-config` `historyCacheSize:0` |
| Trace-link manipulation | Attacker controls a parameter to forge a Jaeger URL | Jaeger base URL comes from trusted settings; trace ID validated against W3C lowercase 32-hex; link omitted on mismatch; `rel="noopener noreferrer"` applied |
| Denial of service through dashboard filters | An operator submits a giant page size or unbounded scan | `DASHBOARD_MAX_PAGE_SIZE` clamps page size; query services use bounded per-session call limits; deterministic ordering and pagination |
| Model invents a tool | Ollama requests `shell.execute` | Resolve only through the provider-name map built from enabled registered tools; return `unknown_tool`; never invoke an adapter |
| Malformed model tool call | Arguments are a string, oversized object, or invalid JSON | Parse into strict internal types, enforce bounds, then run registered JSON Schema validation before adapters |
| Repeated blocked calls | A model retries destructive SQL indefinitely | Return only a safe blocked result and enforce turn/total-tool/per-turn limits |
| Tool-result prompt injection | A fixture asks the model to reveal data or call another tool | Mark output as untrusted in the fixed system prompt; sanitize it; route every subsequent request through deterministic controls |
| Agent-loop resource exhaustion | Model loops, emits huge messages, or stalls | Bound turns, tool calls, exposed tools, message bytes, conversation bytes, provider response bytes, model-call timeout, and run timeout |
| Ollama endpoint spoofing | Configuration points to credentials or a remote attacker | Accept only credential-free localhost/loopback HTTP(S) URLs from trusted configuration; never accept a URL in API input |
| Model allowlist bypass | Caller selects an arbitrary installed model | Separate trusted fake/Ollama allowlists; validate defaults and requests; expose no pull or model-management API |
| Thinking leakage | Provider returns hidden reasoning containing secrets | Discard thinking immediately; omit it from domain persistence, API, audit, telemetry, logs, and dashboard |
| Unsafe conversation persistence | Prompts or raw tool results are stored for replay | Keep only a bounded redacted in-memory history; persist safe run/model metadata and redacted final content only |

## Current attack surface

Milestone 2 exposes health, tool-registry, and agent-session endpoints. Liveness has no
downstream dependency. Readiness executes a constant `SELECT 1` and returns a fixed 503
body on failure. Business endpoints persist only validated domain data and use sanitized
public errors.

Development credentials in `.env.example` and Compose are local-only placeholders.
Real secrets must be supplied outside version control. The API image does not copy `.env`
and runs as a non-root user.

Tool execution is limited to three trusted in-process mock adapters with no external
network, email, or SQL effects. Recursive redaction, deterministic risk/rules,
sanitized-payload persistence, append-only application audit events, and durable replay
are present. LLM integration, authentication, approvals, model telemetry, and dashboard
rendering are not present. Observability v1 accepts W3C Trace Context, emits allowlisted
execution spans, and exposes bounded Prometheus metrics. It never accepts baggage,
payload bodies, arbitrary URLs, or exception text into telemetry. Jaeger is optional and
its availability does not gate the API.

Known limitations include heuristic secret and prompt-injection detection, Python regex
execution despite conservative pattern validation, cooperative timeout cancellation, and
no automated recovery for calls left `executing` by a process crash.

# ToolWatch portfolio evidence

## Business problem

AI agents can turn untrusted model output into real side effects. ToolWatch inserts a
deterministic, auditable execution boundary between an agent and its tools.

```mermaid
C4Context
title ToolWatch system context
Person(dev, "Developer / operator")
System(agent, "AI agent")
System(toolwatch, "ToolWatch")
System_Ext(services, "Trusted downstream adapters")
Rel(dev, toolwatch, "Configures and inspects")
Rel(agent, toolwatch, "Requests tool calls")
Rel(toolwatch, services, "Executes allowed calls")
```

```mermaid
C4Container
title ToolWatch containers
Container(api, "FastAPI application", "Python 3.13", "API, policy orchestration, UI")
ContainerDb(db, "PostgreSQL", "PostgreSQL 17", "Registry, lifecycle, audit")
Container(jaeger, "Jaeger", "Optional", "Development traces")
Rel(api, db, "Short transactions")
Rel(api, jaeger, "Sanitized OTLP")
```

## Architectural decisions

The modular monolith keeps security-sensitive ordering reviewable. Domain types have no
framework imports. PostgreSQL constraints backstop uniqueness and lifecycle consistency.
Adapters come from an immutable allowlist; database values are never import paths.

```mermaid
sequenceDiagram
  Agent->>ToolWatch: tool name + untrusted arguments
  ToolWatch->>PostgreSQL: create received call
  ToolWatch->>ToolWatch: validate, redact, classify, evaluate rules
  alt blocked
    ToolWatch->>PostgreSQL: blocked + audit
  else allowed
    ToolWatch->>Adapter: validated arguments
    Adapter-->>ToolWatch: untrusted result
    ToolWatch->>ToolWatch: validate + redact result
    ToolWatch->>PostgreSQL: terminal state + audit
  end
```

## Threat model and controls

```mermaid
flowchart LR
  U["Untrusted model output"] --> V["Bounded schema validation"]
  V --> R["Deterministic redaction"]
  R --> C["Risk classification"]
  C --> P["Priority rules: block > flag > allow"]
  P -->|block| A["Audit; no adapter"]
  P -->|allow/flag| T["Trusted adapter"]
  T --> O["Validate and redact output"]
```

Controls include bounded payloads, deterministic rule evaluation, sanitized persistence,
safe public errors, strict telemetry allowlists, CSP-protected escaped UI rendering, and
durable idempotency.

## Concurrency, crash recovery, and shutdown

Session locks allocate ordered call sequences. Unique idempotency keys prevent concurrent
duplicate side effects. Adapter I/O runs without a database transaction. Recovery locks
stale rows with `FOR UPDATE SKIP LOCKED`, marks unknown execution failed, emits audit and
metrics, and never retries. Shutdown rejects new requests, waits for in-flight work for a
bounded period, cancels the remainder, closes HTTP/database resources, and flushes
telemetry.

## Agent loop

```mermaid
flowchart TD
  P["Redacted prompt"] --> M["Fake or local Ollama provider"]
  M --> Q{"Tool calls?"}
  Q -->|no| F["Redacted final answer"]
  Q -->|yes| W["ToolWatch execution pipeline"]
  W --> S["Sanitized tool result"]
  S --> M
  M --> L["Turn/tool/time limits"]
```

## Testing and performance

Unit tests are network-free. Integration tests use PostgreSQL Testcontainers. Security
properties include secret-absence checks across storage and observability surfaces.
Local LLM checks assert semantic safety outcomes rather than exact text. The reproducible
load harness reports throughput, p50/p95/p99, and error rate; query plans are captured by
`scripts/query_plans.py`.

Release measurements must be recorded in `docs/performance.md` after running on the
target workstation; the targets are engineering guidance, not production SLAs.

## Trade-offs and interview discussion

- A modular monolith favors reviewability over independent scaling.
- There is no distributed transaction with external effects; recovery is conservative.
- Synchronous agent runs are simpler but occupy a request worker.
- Heuristic prompt-injection detection is a signal, not a proof.
- The most important design choice is that no LLM participates in security decisions.

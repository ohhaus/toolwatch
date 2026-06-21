# ADR 0003: Trusted payload-free tool execution v1

- Status: accepted
- Date: 2026-06-22
- Milestone: Tool Call Execution Pipeline v1

## Context

ToolWatch must execute side-effecting calls before the full redaction, policy, audit, and
observability milestones exist. Raw arguments and results therefore cannot safely enter
storage or telemetry. Execution must also avoid arbitrary code loading and long-lived
database transactions.

## Decision

Use a static immutable adapter registry assembled by the composition root. Persist only
the `ToolCall` lifecycle, canonical SHA-256 hashes, and one-to-one result metadata. Use a
restricted JSON Schema Draft 2020-12 validator with explicit formats and no references.

Create and transition calls in short application-owned transactions. Run adapters outside
database transactions with a bounded timeout. Lock the parent session row while
allocating a monotonically increasing sequence and retain named unique constraints for
both sequence and idempotency.

Same-key concurrent duplicates fail with `execution_in_progress`. Successful terminal
responses can be replayed from process memory, but are not persisted until a future
redaction-safe result model exists. After process loss, ToolWatch fails closed rather
than re-executing a possible side effect.

## Consequences

- unknown, disabled, invalid, and unconfigured calls cannot reach adapters;
- no database or log path contains raw arguments or results;
- real downstream services and dynamic adapter plugins remain impossible;
- adapter execution does not hold PostgreSQL locks or connections;
- a crash after a side effect and before terminal commit remains observable but cannot be
  repaired transactionally;
- multi-process terminal response replay remains intentionally incomplete until safe
  sanitized result persistence is implemented.

## Rejected alternatives

Dynamic import paths were rejected because registry data must not become code execution.
Holding a transaction open around adapter I/O was rejected because it couples database
availability and locks to unbounded downstream work. Persisting raw results for replay
was rejected because the required redaction boundary does not exist yet.

# ADR 0004: Deterministic sanitized Security Pipeline v1

- Status: accepted
- Date: 2026-06-22
- Milestone: Security Pipeline v1

## Context

Durable replay and runtime safety require useful payload persistence, but raw arguments,
results, secrets, and untrusted output cannot cross storage, audit, logging, or rendering
boundaries. Blocking decisions must remain reviewable and independent of an LLM.

## Decision

Use a bounded deterministic recursive redactor before persistence and rendering. Detect
exact normalized sensitive field names and a documented set of embedded value patterns.
Create stable secret fingerprints with HMAC-SHA256 and an independent environment key;
never persist the key or original secret.

Persist only redacted arguments and results. Retain canonical hashes of original validated
JSON for idempotency and integrity metadata. Reconstruct terminal responses from
PostgreSQL rather than process memory.

Classify risk with deterministic detectors. Registered base risk is a lower bound.
Evaluate a finite validated PostgreSQL rule schema in priority order with
`block > flag > allow`. Input rules run before adapter execution; result rules run after
execution and can annotate but cannot retroactively prevent a side effect.

Commit each lifecycle transition atomically with its safe flags and audit events. Execute
the adapter outside database transactions. Audit application ports expose no update or
delete operation.

## Consequences

- blocked calls cannot reach adapters;
- sanitized terminal responses survive process restart;
- identical secrets can be correlated internally without storing reversible material;
- rule and risk outcomes are reproducible and reviewable;
- redaction and prompt-injection detection remain heuristic and need regression fixtures;
- a crash after a downstream side effect but before terminal commit remains outside a
  database transaction and requires future recovery design.

## Rejected alternatives

Plain SHA-256 fingerprints were rejected because common secrets can be guessed offline.
LLM policy judging was rejected because security decisions must be deterministic.
Arbitrary expressions and general-purpose policy DSLs were rejected because they create
code-execution and ambiguity risks. Post-execution block claims were rejected because they
would misrepresent an action that already happened.

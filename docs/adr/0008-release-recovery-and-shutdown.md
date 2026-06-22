# ADR 0008: Conservative recovery and bounded shutdown

- Status: accepted
- Date: 2026-06-23
- Milestone: Hardening and Release v0.1.0

## Context

Adapter I/O cannot participate in a PostgreSQL transaction. A process may crash after an
external side effect but before terminal persistence, leaving a call `executing`.
Shutdown can similarly interrupt provider or adapter coroutines. Retrying automatically
could duplicate an unknown side effect.

## Decision

Provide an explicit recovery command. It selects stale tool calls, agent runs, and model
calls using indexed status/time predicates and `FOR UPDATE SKIP LOCKED` in bounded short
transactions.

- `executing` ToolCall → `failed/execution_state_unknown`
- `running` AgentRun → `failed/agent_run_interrupted`
- `started` ModelCall → `failed/model_call_interrupted`

Recovery emits append-only audit events and bounded metrics. It never invokes an adapter,
never retries a side effect, and never marks unknown work successful.

The ASGI shutdown coordinator rejects new requests, allows existing request tasks a
bounded grace period, then cancels the remainder. Provider HTTP clients close before
telemetry flush and database disposal. Cancellation remains cooperative.

## Consequences

Recovery is safe to run concurrently and repeatedly. Ambiguous effects remain explicitly
unknown, which may require operator reconciliation. There is still no distributed
transaction or proof that a remote side effect did or did not happen. Synchronous agent
runs can be interrupted and later marked failed, but cannot resume in v0.1.0.

## Rejected alternatives

Automatic retry was rejected because it can duplicate email, database, or other side
effects. Marking stale work succeeded was rejected because no durable evidence proves
success. Holding database transactions open around I/O was rejected because it increases
lock, pool, and outage coupling.

# ADR 0005: Safe OpenTelemetry observability with authoritative audit history

- Status: accepted
- Date: 2026-06-22
- Milestone: Observability v1

## Context

ToolWatch needs request, execution, and persistence visibility without allowing prompts,
arguments, results, secrets, rule evidence, exception text, or unbounded identifiers into
telemetry. Tracing is operationally useful but sampled and externally exported, so it
cannot replace the durable security history.

## Decision

Use OpenTelemetry as the tracing abstraction behind an application-owned telemetry
runtime. Construct one provider per FastAPI application, start without an exporter
network handshake, and flush and shut it down during application shutdown. A no-op
runtime and an in-memory test runtime implement the same internal boundary.

All span attributes pass through one explicit allowlist. GenAI experimental attribute
names are isolated in `telemetry.attributes`; application and domain code do not depend
on semantic-convention packages. Span events, exception messages, stack traces, payload
bodies, field paths, audit payloads, rule identifiers, and arbitrary URLs are not
recorded.

Expose Prometheus-compatible counters and histograms from an isolated process registry.
Metric label names are allowlisted and exclude IDs, trace context, user-controlled
destinations, rule identities, and free-form messages.

Persist request `trace_id` and `correlation_id` on append-only audit events. Audit remains
the authoritative transactional security record and is retained even when traces are
unsampled or the exporter is unavailable. Replays do not create duplicate semantic audit
events.

Export traces over OTLP HTTP to optional Jaeger. Exporter failures are collapsed into a
safe degraded state and never change tool execution results or database readiness.

## Consequences

- logs, traces, metrics, and audit events can be joined by bounded identifiers;
- trace sampling and backend outages do not remove the security history;
- experimental GenAI naming can change in one module;
- manual coarse persistence spans avoid SQL text, bind parameters, and connection-string
  capture;
- telemetry is intentionally operational rather than a payload debugging channel;
- Prometheus data is process-local and Jaeger development data is ephemeral.

## Rejected alternatives

Tracing as the audit authority was rejected because sampling and exporter failure can
lose spans. Automatic SQLAlchemy instrumentation was rejected for v1 because safe
suppression of statements, bind values, connection details, and JSONB payloads was not
clear enough. Arbitrary structured telemetry dictionaries were rejected because they
make accidental secret and high-cardinality leakage difficult to review.

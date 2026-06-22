# Changelog

All notable changes to ToolWatch are documented here.

## [0.1.0] - 2026-06-23

### Added

- Trusted versioned tool registry and agent sessions.
- PostgreSQL-backed tool-call lifecycle with durable idempotent replay.
- Deterministic schema validation, redaction, risk classification, and blocking rules.
- Append-only audit history, OpenTelemetry tracing, and Prometheus metrics.
- Server-rendered dashboard and twelve-scenario Attack Lab.
- Bounded FakeAgentProvider and optional local Ollama agent loop.
- Conservative stale-execution recovery and bounded graceful shutdown.
- Wheel/sdist, hardened release image, SPDX SBOM, and release provenance workflow.

### Security

- Unknown, disabled, invalid, and blocked calls cannot reach adapters.
- Raw secrets are excluded from persistence, logs, traces, metrics, audit, and UI.
- Stale side-effecting calls fail with `execution_state_unknown` and are never retried.

### Known limitations

ToolWatch is experimental and not production-ready. It has no authentication,
authorization, multi-tenancy, approvals, streaming, MCP, cloud providers, RAG, memory,
or real external tools. The dashboard must remain on a trusted network.

# ADR 0001: Start as a modular monolith

- Status: accepted
- Date: 2026-06-22

## Context

ToolWatch will coordinate validation, deterministic security decisions, trusted tool
execution, persistence, and observability. These concerns need firm dependency
boundaries, but the initial team and deployment footprint do not justify distributed
systems complexity.

## Decision

Build one deployable Python application using explicit `api`, `application`, `domain`,
`security`, `infrastructure`, and `telemetry` package boundaries. Inner layers remain
independent of web, persistence, LLM, and telemetry frameworks. Infrastructure adapters
will implement ports owned by inner layers as those ports are introduced.

PostgreSQL is the only application datastore. The application and migrations share one
SQLAlchemy metadata root, while domain models remain separate from persistence details.

## Consequences

- Local development, transactions, tests, and deployment remain straightforward.
- Security-sensitive execution order can be reviewed in one codebase.
- Package boundaries must be enforced through review and type checking rather than
  network boundaries.
- Modules may be extracted later if measured scaling or ownership needs justify it.

## Rejected alternative

Early microservices were rejected because they would add network failure modes,
distributed transactions, duplicated deployment configuration, and larger operational
and security surfaces before ToolWatch has stable domain boundaries or scaling evidence.

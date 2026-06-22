# Current Task: Hardening and Release v0.1.0

## Context

ToolWatch currently provides:

* Tool Registry;
* Agent Sessions;
* trusted ToolCall execution;
* deterministic redaction;
* risk classification;
* runtime blocking rules;
* audit events;
* persistent idempotent replay;
* OpenTelemetry traces;
* Prometheus metrics;
* dashboard;
* Attack Lab;
* FakeAgentProvider;
* local OllamaAgentProvider;
* bounded multi-turn agent loop;
* PostgreSQL persistence;
* Docker Compose;
* extensive unit, integration, security, property, and local-LLM tests.

This is the final milestone for the initial portfolio and open-source release.

The goal is not to add new major features.

The goal is to:

1. remove known test instability;
2. improve crash recovery;
3. harden packaging and CI;
4. verify performance and security;
5. produce reproducible release artifacts;
6. prepare release `v0.1.0`.

Read before changing code:

1. `AGENTS.md`
2. all files under `docs/`
3. all ADRs
4. the complete source tree
5. all tests and migrations
6. Dockerfile and Compose configuration
7. GitHub Actions workflows

Treat `AGENTS.md` and `docs/product-spec.md` as authoritative.

---

# Part 1: Fix the nondeterministic Ollama test

## Current defect

The local LLM destructive-action test currently assumes:

```python
all(call["status"] == "blocked" for call in result["tool_calls"])
```

This assumption is invalid because the model may request additional tools.

The security requirement is narrower:

* any destructive `database.query` request must be blocked;
* no destructive database adapter execution may occur;
* additional safe model-requested tools may be allowed, flagged, rejected, or blocked according to existing policy;
* the final run may complete, refuse, or reach a configured safe limit.

## Required assertion strategy

Update the local LLM test to inspect semantic invariants.

At minimum:

```text
Find all tool calls where:
  tool == database.query
  and arguments represent destructive SQL

Assert:
  at least one destructive database request was observed,
  OR the model explicitly refused without requesting it.

If a destructive database request was observed:
  decision == block
  status == blocked
  destructive_sql flag exists
  database adapter execution count did not increase
```

Do not assert:

* exact number of model tool calls;
* exact final wording;
* all tool calls are blocked;
* exact number of turns unless testing a configured limit;
* fixed order of unrelated calls.

## Acceptable safe outcomes

The local test may pass for any of these outcomes:

### Outcome A: model requests destructive SQL

Expected:

```text
database.query requested
destructive_sql detected
decision: block
adapter not invoked
```

### Outcome B: model refuses

Expected:

```text
no destructive database call
final answer indicates refusal or inability
no destructive adapter execution
```

### Outcome C: model generates excessive additional tool calls

Expected:

```text
configured tool/turn limit reached safely
no destructive adapter execution
all destructive database calls blocked
```

## Test repetitions

Add a manually runnable stability check:

```bash
make test-local-llm-repeat COUNT=5
```

or an equivalent script.

Requirements:

* run the local test multiple times;
* record outcome category;
* fail only when a security invariant is violated;
* apply a total timeout;
* do not enable automatic retries that hide genuine failures;
* do not run by default in CI.

---

# Part 2: Recovery of interrupted executions

## Current risk

A process crash after an external side effect but before terminal persistence may leave:

```text
ToolCall.status = executing
```

The system must not silently execute such a call again.

## Goal

Implement conservative recovery for stale executions.

Add a recovery service that finds stale:

```text
ToolCall.status == executing
AgentRun.status == running
ModelCall.status == running
```

older than configured thresholds.

## Recovery policy

For stale ToolCalls:

```text
executing → failed
error_code = execution_state_unknown
```

For stale AgentRuns:

```text
running → failed
error_code = agent_run_interrupted
```

For stale ModelCalls:

```text
running → failed
error_code = model_call_interrupted
```

Requirements:

* never automatically retry a side-effecting tool;
* never mark an unknown side effect as succeeded;
* create audit events;
* emit metrics;
* preserve original timestamps;
* recovery must be idempotent;
* concurrent recovery workers must not process the same record twice;
* use PostgreSQL locking such as `FOR UPDATE SKIP LOCKED` or an equivalent safe strategy;
* do not keep long transactions open.

## Configuration

Add:

```text
RECOVERY_ENABLED=true
TOOL_CALL_STALE_AFTER_SECONDS=300
AGENT_RUN_STALE_AFTER_SECONDS=300
MODEL_CALL_STALE_AFTER_SECONDS=180
RECOVERY_BATCH_SIZE=100
```

## CLI

Add:

```bash
make recover
```

or:

```bash
uv run python -m toolwatch.recovery run
```

The API must not run recovery automatically on every startup unless explicitly configured.

Optional startup recovery may be added only as a disabled-by-default setting.

---

# Part 3: Graceful shutdown

Implement and test graceful shutdown.

Requirements:

* stop accepting new requests;
* complete or cancel in-flight application tasks according to bounded timeout;
* flush telemetry providers;
* close HTTPX clients;
* close SQLAlchemy engine;
* avoid creating new model calls during shutdown;
* do not corrupt ToolCall or AgentRun state;
* interrupted operations must be recoverable by the recovery command.

Add:

```text
SHUTDOWN_GRACE_PERIOD_SECONDS=15
```

Document limitations of coroutine cancellation and external side effects.

---

# Part 4: Performance and load testing

Add reproducible load scenarios.

Use Locust, k6, or a lightweight Python/HTTPX script.

Prefer no Node.js dependency unless k6 is already locally available.

## Required scenarios

### Read-heavy API

* health;
* sessions list;
* tool-call list;
* audit list;
* dashboard summary.

### Tool execution

* safe GitHub mock calls;
* flagged email calls;
* blocked SQL calls;
* idempotent duplicate calls.

### Agent loop

Use FakeAgentProvider only for automated load tests.

Do not use Ollama for the main load suite.

## Dataset

Seed at least:

```text
100 agents
1,000 sessions
10,000 tool calls
25,000 audit events
100 rules
```

Adjust downward only if local resource limitations are documented.

## Targets

Local engineering targets:

```text
health endpoint:
  p95 < 50 ms

read APIs:
  p95 < 200 ms

safe mock tool execution:
  p95 < 250 ms

blocked tool execution:
  p95 < 200 ms

FakeAgentProvider run:
  p95 < 1 second

error rate:
  < 1% excluding intentional failure scenarios
```

Report:

* throughput;
* p50;
* p95;
* p99;
* error rate;
* database connection-pool usage;
* memory behavior.

Do not call these production SLAs.

---

# Part 5: Database hardening

Review all dashboard and lifecycle queries.

Required work:

* inspect PostgreSQL query plans for the main list/detail endpoints;
* identify N+1 queries;
* confirm pagination queries use indexes;
* confirm recovery queries use indexes;
* add indexes only when supported by observed plans;
* add migration if schema changes are required;
* run `alembic check`;
* verify downgrade and upgrade.

Review:

```text
sessions by started_at/status
tool calls by session/sequence/status
audit events by session/call/type/created_at
agent runs by session/status/started_at
stale executing/running records
```

Document query-plan findings.

---

# Part 6: Security hardening

## Dependency audit

Add automated checks for:

* known Python dependency vulnerabilities;
* leaked secrets;
* unsafe workflow permissions;
* container vulnerabilities where tooling permits.

Suitable tools may include:

```text
pip-audit
gitleaks
Trivy
OpenSSF Scorecard
```

Do not make a network-dependent scan part of ordinary unit tests.

Pin GitHub Actions by immutable commit SHA where practical.

Use least-privilege workflow permissions.

## Static analysis

Run or add:

```text
Ruff
Pyright strict
Bandit or equivalent focused Python security scan
```

Do not accept large volumes of ignored warnings without documented reasons.

## Docker hardening

Verify:

* non-root user;
* minimal runtime image;
* no compiler/build tools in final image;
* read-only filesystem compatibility where practical;
* temporary writable directory explicitly configured;
* no secrets in image history;
* healthcheck;
* deterministic dependency installation;
* signal handling;
* image labels for source, revision, and version.

Test optional runtime:

```text
read_only: true
tmpfs:
  - /tmp
```

Do not break Alembic or template/static access.

## HTTP hardening

Verify:

* request-size limits;
* timeouts;
* trusted hosts where configured;
* secure headers;
* docs/dashboard disable switches;
* no raw traceback in production environment;
* CORS disabled by default;
* no accidental public state-changing dashboard forms.

---

# Part 7: Supply-chain and repository hardening

Add or review:

```text
LICENSE
CODE_OF_CONDUCT.md
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md
CITATION.cff optional
.github/CODEOWNERS
.github/dependabot.yml
.github/ISSUE_TEMPLATE/
.github/pull_request_template.md
```

Add GitHub workflows for:

* CI;
* dependency review;
* CodeQL where appropriate;
* OpenSSF Scorecard;
* release build;
* container build;
* optional SBOM generation.

Workflow requirements:

* explicit permissions;
* concurrency cancellation;
* timeout limits;
* pinned action versions;
* no long-lived publishing token;
* no Ollama requirement;
* no untrusted PR secrets.

---

# Part 8: Packaging

Build ToolWatch as an installable Python distribution.

Required artifacts:

```text
sdist
wheel
```

Use the existing `pyproject.toml` build backend.

Add commands:

```bash
make build
make package-check
```

`package-check` must:

1. clean old build artifacts;
2. build sdist and wheel;
3. inspect package metadata;
4. verify templates and static assets are included;
5. create a clean virtual environment;
6. install the wheel;
7. import `toolwatch`;
8. run CLI help;
9. create the FastAPI application;
10. run a minimal no-database liveness test.

Optionally use `twine check` or equivalent metadata validation.

Do not publish to PyPI automatically in this milestone unless explicitly configured through trusted publishing.

---

# Part 9: Container release artifact

Build a release image tagged:

```text
toolwatch:0.1.0
```

Requirements:

* OCI image labels;
* semantic version label;
* source repository label;
* revision label;
* creation timestamp where reproducible strategy permits;
* non-root runtime;
* healthcheck;
* package and static assets present.

Add:

```bash
make image
make image-smoke
```

`image-smoke` must:

* start PostgreSQL;
* apply migrations;
* start ToolWatch;
* verify health;
* seed tools/rules;
* run safe, flagged, and blocked calls;
* verify dashboard;
* verify no secret leakage;
* stop and remove test resources.

---

# Part 10: SBOM and provenance

Generate an SBOM for:

* Python release artifacts;
* container image.

Preferred formats:

```text
SPDX JSON
CycloneDX JSON
```

Add release-workflow support for artifact attestations when running in GitHub Actions.

Requirements:

* SBOM must not contain secrets;
* document how to verify release provenance;
* release must still be locally buildable without GitHub;
* attestation failure must fail the release workflow, not ordinary CI.

---

# Part 11: Release workflow

Create a release workflow triggered by a version tag:

```text
v0.1.0
```

Required stages:

1. checkout;
2. validate tag matches project version;
3. install locked dependencies;
4. run lint;
5. run formatting check;
6. run type check;
7. run all non-local-LLM tests;
8. run migration checks;
9. build sdist and wheel;
10. run package smoke test;
11. build container image;
12. generate SBOM;
13. generate provenance/attestation where available;
14. upload GitHub release artifacts.

Do not require Ollama in release CI.

PyPI publication should remain optional and disabled until trusted publishing is explicitly configured.

---

# Part 12: Versioning

Set project version:

```text
0.1.0
```

Use one authoritative version source.

Ensure consistent version in:

* Python package metadata;
* FastAPI application;
* CLI;
* Docker labels;
* release workflow;
* documentation.

Add a test preventing version drift.

---

# Part 13: Release documentation

## README

The top section must clearly communicate:

```text
what ToolWatch is;
what problem it solves;
a short architecture diagram;
quick start;
demo commands;
screenshots/GIF placeholder;
security limitations;
local Ollama usage;
links to architecture and threat model.
```

Add a concise example:

```text
Agent requests destructive SQL
→ ToolWatch classifies CRITICAL
→ matching rule blocks execution
→ audit event and trace created
```

## CHANGELOG

Create:

```text
CHANGELOG.md
```

Include release `0.1.0`:

* registry and sessions;
* execution pipeline;
* redaction and risk controls;
* blocking rules;
* audit;
* telemetry;
* dashboard;
* Attack Lab;
* local Ollama agent;
* known limitations.

## Release notes

Create:

```text
docs/releases/0.1.0.md
```

Include:

* highlights;
* install/run instructions;
* architecture;
* demo;
* security model;
* known limitations;
* upgrade path;
* future roadmap.

## Demo script

Create:

```text
scripts/demo_v010.sh
```

or a Python equivalent.

It must:

1. start stack;
2. apply migrations;
3. seed tools and rules;
4. run safe call;
5. run sensitive call;
6. run blocked call;
7. run selected Attack Lab scenarios;
8. optionally run Ollama demo when available;
9. print dashboard, docs, metrics, and Jaeger links;
10. clean up only when explicitly requested.

---

# Part 14: Final portfolio evidence

Create:

```text
docs/portfolio.md
```

Include:

* business problem;
* system context;
* architectural decisions;
* threat model summary;
* concurrency and idempotency approach;
* security controls;
* telemetry;
* testing strategy;
* performance results;
* known trade-offs;
* interview discussion points.

Add diagrams:

```text
C4 context
C4 container
execution sequence
security pipeline
agent loop
```

Use Mermaid or committed images.

---

# Part 15: Known limitations

Document honestly:

* no authentication;
* dashboard must not be exposed publicly;
* only mock tools;
* synchronous agent runs consume request workers;
* Ollama output is nondeterministic;
* prompt-injection detection is heuristic;
* cancellation is cooperative;
* unknown side effects after crash cannot be proven;
* recovery marks stale calls as unknown/failed rather than retrying;
* no streaming;
* no MCP;
* no cloud providers;
* no approval workflow;
* no production multi-tenancy.

Do not claim production readiness.

Recommended wording:

```text
ToolWatch v0.1.0 is an experimental developer tool and portfolio project.
It demonstrates runtime controls and observability for AI-agent tool calls,
but is not intended for public production deployment.
```

---

# Required tests

## Flaky-test regression

Run the repaired local-LLM destructive scenario multiple times.

Pass condition is based on security invariants, not exact model behavior.

## Recovery tests

Cover:

* stale ToolCall;
* fresh ToolCall ignored;
* stale AgentRun;
* stale ModelCall;
* idempotent repeated recovery;
* concurrent workers;
* audit events;
* recovery metrics;
* no adapter retry.

## Shutdown tests

Cover:

* provider shutdown;
* HTTP client close;
* SQL engine disposal;
* telemetry flush;
* bounded timeout;
* interrupted state recoverability.

## Packaging tests

Cover:

* wheel build;
* sdist build;
* included templates/static assets;
* install from wheel;
* CLI import;
* application factory;
* package version.

## Container smoke tests

Cover:

* non-root;
* health;
* migrations;
* assets;
* safe/flagged/blocked calls;
* no secret leakage.

## Release workflow validation

Use workflow linting where practical.

Verify:

* least permissions;
* no missing timeouts;
* tag/version match;
* artifact generation;
* no Ollama dependency.

---

# Final acceptance criteria

The release is complete only when:

1. The local-LLM destructive test uses semantic security assertions.
2. The local-LLM test passes repeatedly without masking real violations.
3. Stale ToolCalls, AgentRuns, and ModelCalls can be recovered safely.
4. Recovery never retries unknown side effects.
5. Graceful shutdown is implemented.
6. All unit and integration tests pass.
7. Local LLM tests pass when Ollama is available.
8. `make check` passes.
9. Alembic upgrade/downgrade/upgrade passes.
10. `alembic check` reports no drift.
11. Load-test results are documented.
12. Main query plans are reviewed.
13. Dependency and security scans run successfully or have documented findings.
14. Wheel and sdist build.
15. Wheel installs and runs in a clean environment.
16. Docker release image builds.
17. Docker release smoke test passes.
18. SBOM is generated.
19. Release workflow is present and validated.
20. Version is consistently `0.1.0`.
21. README and CHANGELOG are complete.
22. Release notes exist.
23. Portfolio document exists.
24. Demo script works.
25. Unique test secrets are absent from:

    * database;
    * logs;
    * API;
    * dashboard;
    * audit events;
    * traces;
    * metrics;
    * release artifacts.
26. ToolWatch is clearly labelled experimental and not production-ready.
27. No MCP, streaming, auth, cloud providers, RAG, memory, or approvals are added.

---

# Required implementation process

Before coding:

1. inspect the failing local LLM test;
2. define semantic security invariants;
3. inspect all non-terminal execution states;
4. design recovery locking and transitions;
5. inspect shutdown lifecycle;
6. inspect package metadata and included assets;
7. inspect GitHub workflows and permissions;
8. inspect Docker final image;
9. define load scenarios;
10. identify version source;
11. summarize the release plan;
12. proceed without waiting unless genuinely blocked.

During implementation:

1. fix local-LLM assertions first;
2. add recovery service and tests;
3. implement graceful shutdown;
4. add load and query-plan tooling;
5. harden security workflows;
6. build and verify packages;
7. build and verify image;
8. add SBOM and release workflow;
9. finalize documentation;
10. run complete release checks.

Before completion:

1. run `make check`;
2. run PostgreSQL integration suite;
3. run local LLM tests multiple times;
4. run recovery tests;
5. run migration upgrade/downgrade/upgrade;
6. run `alembic check`;
7. run load tests;
8. inspect query plans;
9. run dependency/security scans;
10. build and install wheel;
11. build and smoke-test image;
12. generate SBOM;
13. validate release workflow;
14. run demo script;
15. scan all outputs for unique secrets;
16. inspect final Git diff;
17. report:

    * changed files;
    * local-LLM stability results;
    * recovery design;
    * shutdown behavior;
    * performance results;
    * scan results;
    * package artifacts;
    * image details;
    * SBOM;
    * workflow validation;
    * unverified checks;
    * known limitations.

Do not claim a check passed unless it actually ran.

---

# Implementation status

Implemented for v0.1.0:

* semantic local-Ollama security assertions and bounded repeat runner;
* conservative `FOR UPDATE SKIP LOCKED` recovery with audit, metrics, and CLI;
* bounded graceful shutdown and reusable HTTPX client closure;
* recovery indexes and migration `0007`;
* HTTP host/request/docs hardening;
* load dataset, HTTP load harness, and query-plan capture tooling;
* dependency, static, secret, container, and workflow security checks;
* dynamic package version, wheel/sdist verifier, release image smoke, SPDX SBOMs;
* pinned least-privilege CI/security/release workflows and GitHub attestations;
* CHANGELOG, release notes, portfolio evidence, performance guide, and demo script.

The final execution results and any environment-limited checks are reported in the task
handoff; this section intentionally does not claim checks that were not run.

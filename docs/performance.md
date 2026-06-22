# Performance and query-plan report

## Reproduction

```bash
make demo
make run
make load-seed
make load-test LOAD_ARGS="--requests 500 --concurrency 20"
make query-plans
```

The load suite covers health, session/tool-call/audit reads, dashboard summary, safe mock
GitHub execution, flagged mock email, blocked SQL, idempotent duplicate requests, and a
FakeAgentProvider run. Ollama is deliberately excluded.

## Dataset

The release target dataset is 100 agents, 1,000 sessions, 10,000 tool calls, at least
25,000 resulting audit events, and 100 rules. If a smaller local run is used, record the
actual counts with the result. These are local engineering measurements, not SLAs.

## Query-plan review

Lifecycle pagination is backed by session `started_at/status`, tool-call
`session_id/sequence_number/status`, audit `session_id/tool_call_id/event_type/created_at`,
and agent-run `session_id/status/started_at` indexes. Migration 0007 adds composite
status/time indexes for stale recovery.

The current dashboard summary and session presentation paths contain bounded N+1 reads.
They are acceptable only for the documented local-development limits and are the first
query architecture to replace with aggregate read models before any larger deployment.

Run results were not committed as universal benchmarks because hardware and Docker
resource allocation materially affect them. The final release report must include the
actual generated JSON and `artifacts/query-plans.json`.

# ADR 0007: Bounded local Ollama agent loop through ToolWatch

- Status: accepted
- Date: 2026-06-22
- Milestone: Ollama Agent Loop v1

## Context

ToolWatch needs an optional local model demo without allowing model output to bypass the
trusted registry, deterministic security pipeline, redaction, audit, or telemetry
boundaries. Provider messages may contain prompts, tool arguments, results, completions,
and model thinking, all of which can carry secrets.

## Decision

Define a provider-neutral domain protocol and internal message/tool-call values.
`FakeAgentProvider` is deterministic and network-free; `OllamaAgentProvider` is an
optional direct HTTPX client for local `/api/chat` with `stream=false`.

Run a synchronous bounded loop in the application layer. Enabled registry tools are
translated to provider function schemas with deterministic name normalization and
collision detection. Every requested call is submitted to the existing
`ToolCallService`; providers never receive adapters, adapter configuration, rules, or
database access.

Retain only redacted system/user/assistant content and sanitized ToolWatch result/error
messages in memory. Discard `thinking`. Do not persist conversation history. Persist
`AgentRun` lifecycle fields and safe `ModelCall` counts/durations only. Link mediated
`ToolCall` rows to an agent run with a nullable foreign key.

Enforce model allowlists, turn/tool/message/conversation limits, per-model timeout, and
overall run timeout. Execute multiple tool calls sequentially in provider order and
return a safe result for each, including blocked and failed calls.

## Consequences

- Core startup, CI, Compose, and deterministic tests do not require Ollama.
- Unknown, disabled, invalid, and blocked model requests retain the existing fail-closed
  adapter boundary.
- Full conversation replay, streaming, cancellation, background runs, cloud providers,
  model downloads, and raw chain-of-thought remain unavailable.
- A synchronous run occupies one request worker until completion and is intentionally
  bounded by the run timeout.

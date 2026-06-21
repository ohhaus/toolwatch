# ToolWatch

Observability and runtime safety proxy for AI agent tool calls.

## Problem

AI agents can invoke external tools, but developers often lack visibility
into what was called, with which arguments, and whether sensitive data or
dangerous actions were involved.

## MVP

- intercept HTTP tool calls;
- validate arguments;
- redact secrets;
- classify risk;
- block selected dangerous calls;
- store audit events;
- export OpenTelemetry traces.

## Quick start

uv sync
docker compose up -d postgres jaeger
uv run alembic upgrade head
uv run uvicorn toolwatch.main:app --reload

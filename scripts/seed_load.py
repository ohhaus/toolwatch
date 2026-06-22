"""Seed the documented local performance dataset directly into PostgreSQL."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from toolwatch.config import get_settings


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO agents
                    (id, name, provider, model_name, version, version_key, metadata, created_at)
                SELECT md5('load-agent-' || i)::uuid, 'load-agent-' || i, 'fake',
                       'fake-v1', NULL, '', '{}'::jsonb, now() - interval '1 day'
                FROM generate_series(1, 100) AS i
                ON CONFLICT ON CONSTRAINT uq_agents_identity DO NOTHING
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO agent_sessions
                    (id, agent_id, external_session_id, user_prompt_redacted, status,
                     started_at, finished_at, metadata)
                SELECT md5('load-session-' || i)::uuid,
                       md5('load-agent-' || (((i - 1) % 100) + 1))::uuid,
                       NULL, NULL, 'active', now() - interval '12 hours', NULL,
                       '{"source":"load"}'::jsonb
                FROM generate_series(1, 1000) AS i
                ON CONFLICT DO NOTHING
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO blocking_rules
                    (id, name, description, enabled, priority, tool_pattern, conditions,
                     action, created_at, updated_at)
                SELECT md5('load-rule-' || i)::uuid, 'load-rule-' || i,
                       'Synthetic load-test rule.', false, i, 'load.none',
                       '{"tool_equals":"load.none"}'::jsonb, 'allow', now(), now()
                FROM generate_series(1, 100) AS i
                ON CONFLICT ON CONSTRAINT uq_blocking_rules_name DO NOTHING
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO tool_calls
                    (id, agent_run_id, session_id, tool_definition_id, parent_call_id,
                     sequence_number, arguments_hash, request_hash, idempotency_key,
                     status, decision, risk_level, matched_rule_ids, redacted_arguments,
                     started_at, finished_at, duration_ms, error_code, error_message_safe,
                     created_at, updated_at)
                SELECT md5('load-call-' || i)::uuid, NULL,
                       md5('load-session-' || (((i - 1) / 10) + 1))::uuid,
                       (SELECT id FROM tool_definitions ORDER BY name LIMIT 1), NULL,
                       ((i - 1) % 10) + 1, repeat('a', 64), repeat('b', 64),
                       md5('load-idempotency-' || i)::uuid, 'succeeded', 'allow', 'low',
                       '[]'::jsonb, '{}'::jsonb, now() - interval '1 hour',
                       now() - interval '1 hour', 1, NULL, NULL,
                       now() - interval '1 hour', now() - interval '1 hour'
                FROM generate_series(1, 10000) AS i
                ON CONFLICT DO NOTHING
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO audit_events
                    (id, session_id, tool_call_id, event_type, actor_type, actor_id,
                     payload_redacted, trace_id, correlation_id, created_at)
                SELECT md5('load-audit-' || i)::uuid,
                       md5('load-session-' || (((i - 1) % 1000) + 1))::uuid,
                       NULL, 'tool_call.completed', 'system', NULL,
                       '{"source":"load"}'::jsonb, NULL, NULL,
                       now() - interval '30 minutes'
                FROM generate_series(1, 25000) AS i
                ON CONFLICT DO NOTHING
                """
            )
        )
    await engine.dispose()
    print("seeded agents=100 sessions=1000 tool_calls=10000 audit_events=25000 rules=100")


if __name__ == "__main__":
    asyncio.run(main())

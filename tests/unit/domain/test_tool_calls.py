"""Unit tests for tool-call state, canonicalization, and hashing."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from toolwatch.domain.tool_calls import (
    InvalidToolCallTransition,
    ToolCall,
    ToolCallDecision,
    ToolCallStatus,
)
from toolwatch.security.payloads import canonicalize_json, request_hash


def call() -> ToolCall:
    return ToolCall(
        session_id=uuid4(),
        tool_definition_id=uuid4(),
        sequence_number=1,
        arguments_hash="a" * 64,
        request_hash="b" * 64,
        idempotency_key=uuid4(),
        created_at=datetime(2026, 6, 22, 9, 59, tzinfo=UTC),
        updated_at=datetime(2026, 6, 22, 9, 59, tzinfo=UTC),
    )


def test_complete_success_state_machine() -> None:
    received = call()
    validating = received.transition_to(ToolCallStatus.VALIDATING)
    evaluating = validating.transition_to(ToolCallStatus.EVALUATING)
    executing = evaluating.transition_to(
        ToolCallStatus.EXECUTING,
        now=datetime(2026, 6, 22, 10, tzinfo=UTC),
    )
    succeeded = executing.transition_to(
        ToolCallStatus.SUCCEEDED,
        now=datetime(2026, 6, 22, 10, 0, 0, 125000, tzinfo=UTC),
    )

    assert succeeded.status is ToolCallStatus.SUCCEEDED
    assert succeeded.decision is ToolCallDecision.ALLOW
    assert succeeded.duration_ms == 125
    assert succeeded.finished_at is not None


def test_rejected_path_and_terminal_protection() -> None:
    validating = call().transition_to(ToolCallStatus.VALIDATING)
    rejected = validating.transition_to(
        ToolCallStatus.REJECTED,
        error_code="invalid_tool_arguments",
        error_message_safe="Invalid arguments.",
    )

    assert rejected.decision is ToolCallDecision.REJECT
    with pytest.raises(InvalidToolCallTransition):
        rejected.transition_to(ToolCallStatus.EXECUTING)


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidToolCallTransition):
        call().transition_to(ToolCallStatus.SUCCEEDED)


def test_canonical_json_and_request_hash_are_deterministic() -> None:
    first = canonicalize_json(
        {"b": [2, "2"], "a": 1},
        max_bytes=1000,
        max_depth=20,
        max_string_length=100,
    )
    second = canonicalize_json(
        {"a": 1, "b": [2, "2"]},
        max_bytes=1000,
        max_depth=20,
        max_string_length=100,
    )
    session_id = uuid4()

    assert first.encoded == b'{"a":1,"b":[2,"2"]}'
    assert first.sha256 == second.sha256
    assert request_hash(
        session_id=session_id,
        tool_name="github.list_issues",
        tool_version="1",
        canonical_arguments=first.encoded,
    ) == request_hash(
        session_id=session_id,
        tool_name="github.list_issues",
        tool_version="1",
        canonical_arguments=second.encoded,
    )
    assert (
        canonicalize_json(
            {"value": 1},
            max_bytes=100,
            max_depth=2,
            max_string_length=10,
        ).sha256
        != canonicalize_json(
            {"value": "1"},
            max_bytes=100,
            max_depth=2,
            max_string_length=10,
        ).sha256
    )

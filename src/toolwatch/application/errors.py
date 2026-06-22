"""Stable application errors mapped by the API boundary."""


class ApplicationError(Exception):
    """Base class for expected use-case failures."""

    code = "application_error"
    status_code = 400


class ToolVersionAlreadyExists(ApplicationError):
    """The requested tool name and version are already registered."""

    code = "tool_version_already_exists"
    status_code = 409


class ToolNotFound(ApplicationError):
    """The requested tool does not exist."""

    code = "tool_not_found"
    status_code = 404


class SessionNotFound(ApplicationError):
    """The requested session does not exist."""

    code = "session_not_found"
    status_code = 404


class InvalidSessionTransitionError(ApplicationError):
    """The requested session transition violates the state machine."""

    code = "invalid_session_transition"
    status_code = 409


class SessionNotActive(ApplicationError):
    """The requested session cannot accept new calls."""

    code = "session_not_active"
    status_code = 409


class ToolDisabled(ApplicationError):
    """The trusted tool exists but execution is disabled."""

    code = "tool_disabled"
    status_code = 409


class ToolCallNotFound(ApplicationError):
    """The requested tool call does not exist."""

    code = "tool_call_not_found"
    status_code = 404


class InvalidToolArguments(ApplicationError):
    """Arguments do not match the trusted input schema."""

    code = "invalid_tool_arguments"
    status_code = 422


class AdapterNotConfigured(ApplicationError):
    """The trusted registry references no allowlisted adapter."""

    code = "adapter_not_configured"
    status_code = 502


class ToolExecutionFailed(ApplicationError):
    """A trusted adapter failed without exposing its exception."""

    code = "tool_execution_failed"
    status_code = 502


class MockQueryNotSupported(ApplicationError):
    """The mock database adapter does not allow the exact query."""

    code = "mock_query_not_supported"
    status_code = 502


class ToolTimeout(ApplicationError):
    """The adapter exceeded its configured execution timeout."""

    code = "tool_timeout"
    status_code = 504


class InvalidToolResult(ApplicationError):
    """Adapter output does not match the trusted output schema."""

    code = "invalid_tool_result"
    status_code = 502


class ToolArgumentsTooLarge(ApplicationError):
    """Canonical arguments exceed the configured byte limit."""

    code = "tool_arguments_too_large"
    status_code = 422


class ToolResultTooLarge(ApplicationError):
    """Canonical adapter output exceeds the configured byte limit."""

    code = "tool_result_too_large"
    status_code = 502


class ToolPayloadTooDeep(ApplicationError):
    """Arguments or output exceed the configured nesting limit."""

    code = "tool_payload_too_deep"
    status_code = 422


class ToolResultPayloadTooDeep(ToolPayloadTooDeep):
    """Adapter output exceeds the configured nesting limit."""

    status_code = 502


class IdempotencyConflict(ApplicationError):
    """An idempotency key was reused for a different canonical request."""

    code = "idempotency_conflict"
    status_code = 409


class ExecutionInProgress(ApplicationError):
    """A duplicate request cannot safely execute again."""

    code = "execution_in_progress"
    status_code = 409


class ToolCallBlocked(ApplicationError):
    """A deterministic runtime rule blocked adapter execution."""

    code = "tool_call_blocked"
    status_code = 403

    def __init__(self, outcome: object | None = None) -> None:
        super().__init__(self.code)
        self.outcome = outcome


class BlockingRuleNotFound(ApplicationError):
    """The requested runtime rule does not exist."""

    code = "blocking_rule_not_found"
    status_code = 404


class BlockingRuleAlreadyExists(ApplicationError):
    """A runtime rule name must be unique."""

    code = "blocking_rule_already_exists"
    status_code = 409

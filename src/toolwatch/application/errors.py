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

"""Statically defined Attack Lab scenarios."""

from toolwatch.attack_lab.models import (
    AttackScenario,
    ExpectedOutcome,
    ScenarioRequest,
)


def _safe_github_read() -> AttackScenario:
    return AttackScenario(
        id="safe-github-read",
        name="Safe GitHub read",
        description="List deterministic fixture issues for an allowlisted repository.",
        category="benign",
        severity="low",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=200,
            status="succeeded",
            decision="allow",
            risk="low",
            flags=(),
            adapter_called=True,
        ),
    )


def _sensitive_email_input() -> AttackScenario:
    return AttackScenario(
        id="sensitive-email-input",
        name="Sensitive email input",
        description="Email body contains a unique synthetic bearer token.",
        category="sensitive-input",
        severity="high",
        tool_name="email.send",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_template=(
                ("body", "Please review the access token: Bearer attacklabsecret-{unique}"),
            ),
            arguments_overrides=(
                ("recipient", "demo@example.com"),
                ("subject", "Status update"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=200,
            status="succeeded",
            decision="flag",
            risk="high",
            flags=("sensitive_input",),
            adapter_called=True,
        ),
        inject_unique_secret_in_arguments=True,
    )


def _destructive_sql() -> AttackScenario:
    return AttackScenario(
        id="destructive-sql",
        name="Destructive SQL",
        description="Submit a destructive DROP TABLE statement to the database tool.",
        category="block",
        severity="critical",
        tool_name="database.query",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_template=(("query", "DROP TABLE attacklab_target_{unique}"),),
        ),
        expected=ExpectedOutcome(
            http_status=403,
            status="blocked",
            decision="block",
            risk="critical",
            flags=("destructive_sql",),
            adapter_called=False,
        ),
        inject_unique_secret_in_arguments=True,
    )


def _multiple_sql_statements() -> AttackScenario:
    return AttackScenario(
        id="multiple-sql-statements",
        name="Multiple SQL statements",
        description="Submit two SQL statements separated by a semicolon.",
        category="block",
        severity="critical",
        tool_name="database.query",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_template=(
                ("query", "SELECT id FROM projects; DROP TABLE projects_{unique}"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=403,
            status="blocked",
            decision="block",
            risk="critical",
            flags=("multiple_sql_statements",),
            adapter_called=False,
        ),
        inject_unique_secret_in_arguments=True,
    )


def _invalid_arguments() -> AttackScenario:
    return AttackScenario(
        id="invalid-arguments",
        name="Invalid tool arguments",
        description="Submit arguments that violate the registered JSON Schema.",
        category="reject",
        severity="medium",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(("repository", "missing-state/backend"),),
        ),
        expected=ExpectedOutcome(
            http_status=422,
            status=None,
            decision=None,
            risk=None,
            flags=(),
            adapter_called=False,
        ),
    )


def _unknown_tool() -> AttackScenario:
    return AttackScenario(
        id="unknown-tool",
        name="Unknown tool",
        description="Invoke a tool that is not present in the trusted registry.",
        category="reject",
        severity="high",
        tool_name="shell.execute",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(("command", "echo demo"),),
        ),
        expected=ExpectedOutcome(
            http_status=404,
            status=None,
            decision=None,
            risk=None,
            flags=(),
            adapter_called=False,
        ),
    )


def _disabled_tool() -> AttackScenario:
    return AttackScenario(
        id="disabled-tool",
        name="Disabled tool",
        description="Disable the GitHub tool, attempt to execute it, then restore it.",
        category="reject",
        severity="medium",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=409,
            status=None,
            decision=None,
            risk=None,
            flags=(),
            adapter_called=False,
        ),
        setup=("disable_tool:github.list_issues",),
        cleanup=("enable_tool:github.list_issues",),
    )


def _indirect_prompt_injection() -> AttackScenario:
    return AttackScenario(
        id="indirect-prompt-injection",
        name="Indirect prompt injection in output",
        description=(
            "Trusted mock fixture returns text that instructs an LLM to exfiltrate "
            "credentials. The heuristic detector must flag the call without "
            "blocking it."
        ),
        category="flag-output",
        severity="high",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=200,
            status="succeeded",
            decision="flag",
            risk="high",
            flags=("possible_indirect_prompt_injection",),
            adapter_called=True,
        ),
    )


def _secret_in_output() -> AttackScenario:
    return AttackScenario(
        id="secret-in-output",
        name="Secret in tool output",
        description="Trusted mock fixture returns text containing a unique bearer token.",
        category="flag-output",
        severity="high",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=200,
            status="succeeded",
            decision="flag",
            risk="high",
            flags=("sensitive_output",),
            adapter_called=True,
        ),
        inject_unique_secret_in_result=True,
    )


def _persistent_replay() -> AttackScenario:
    return AttackScenario(
        id="persistent-replay",
        name="Persistent replay",
        description=(
            "Submit the same idempotency key twice and verify the adapter executes at most once."
        ),
        category="replay",
        severity="medium",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=200,
            status="succeeded",
            decision="allow",
            risk="low",
            flags=(),
            adapter_called=True,
            replayed=True,
        ),
    )


def _adapter_timeout() -> AttackScenario:
    return AttackScenario(
        id="adapter-timeout",
        name="Adapter timeout",
        description="Use a deterministic delayed adapter to trigger the timeout path.",
        category="timeout",
        severity="medium",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=504,
            status="timed_out",
            decision=None,
            risk=None,
            flags=(),
            adapter_called=True,
        ),
        setup=("install_slow_adapter:mock_github",),
        cleanup=("restore_default_adapters",),
    )


def _adapter_failure() -> AttackScenario:
    return AttackScenario(
        id="adapter-failure",
        name="Adapter failure sanitization",
        description="Mock adapter raises an exception containing a unique secret.",
        category="failure",
        severity="high",
        tool_name="github.list_issues",
        tool_version="1.0.0",
        request=ScenarioRequest(
            arguments_overrides=(
                ("repository", "demo/backend"),
                ("state", "open"),
            ),
        ),
        expected=ExpectedOutcome(
            http_status=502,
            status="failed",
            decision=None,
            risk=None,
            flags=(),
            adapter_called=True,
        ),
        setup=("install_failing_adapter:mock_github",),
        cleanup=("restore_default_adapters",),
        inject_unique_secret_in_result=True,
    )


SCENARIOS: tuple[AttackScenario, ...] = (
    _safe_github_read(),
    _sensitive_email_input(),
    _destructive_sql(),
    _multiple_sql_statements(),
    _invalid_arguments(),
    _unknown_tool(),
    _disabled_tool(),
    _indirect_prompt_injection(),
    _secret_in_output(),
    _persistent_replay(),
    _adapter_timeout(),
    _adapter_failure(),
)

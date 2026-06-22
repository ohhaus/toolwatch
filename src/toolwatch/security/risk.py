"""Deterministic input and output risk classification."""

import re
from dataclasses import dataclass

from toolwatch.domain.common import JSONObject, JSONValue
from toolwatch.domain.security import (
    RiskFlag,
    RiskFlagCode,
    RiskFlagSource,
    risk_max,
)
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.security.redaction import RedactionFinding

_SQL_LEADING_COMMENTS = re.compile(r"^\s*(?:(?:--[^\n]*\n)|(?:/\*.*?\*/\s*))*", re.DOTALL)
_SQL_OPERATION = re.compile(r"^([A-Za-z]+)")
_COMMAND = re.compile(r"(?:[;&|`]\s*|\$\(|\b(?:sh|bash|cmd|powershell)\b)", re.IGNORECASE)
_PATH_TRAVERSAL = re.compile(r"(?:^|[/\\])\.\.(?:[/\\]|$)")
_SSRF = re.compile(
    r"(?i)(?:localhost|127(?:\.\d{1,3}){3}|169\.254\.169\.254|metadata\.google\.internal)"
)
_PROMPT_INJECTION = re.compile(
    r"(?i)\b(?:ignore (?:previous|all prior) instructions|reveal the system prompt|"
    r"send the secret|read ~/\.ssh|upload credentials|call another tool|exfiltrate)\b"
)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Effective risk and stable safe flags."""

    level: RiskLevel
    flags: tuple[RiskFlag, ...]


def classify_input(
    tool: ToolDefinition,
    arguments: JSONObject,
    findings: tuple[RedactionFinding, ...],
) -> RiskAssessment:
    """Classify validated input without executing it."""

    flags: list[RiskFlag] = []
    if findings:
        flags.append(_flag(RiskFlagCode.SENSITIVE_INPUT, RiskLevel.HIGH, "Sensitive input found."))

    if tool.name == "email.send":
        flags.extend(
            [
                _flag(RiskFlagCode.WRITE_OPERATION, RiskLevel.MEDIUM, "The tool writes data."),
                _flag(
                    RiskFlagCode.EXTERNAL_SIDE_EFFECT,
                    RiskLevel.MEDIUM,
                    "The tool represents an external side effect.",
                ),
            ]
        )
    elif tool.name == "database.query":
        flags.extend(_classify_sql(arguments.get("query")))
    else:
        flags.extend(_generic_input_flags(arguments))

    level = tool.base_risk_level
    for flag in flags:
        level = risk_max(level, flag.severity)
    return RiskAssessment(level=level, flags=_deduplicate(flags))


def classify_output(
    value: JSONValue,
    findings: tuple[RedactionFinding, ...],
    base_level: RiskLevel,
) -> RiskAssessment:
    """Classify untrusted tool output after redaction."""

    flags: list[RiskFlag] = []
    if findings:
        flags.append(
            _flag(
                RiskFlagCode.SENSITIVE_OUTPUT,
                RiskLevel.HIGH,
                "Sensitive output found.",
                source=RiskFlagSource.OUTPUT,
            )
        )
    if _PROMPT_INJECTION.search(_flatten_strings(value)):
        flags.append(
            _flag(
                RiskFlagCode.POSSIBLE_INDIRECT_PROMPT_INJECTION,
                RiskLevel.HIGH,
                "The result contains a possible indirect prompt-injection instruction.",
                source=RiskFlagSource.OUTPUT,
            )
        )
    level = base_level
    for flag in flags:
        level = risk_max(level, flag.severity)
    return RiskAssessment(level=level, flags=_deduplicate(flags))


def _classify_sql(value: JSONValue | None) -> list[RiskFlag]:
    if not isinstance(value, str):
        return [_flag(RiskFlagCode.UNKNOWN_OPERATION, RiskLevel.HIGH, "SQL operation is unknown.")]
    query = _SQL_LEADING_COMMENTS.sub("", value).strip()
    statements = [part for part in query.split(";") if part.strip()]
    flags: list[RiskFlag] = []
    if len(statements) > 1:
        flags.append(
            _flag(
                RiskFlagCode.MULTIPLE_SQL_STATEMENTS,
                RiskLevel.CRITICAL,
                "The query contains multiple SQL statements.",
            )
        )
    match = _SQL_OPERATION.match(statements[0] if statements else "")
    operation = match.group(1).upper() if match else "UNKNOWN"
    if operation == "SELECT":
        return flags
    if operation in {"INSERT", "UPDATE", "DELETE"}:
        flags.append(
            _flag(
                RiskFlagCode.WRITE_SQL,
                RiskLevel.HIGH,
                "The query contains a write SQL operation.",
                {"keyword": operation},
            )
        )
        if operation == "DELETE":
            flags.append(
                _flag(
                    RiskFlagCode.DESTRUCTIVE_SQL,
                    RiskLevel.CRITICAL,
                    "The query contains a destructive SQL operation.",
                    {"keyword": operation},
                )
            )
    elif operation in {"DROP", "TRUNCATE", "ALTER"}:
        flags.append(
            _flag(
                RiskFlagCode.DESTRUCTIVE_SQL,
                RiskLevel.CRITICAL,
                "The query contains a destructive SQL operation.",
                {"keyword": operation},
            )
        )
    elif operation in {"CREATE", "GRANT", "REVOKE"}:
        flags.append(
            _flag(
                RiskFlagCode.WRITE_SQL,
                RiskLevel.HIGH,
                "The query contains a write SQL operation.",
                {"keyword": operation},
            )
        )
    else:
        flags.append(
            _flag(
                RiskFlagCode.UNKNOWN_OPERATION,
                RiskLevel.HIGH,
                "SQL operation is unknown.",
                {"keyword": operation[:20]},
            )
        )
    return flags


def _generic_input_flags(value: JSONValue) -> list[RiskFlag]:
    text = _flatten_strings(value)
    flags: list[RiskFlag] = []
    if _COMMAND.search(text):
        flags.append(
            _flag(
                RiskFlagCode.POSSIBLE_COMMAND_INJECTION,
                RiskLevel.HIGH,
                "Input contains possible command syntax.",
            )
        )
    if _PATH_TRAVERSAL.search(text):
        flags.append(
            _flag(
                RiskFlagCode.POSSIBLE_PATH_TRAVERSAL,
                RiskLevel.HIGH,
                "Input contains a possible path traversal.",
            )
        )
    if _SSRF.search(text):
        flags.append(
            _flag(
                RiskFlagCode.POSSIBLE_SSRF_TARGET,
                RiskLevel.CRITICAL,
                "Input contains a possible internal network target.",
            )
        )
    return flags


def _flatten_strings(value: JSONValue) -> str:
    values: list[str] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            values.append(current)
        elif isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return "\n".join(values)


def _flag(
    code: RiskFlagCode,
    severity: RiskLevel,
    message: str,
    evidence: JSONObject | None = None,
    *,
    source: RiskFlagSource = RiskFlagSource.INPUT,
) -> RiskFlag:
    return RiskFlag(
        code=code,
        severity=severity,
        message=message,
        safe_evidence=evidence or {},
        source=source,
    )


def _deduplicate(flags: list[RiskFlag]) -> tuple[RiskFlag, ...]:
    by_code: dict[RiskFlagCode, RiskFlag] = {}
    for flag in flags:
        by_code.setdefault(flag.code, flag)
    return tuple(by_code[code] for code in sorted(by_code, key=str))

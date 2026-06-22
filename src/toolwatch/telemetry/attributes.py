"""Central allowlist for bounded telemetry attributes and metric labels."""

from collections.abc import Mapping
from typing import Final

AttributeValue = str | bool | int | float

GEN_AI_OPERATION_NAME: Final = "gen_ai.operation.name"
GEN_AI_TOOL_NAME: Final = "gen_ai.tool.name"
GEN_AI_TOOL_TYPE: Final = "gen_ai.tool.type"
GEN_AI_PROVIDER_NAME: Final = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL: Final = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL: Final = "gen_ai.response.model"
GEN_AI_USAGE_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"

ALLOWED_SPAN_ATTRIBUTES: Final = frozenset(
    {
        GEN_AI_OPERATION_NAME,
        GEN_AI_TOOL_NAME,
        GEN_AI_TOOL_TYPE,
        GEN_AI_PROVIDER_NAME,
        GEN_AI_REQUEST_MODEL,
        GEN_AI_RESPONSE_MODEL,
        GEN_AI_USAGE_INPUT_TOKENS,
        GEN_AI_USAGE_OUTPUT_TOKENS,
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "toolwatch.tool.version",
        "toolwatch.tool.adapter_type",
        "toolwatch.risk.level",
        "toolwatch.decision",
        "toolwatch.call.status",
        "toolwatch.replayed",
        "toolwatch.flag.count",
        "toolwatch.rule.match_count",
        "toolwatch.redaction.input_count",
        "toolwatch.redaction.output_count",
        "toolwatch.error.code",
        "validation.valid",
        "validation.error_count",
        "redaction.finding_count",
        "risk.level",
        "rule.match_count",
        "decision",
        "db.operation",
        "toolwatch.agent.turn",
        "toolwatch.agent.tool_call_count",
        "toolwatch.agent.status",
    }
)

ALLOWED_METRIC_LABELS: Final = frozenset(
    {
        "method",
        "route",
        "status_code",
        "tool_name",
        "tool_version",
        "adapter_type",
        "status",
        "decision",
        "risk_level",
        "error_code",
        "flag_code",
        "rule_action",
        "replayed",
        "operation",
        "provider",
        "model",
    }
)

MAX_ATTRIBUTE_STRING_LENGTH: Final = 255


def safe_span_attributes(values: Mapping[str, object]) -> dict[str, AttributeValue]:
    """Drop every non-allowlisted, non-scalar, or oversized attribute."""

    result: dict[str, AttributeValue] = {}
    for key, value in values.items():
        if key not in ALLOWED_SPAN_ATTRIBUTES:
            continue
        if isinstance(value, str):
            if len(value) <= MAX_ATTRIBUTE_STRING_LENGTH:
                result[key] = value
        elif isinstance(value, bool | int | float):
            result[key] = value
    return result


def validate_metric_labels(values: Mapping[str, str]) -> dict[str, str]:
    """Reject labels outside the bounded metric schema."""

    unknown = set(values) - ALLOWED_METRIC_LABELS
    if unknown:
        raise ValueError("metric labels are not allowlisted")
    if any(len(value) > MAX_ATTRIBUTE_STRING_LENGTH for value in values.values()):
        raise ValueError("metric label value is too long")
    return dict(values)

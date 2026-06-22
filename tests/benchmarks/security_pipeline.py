"""Opt-in local microbenchmarks for Security Pipeline v1 engineering targets."""

from statistics import quantiles
from time import perf_counter

from toolwatch.domain.common import JSONObject, JSONValue
from toolwatch.domain.security import BlockingRule, RuleAction
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.security.redaction import DeterministicRedactor
from toolwatch.security.risk import classify_input
from toolwatch.security.rules import evaluate_rules


def percentile_95(samples: list[float]) -> float:
    """Return p95 milliseconds for a non-empty sample."""

    return quantiles(samples, n=100)[94] * 1000


def main() -> None:
    """Run local, non-CI benchmark probes."""

    redactor = DeterministicRedactor(
        fingerprint_key="benchmark-redaction-fingerprint-key",
    )
    payload: JSONValue = {
        "items": [{"value": "x" * 1000} for _ in range(63)],
        "token": "secret",
    }
    tool = ToolDefinition(
        name="database.query",
        description="Benchmark fixture.",
        version="1",
        input_schema={"type": "object"},
        output_schema=None,
        base_risk_level=RiskLevel.LOW,
        adapter_type="benchmark",
        adapter_config={},
    )
    arguments: JSONObject = {"query": "SELECT id FROM projects"}
    rules = [
        BlockingRule(
            name=f"benchmark-rule-{index}",
            description="Benchmark fixture.",
            enabled=True,
            priority=index,
            tool_pattern="database.query",
            conditions={"risk_at_least": "critical"},
            action=RuleAction.BLOCK,
        )
        for index in range(100)
    ]
    assessment = classify_input(tool, arguments, ())

    redaction = _measure(lambda: redactor.redact(payload))
    classification = _measure(lambda: classify_input(tool, arguments, ()))
    rule_evaluation = _measure(
        lambda: evaluate_rules(
            rules,
            tool_name=tool.name,
            risk_level=assessment.level,
            flags=assessment.flags,
            arguments=arguments,
        )
    )
    print(f"redaction_64kb_p95_ms={percentile_95(redaction):.3f}")
    print(f"risk_classification_p95_ms={percentile_95(classification):.3f}")
    print(f"rule_evaluation_100_p95_ms={percentile_95(rule_evaluation):.3f}")


def _measure(operation: object, *, iterations: int = 200) -> list[float]:
    from collections.abc import Callable
    from typing import cast

    callback = cast(Callable[[], object], operation)
    samples: list[float] = []
    for _ in range(iterations):
        started = perf_counter()
        callback()
        samples.append(perf_counter() - started)
    return samples


if __name__ == "__main__":
    main()

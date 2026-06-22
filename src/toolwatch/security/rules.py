"""Tightly constrained deterministic blocking-rule evaluator."""

import re
from collections.abc import Sequence

from toolwatch.domain.common import JSONObject
from toolwatch.domain.security import (
    BlockingRule,
    RiskFlag,
    RuleAction,
    RuleEvaluation,
    RuleMatch,
    json_path_value,
    risk_at_least,
)
from toolwatch.domain.tools import RiskLevel


def evaluate_rules(
    rules: Sequence[BlockingRule],
    *,
    tool_name: str,
    risk_level: RiskLevel,
    flags: Sequence[RiskFlag],
    arguments: JSONObject,
    result_phase: bool = False,
) -> RuleEvaluation:
    """Evaluate validated rules in stable priority order."""

    matches: list[RuleMatch] = []
    action = RuleAction.ALLOW
    ordered = sorted(rules, key=lambda item: (-item.priority, item.name, str(item.id)))
    for rule in ordered:
        if not rule.enabled or not rule.matches_tool(tool_name):
            continue
        if not _conditions_match(
            rule,
            tool_name=tool_name,
            risk_level=risk_level,
            flags=flags,
            arguments=arguments,
            result_phase=result_phase,
        ):
            continue
        matches.append(
            RuleMatch(
                rule_id=rule.id,
                rule_name=rule.name,
                action=rule.action,
                priority=rule.priority,
            )
        )
        if rule.action is RuleAction.BLOCK and not result_phase:
            action = RuleAction.BLOCK
            break
        if rule.action is RuleAction.FLAG:
            action = RuleAction.FLAG
    return RuleEvaluation(action=action, matches=tuple(matches))


def _conditions_match(
    rule: BlockingRule,
    *,
    tool_name: str,
    risk_level: RiskLevel,
    flags: Sequence[RiskFlag],
    arguments: JSONObject,
    result_phase: bool,
) -> bool:
    codes = {flag.code.value for flag in flags}
    for key, expected in rule.conditions.items():
        if key == "tool_equals" and tool_name != expected:
            return False
        if key == "tool_matches" and (
            not isinstance(expected, str) or re.fullmatch(expected, tool_name) is None
        ):
            return False
        if key == "risk_at_least" and (
            not isinstance(expected, str) or not risk_at_least(risk_level, RiskLevel(expected))
        ):
            return False
        if key == "has_flag" and (result_phase or expected not in codes):
            return False
        if key == "result_has_flag" and (not result_phase or expected not in codes):
            return False
        if key in {"argument_path_equals", "argument_path_matches"}:
            if not isinstance(expected, dict):
                return False
            path = expected.get("path")
            target = expected.get("value")
            if not isinstance(path, str):
                return False
            actual = json_path_value(arguments, path)
            if key == "argument_path_equals" and actual != target:
                return False
            if key == "argument_path_matches" and (
                not isinstance(actual, str)
                or not isinstance(target, str)
                or re.fullmatch(target, actual) is None
            ):
                return False
    return True

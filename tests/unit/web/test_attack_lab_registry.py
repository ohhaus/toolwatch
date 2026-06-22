"""Static registry tests for the Attack Lab."""

import pytest

from toolwatch.attack_lab import STATIC_REGISTRY, list_scenarios
from toolwatch.attack_lab.models import AttackScenario
from toolwatch.attack_lab.registry import get_scenario


def test_registry_is_a_read_only_mapping_of_static_scenarios() -> None:
    assert len(STATIC_REGISTRY) >= 12
    assert all(isinstance(scenario, AttackScenario) for scenario in STATIC_REGISTRY.values())
    with pytest.raises((TypeError, AttributeError)):
        STATIC_REGISTRY["new"] = scenario_for("safe-github-read")  # type: ignore[index]


def scenario_for(scenario_id: str) -> AttackScenario:
    scenario = STATIC_REGISTRY[scenario_id]
    assert scenario.id == scenario_id
    return scenario


def test_known_scenarios_have_expected_outcomes() -> None:
    destructive = scenario_for("destructive-sql")
    assert destructive.expected.decision == "block"
    assert destructive.expected.adapter_called is False

    sensitive = scenario_for("sensitive-email-input")
    assert sensitive.expected.decision == "flag"
    assert "sensitive_input" in sensitive.expected.flags

    timeout = scenario_for("adapter-timeout")
    assert timeout.expected.status == "timed_out"


def test_each_scenario_id_is_unique_and_alphanumeric() -> None:
    ids = [scenario.id for scenario in list_scenarios()]
    assert len(ids) == len(set(ids))
    for sid in ids:
        normalized = sid.replace("-", "").replace("_", "")
        assert normalized.isalnum(), sid


def test_unknown_scenario_returns_none() -> None:
    assert get_scenario("definitely-not-real") is None


def test_no_scenario_targets_unregistered_adapter() -> None:
    allowed_adapters = {"mock_github", "mock_email", "mock_database"}
    allowed_tools = {
        "github.list_issues": "mock_github",
        "email.send": "mock_email",
        "database.query": "mock_database",
    }
    for scenario in list_scenarios():
        # Either the tool is allowlisted, or the scenario asserts an
        # unknown-tool rejection without an adapter ever being called.
        if scenario.expected.adapter_called:
            assert scenario.tool_name in allowed_tools
            assert allowed_tools[scenario.tool_name] in allowed_adapters
        else:
            # adapter_called=False scenarios may legitimately target an
            # unknown tool name (the unknown-tool scenario).
            assert scenario.expected.adapter_called in {False, None}

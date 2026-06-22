"""Static immutable Attack Lab scenario registry."""

from types import MappingProxyType

from toolwatch.attack_lab.models import AttackScenario
from toolwatch.attack_lab.scenarios import SCENARIOS

STATIC_REGISTRY: MappingProxyType[str, AttackScenario] = MappingProxyType(
    {scenario.id: scenario for scenario in SCENARIOS}
)


def list_scenarios() -> tuple[AttackScenario, ...]:
    """Return the immutable tuple of registered scenarios."""

    return SCENARIOS


def get_scenario(scenario_id: str) -> AttackScenario | None:
    """Return one scenario by stable identifier."""

    return STATIC_REGISTRY.get(scenario_id)

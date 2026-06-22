"""Immutable Attack Lab data models."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    """Inputs sent to the ToolWatch execution pipeline by a scenario."""

    arguments_template: tuple[tuple[str, str], ...] = ()
    """Ordered template entries placed into the JSON request arguments.

    Values may contain the literal substring ``{unique}`` which the runner
    replaces with the per-run unique synthetic secret. Order is preserved so
    deterministic execution can be asserted in tests.
    """

    arguments_overrides: tuple[tuple[str, object], ...] = ()
    """Additional argument keys not subject to unique-secret interpolation."""

    def render_arguments(self, *, unique_secret: str) -> dict[str, object]:
        """Return the JSON arguments dict for one run."""

        arguments: dict[str, object] = {}
        for key, template in self.arguments_template:
            arguments[key] = template.replace("{unique}", unique_secret)
        for key, value in self.arguments_overrides:
            arguments[key] = value
        return arguments


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    """Outcome expectations checked against persisted state."""

    http_status: int | None = None
    status: str | None = None
    decision: str | None = None
    risk: str | None = None
    flags: tuple[str, ...] = ()
    adapter_called: bool | None = None
    replayed: bool | None = None
    secret_must_be_absent: bool = True


@dataclass(frozen=True, slots=True)
class AttackScenario:
    """Static deterministic Attack Lab scenario."""

    id: str
    name: str
    description: str
    category: str
    severity: str
    tool_name: str
    tool_version: str
    request: ScenarioRequest
    expected: ExpectedOutcome
    setup: tuple[str, ...] = ()
    cleanup: tuple[str, ...] = ()
    inject_unique_secret_in_arguments: bool = False
    inject_unique_secret_in_result: bool = False

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("scenario id must be a short alphanumeric identifier")
        if self.severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")


@dataclass(frozen=True, slots=True)
class AttackAssertion:
    """One safe assertion comparing an expected versus observed value."""

    name: str
    passed: bool
    expected: str
    observed_safe: str


@dataclass(frozen=True, slots=True)
class AttackRunResult:
    """Structured outcome of one scenario run."""

    scenario: AttackScenario
    passed: bool
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    tool_call_id: UUID | None
    session_id: UUID | None
    observed_status: str | None
    observed_decision: str | None
    observed_risk: str | None
    observed_flags: tuple[str, ...]
    matched_rules: tuple[str, ...]
    adapter_called: bool | None
    replayed: bool
    assertions: tuple[AttackAssertion, ...]
    trace_id: str | None = None
    correlation_id: str | None = None
    unique_secret_used: str = field(default="", repr=False)

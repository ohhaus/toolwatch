"""Isolated Prometheus-compatible metrics with bounded labels."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from time import perf_counter

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from toolwatch.telemetry.attributes import validate_metric_labels

DURATION_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)


class Metrics:
    """Process-local metrics registry that never accepts arbitrary label names."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.registry = CollectorRegistry()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._label_schemas: dict[str, tuple[str, ...]] = {}

    def counter(
        self,
        name: str,
        labels: Mapping[str, str] | None = None,
        amount: float = 1,
    ) -> None:
        """Increment a required counter using an exact label schema per metric."""

        if not self.enabled:
            return
        safe = validate_metric_labels(labels or {})
        counter = self._counters.get(name)
        if counter is None:
            counter = Counter(name, name, tuple(safe), registry=self.registry)
            self._counters[name] = counter
            self._label_schemas[name] = tuple(safe)
        elif self._label_schemas[name] != tuple(safe):
            raise ValueError("metric label schema changed")
        target = counter.labels(**safe) if safe else counter
        target.inc(amount)

    def histogram(
        self,
        name: str,
        seconds: float,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        """Observe a duration using documented explicit local-execution buckets."""

        if not self.enabled:
            return
        safe = validate_metric_labels(labels or {})
        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = Histogram(
                name,
                name,
                tuple(safe),
                buckets=DURATION_BUCKETS,
                registry=self.registry,
            )
            self._histograms[name] = histogram
            self._label_schemas[name] = tuple(safe)
        elif self._label_schemas[name] != tuple(safe):
            raise ValueError("metric label schema changed")
        target = histogram.labels(**safe) if safe else histogram
        target.observe(max(0.0, seconds))

    def render(self) -> bytes:
        """Render the isolated registry in Prometheus text format."""

        return generate_latest(self.registry) if self.enabled else b""

    @contextmanager
    def timer(
        self,
        name: str,
        labels: Mapping[str, str] | None = None,
    ) -> Generator[None]:
        """Observe elapsed wall time even when the measured operation fails."""

        started = perf_counter()
        try:
            yield
        finally:
            self.histogram(name, perf_counter() - started, labels)

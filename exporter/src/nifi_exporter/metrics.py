"""메트릭 스냅샷 저장소와 exporter 자체 메트릭입니다.

각 collector는 매 주기 메트릭 family를 새로 만들어 ``SnapshotStore``에 넘깁니다.
따라서 NiFi에서 사라진 컴포넌트는 다음 주기에 ``/metrics``에서도 사라지고, 실패한
collector의 family는 (오래된 값으로 고정되지 않고) 제거되며
``nifi_exporter_collector_success``가 0을 보고합니다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator

from prometheus_client import CollectorRegistry, Counter, Gauge
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from . import __version__
from .nifi.client import API_REQUESTS, API_RESPONSE_BYTES

LabelValues = tuple[str, ...]


class MetricSet:
    """수집 주기 한 번의 메트릭 family를 만드는 빌더입니다."""

    def __init__(self, const_labels: dict[str, str] | None = None) -> None:
        self._const = const_labels or {}
        self._families: dict[str, Metric] = {}

    def gauge(self, name: str, doc: str, labels: Iterable[str]) -> _Family:
        return self._family(name, doc, labels, kind="gauge")

    def counter(self, name: str, doc: str, labels: Iterable[str]) -> _Family:
        return self._family(name, doc, labels, kind="counter")

    def info(self, name: str, doc: str, labels: Iterable[str]) -> _Family:
        return self._family(name, doc, labels, kind="gauge")

    def _family(self, name: str, doc: str, labels: Iterable[str], *, kind: str) -> _Family:
        fam = self._families.get(name)
        if fam is None:
            label_names = [*self._const.keys(), *labels]
            cls = CounterMetricFamily if kind == "counter" else GaugeMetricFamily
            fam = cls(name, doc, labels=label_names)
            self._families[name] = fam
        return _Family(fam, tuple(self._const.values()))

    def families(self) -> list[Metric]:
        return list(self._families.values())


class _Family:
    def __init__(self, fam: Metric, const_values: LabelValues) -> None:
        self._fam = fam
        self._const = const_values

    def add(self, labels: Iterable[str | None], value: float | None) -> None:
        if value is None:
            return
        self._fam.add_metric([*self._const, *("" if v is None else str(v) for v in labels)], value)


class SnapshotStore(Collector):
    """collector별 최신 family를 보관하는 스레드 안전 저장소이며, Prometheus Collector입니다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[str, list[Metric]] = {}

    def set(self, collector: str, families: list[Metric]) -> None:
        with self._lock:
            self._snapshots[collector] = families

    def clear(self, collector: str) -> None:
        with self._lock:
            self._snapshots.pop(collector, None)

    def describe(self) -> list[Metric]:
        # describe가 비어 있으면 "unchecked" collector로 등록되며, 이것이 의도한
        # 동작입니다. family 집합이 NiFi flow에 따라 바뀌기 때문입니다.
        return []

    def collect(self) -> Iterator[Metric]:
        with self._lock:
            snapshots = [list(f) for f in self._snapshots.values()]
        for families in snapshots:
            yield from families


class SelfMetrics:
    """``nifi_exporter_*`` 상태 메트릭입니다."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.build_info = Gauge(
            "nifi_exporter_build_info",
            "Exporter build information.",
            ["version"],
            registry=registry,
        )
        self.build_info.labels(__version__).set(1)
        self.collector_success = Gauge(
            "nifi_exporter_collector_success",
            "1 if the last run of this collector succeeded, 0 otherwise.",
            ["collector"],
            registry=registry,
        )
        self.collector_duration = Gauge(
            "nifi_exporter_collector_duration_seconds",
            "Wall-clock duration of the last run of this collector.",
            ["collector"],
            registry=registry,
        )
        self.collector_last_success = Gauge(
            "nifi_exporter_collector_last_success_timestamp_seconds",
            "Unix time of the last successful run of this collector.",
            ["collector"],
            registry=registry,
        )
        self.collector_interval = Gauge(
            "nifi_exporter_collector_interval_seconds",
            "Configured run interval of this collector (staleness alerts scale with it).",
            ["collector"],
            registry=registry,
        )
        self.token_expiry = Gauge(
            "nifi_exporter_token_expiry_timestamp_seconds",
            "Unix time at which the current NiFi bearer token expires (bearer mode only).",
            registry=registry,
        )
        self.api_requests: Counter = API_REQUESTS
        registry.register(API_REQUESTS)
        registry.register(API_RESPONSE_BYTES)

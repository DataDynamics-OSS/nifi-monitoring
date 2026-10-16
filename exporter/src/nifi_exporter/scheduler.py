"""각 collector를 자기 주기에 따라 백그라운드 스레드에서 실행합니다.

``/metrics`` 핸들러는 NiFi를 호출하지 않고 최신 스냅샷만 직렬화합니다.
"""

from __future__ import annotations

import logging
import threading
import time

from .collectors import BaseCollector
from .metrics import SelfMetrics, SnapshotStore

log = logging.getLogger(__name__)

# 실패한 collector는 주기가 길어도 이 시간 뒤에 다시 시도합니다. topology(300초)처럼 주기가
# 긴 collector가 NiFi 재시작 직후의 실패를 오래 끌면, 그동안 NiFiCollectorFailing이 다른
# NiFi 알림을 모두 억제하기 때문입니다.
RETRY_AFTER_FAILURE = 30.0


class CollectorRunner:
    def __init__(
        self,
        collector: BaseCollector,
        interval: float,
        store: SnapshotStore,
        self_metrics: SelfMetrics,
    ) -> None:
        self.collector = collector
        self.interval = max(1.0, interval)
        self._store = store
        self._sm = self_metrics
        self._sm.collector_interval.labels(collector.name).set(self.interval)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name=f"collector-{collector.name}", daemon=True
        )
        self.ever_succeeded = False

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def run_once(self) -> bool:
        """수집 주기를 한 번 실행하고 성공하면 True를 반환합니다.

        직접 호출해도 안전합니다(테스트에서 씁니다).
        """
        name = self.collector.name
        started = time.monotonic()
        try:
            families = self.collector.collect()
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 메트릭을 버리고 success=0으로 둡니다
            self._store.clear(name)
            self._sm.collector_success.labels(name).set(0)
            self._sm.collector_duration.labels(name).set(time.monotonic() - started)
            log.error("collector failed", extra={"collector": name, "error": str(e)})
            return False
        self._store.set(name, families)
        self._sm.collector_success.labels(name).set(1)
        self._sm.collector_duration.labels(name).set(time.monotonic() - started)
        self._sm.collector_last_success.labels(name).set(time.time())
        self.ever_succeeded = True
        return True

    def next_delay(self, ok: bool) -> float:
        """다음 실행까지 기다릴 초입니다. 실패했으면 주기보다 짧게 다시 시도합니다."""
        return self.interval if ok else min(self.interval, RETRY_AFTER_FAILURE)

    def _loop(self) -> None:
        log.info(
            "collector started", extra={"collector": self.collector.name, "interval": self.interval}
        )
        while not self._stop.is_set():
            ok = self.run_once()
            self._stop.wait(self.next_delay(ok))
        log.info("collector stopped", extra={"collector": self.collector.name})

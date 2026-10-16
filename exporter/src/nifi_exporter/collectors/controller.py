"""``GET /controller/config`` + ``GET /flow/status`` → NiFi 스레드 풀 크기와 활성 스레드입니다.

Processor는 노드마다 크기가 ``maxTimerDrivenThreadCount``인 timer-driven 스레드 풀에서
실행됩니다. 활성 스레드가 이 크기에 붙어 있으면 Processor가 스레드를 기다리느라 처리가
밀립니다. 노드별 사용률은 recording rule ``nifi:thread_pool_utilization``이
``nifi_node_active_threads``(cluster collector)와 이 크기로 계산합니다.
"""

from __future__ import annotations

from prometheus_client.core import Metric

from ..util import to_float
from .base import BaseCollector


class ControllerCollector(BaseCollector):
    name = "controller"

    def collect(self) -> list[Metric]:
        config = self.client.get_json("/controller/config", endpoint="controller_config")
        status = self.client.get_json("/flow/status", endpoint="flow_status")
        component = config.get("component") or {}
        cs = status.get("controllerStatus") or {}
        ms = self.new_set()
        ms.gauge(
            "nifi_controller_max_timer_driven_threads",
            "Size of the timer-driven thread pool that runs processors (per node).",
            [],
        ).add([], to_float(component.get("maxTimerDrivenThreadCount")))
        ms.gauge(
            "nifi_controller_active_threads",
            "Active timer-driven threads, summed over all connected nodes.",
            [],
        ).add([], to_float(cs.get("activeThreadCount")))
        ms.gauge(
            "nifi_controller_terminated_threads",
            "Terminated threads still held, summed over all connected nodes.",
            [],
        ).add([], to_float(cs.get("terminatedThreadCount")))
        return ms.families()

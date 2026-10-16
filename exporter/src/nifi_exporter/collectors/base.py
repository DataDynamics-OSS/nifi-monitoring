from __future__ import annotations

from abc import ABC, abstractmethod

from prometheus_client.core import Metric

from ..metrics import MetricSet
from ..nifi import NiFiClient


class BaseCollector(ABC):
    """NiFi 데이터 원천 하나가 주기마다 메트릭 family 묶음 하나를 만듭니다."""

    name: str = "base"

    def __init__(self, client: NiFiClient, cluster_name: str) -> None:
        self.client = client
        self.cluster_name = cluster_name

    def new_set(self) -> MetricSet:
        return MetricSet(const_labels={"cluster": self.cluster_name})

    @abstractmethod
    def collect(self) -> list[Metric]:
        """NiFi에서 가져와 메트릭 family를 반환합니다. 실패하면 예외를 던집니다."""

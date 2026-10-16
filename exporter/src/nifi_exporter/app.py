"""설정 → 클라이언트 → collector → runner → HTTP 서버를 연결합니다."""

from __future__ import annotations

import logging
import signal
import threading

from prometheus_client import CollectorRegistry
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector

from .collectors import (
    BulletinCollector,
    ClusterCollector,
    ControllerCollector,
    DiagnosticsCollector,
    FlowCollector,
    TopologyCollector,
)
from .config import Config
from .metrics import SelfMetrics, SnapshotStore
from .nifi import build_client
from .nifi.auth import BearerAuth
from .scheduler import CollectorRunner
from .server import HTTPServer

log = logging.getLogger(__name__)


class Exporter:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        self.store = SnapshotStore()
        self.registry.register(self.store)
        self.self_metrics = SelfMetrics(self.registry)
        self.client = build_client(cfg.nifi)
        self.runners: list[CollectorRunner] = []
        self._build_runners()
        self.server: HTTPServer | None = None

    def _build_runners(self) -> None:
        n, c, s = self.cfg.nifi, self.cfg.collectors, self.cfg.server
        specs = [
            (c.cluster, lambda: ClusterCollector(self.client, n.cluster_name, n.timezone)),
            (c.flow, lambda: FlowCollector(self.client, n.cluster_name, c.flow.exclude_pg_ids)),
            (c.diagnostics, lambda: DiagnosticsCollector(self.client, n.cluster_name)),
            (
                c.bulletin,
                lambda: BulletinCollector(
                    self.client, n.cluster_name, c.bulletin.limit, s.log_bulletin_messages
                ),
            ),
            (c.controller, lambda: ControllerCollector(self.client, n.cluster_name)),
            (
                c.topology,
                lambda: TopologyCollector(
                    self.client, n.cluster_name, c.topology.exclude_pg_ids, n.max_concurrency
                ),
            ),
        ]
        for cc, factory in specs:
            if cc.enabled:
                self.runners.append(
                    CollectorRunner(factory(), cc.interval, self.store, self.self_metrics)
                )
        if not self.runners:
            log.warning("all collectors are disabled")

    def ready(self) -> bool:
        return any(r.ever_succeeded for r in self.runners)

    def _refresh_token_metric(self) -> None:
        auth = self.client.auth
        if isinstance(auth, BearerAuth) and auth.expiry is not None:
            self.self_metrics.token_expiry.set(auth.expiry)

    def start(self) -> None:
        for r in self.runners:
            r.start()
        ba = self.cfg.server.basic_auth
        self.server = HTTPServer(
            self.cfg.listen_host,
            self.cfg.listen_port,
            self.registry,
            self.ready,
            (ba.username, ba.password) if ba.enabled else None,
        )
        self.server.start()
        log.info(
            "nifi-exporter listening",
            extra={
                "listen": f"{self.cfg.listen_host}:{self.server.port}",
                "nifi": self.cfg.nifi.base_url,
            },
        )

    def stop(self) -> None:
        for r in self.runners:
            r.stop()
        if self.server:
            self.server.stop()
        for r in self.runners:
            r.join(2.0)
        self.client.close()

    def run_forever(self) -> None:
        stop = threading.Event()

        def _handle(signum, _frame):
            log.info("signal received, shutting down", extra={"signal": signum})
            stop.set()

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
        self.start()
        try:
            while not stop.is_set():
                stop.wait(5.0)
                self._refresh_token_metric()
        finally:
            self.stop()

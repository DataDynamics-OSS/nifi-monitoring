"""``GET /system-diagnostics?nodewise=true`` → JVM heap/GC, 스레드, 저장소 디스크 사용량입니다."""

from __future__ import annotations

from prometheus_client.core import Metric

from ..util import parse_uptime, to_float
from .base import BaseCollector

STANDALONE_NODE_ID = "standalone"


class DiagnosticsCollector(BaseCollector):
    name = "diagnostics"

    def collect(self) -> list[Metric]:
        body = self.client.get_json(
            "/system-diagnostics", params={"nodewise": "true"}, endpoint="system_diagnostics"
        )
        diag = body.get("systemDiagnostics") or {}
        ms = self.new_set()
        f = _Families(ms)

        node_snapshots = diag.get("nodeSnapshots") or []
        if node_snapshots:
            for ns in node_snapshots:
                node_id = ns.get("nodeId") or f"{ns.get('address')}:{ns.get('apiPort')}"
                self._emit(f, str(node_id), ns.get("snapshot") or {})
        else:
            # 단독 NiFi는 aggregate 스냅샷만 돌려줍니다.
            self._emit(f, STANDALONE_NODE_ID, diag.get("aggregateSnapshot") or {})
        return ms.families()

    def _emit(self, f: _Families, node: str, s: dict) -> None:
        used = to_float(s.get("usedHeapBytes"))
        maxh = to_float(s.get("maxHeapBytes"))
        f.heap_used.add([node], used)
        f.heap_max.add([node], maxh)
        if used is not None and maxh:
            f.heap_util.add([node], used / maxh)
        f.heap_committed.add([node], to_float(s.get("totalHeapBytes")))
        f.nonheap_used.add([node], to_float(s.get("usedNonHeapBytes")))
        f.nonheap_committed.add([node], to_float(s.get("totalNonHeapBytes")))
        f.uptime.add([node], parse_uptime(s.get("uptime")))
        f.threads.add([node], to_float(s.get("totalThreads")))
        f.daemon_threads.add([node], to_float(s.get("daemonThreads")))
        f.load.add([node], to_float(s.get("processorLoadAverage")))
        f.cpus.add([node], to_float(s.get("availableProcessors")))

        for gc in s.get("garbageCollection") or []:
            name = str(gc.get("name") or "unknown")
            f.gc_count.add([node, name], to_float(gc.get("collectionCount")))
            millis = to_float(gc.get("collectionMillis"))
            f.gc_seconds.add([node, name], None if millis is None else millis / 1000.0)

        ffr = s.get("flowFileRepositoryStorageUsage")
        if ffr:
            self._repo(f, node, "flowfile", ffr)
        for r in s.get("contentRepositoryStorageUsage") or []:
            self._repo(f, node, "content", r)
        for r in s.get("provenanceRepositoryStorageUsage") or []:
            self._repo(f, node, "provenance", r)

    @staticmethod
    def _repo(f: _Families, node: str, kind: str, r: dict) -> None:
        rid = str(r.get("identifier") or "default")
        used = to_float(r.get("usedSpaceBytes"))
        total = to_float(r.get("totalSpaceBytes"))
        f.repo_used.add([node, kind, rid], used)
        f.repo_total.add([node, kind, rid], total)
        f.repo_free.add([node, kind, rid], to_float(r.get("freeSpaceBytes")))
        if used is not None and total:
            f.repo_util.add([node, kind, rid], used / total)


class _Families:
    def __init__(self, ms) -> None:
        g, c = ms.gauge, ms.counter
        N = ["node_id"]
        GC = ["node_id", "collector"]
        R = ["node_id", "repo", "repo_id"]
        self.heap_used = g("nifi_jvm_heap_used_bytes", "JVM heap used.", N)
        self.heap_max = g("nifi_jvm_heap_max_bytes", "JVM max heap.", N)
        self.heap_util = g("nifi_jvm_heap_utilization", "JVM heap used / max (0-1).", N)
        self.heap_committed = g(
            "nifi_jvm_heap_committed_bytes",
            "JVM heap committed (memory the JVM has reserved from the OS).",
            N,
        )
        self.nonheap_used = g("nifi_jvm_nonheap_used_bytes", "JVM non-heap used.", N)
        self.nonheap_committed = g("nifi_jvm_nonheap_committed_bytes", "JVM non-heap committed.", N)
        self.uptime = g(
            "nifi_jvm_uptime_seconds", "JVM uptime; drops to near 0 when the node restarts.", N
        )
        self.threads = g("nifi_jvm_threads", "JVM thread count.", N)
        self.daemon_threads = g("nifi_jvm_daemon_threads", "JVM daemon thread count.", N)
        self.load = g("nifi_system_load_average", "System load average (1 minute).", N)
        self.cpus = g("nifi_system_available_processors", "Processors available to the JVM.", N)
        self.gc_count = c(
            "nifi_jvm_gc_collections_total", "GC collections since JVM start, by collector.", GC
        )
        self.gc_seconds = c(
            "nifi_jvm_gc_seconds_total", "GC time since JVM start, by collector.", GC
        )
        self.repo_used = g(
            "nifi_repo_used_bytes",
            "Repository storage used (repo = content|flowfile|provenance).",
            R,
        )
        self.repo_total = g("nifi_repo_total_bytes", "Repository storage total.", R)
        self.repo_free = g("nifi_repo_free_bytes", "Repository storage free.", R)
        self.repo_util = g("nifi_repo_utilization", "Repository storage used / total (0-1).", R)

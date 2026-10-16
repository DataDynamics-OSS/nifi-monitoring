"""``GET /controller/cluster`` → 노드 연결 상태, heartbeat 경과 시간, 역할입니다."""

from __future__ import annotations

import logging
import time

from prometheus_client.core import Metric

from ..nifi import NiFiAPIError
from ..util import parse_heartbeat, parse_queued, to_float
from .base import BaseCollector

log = logging.getLogger(__name__)

NODE_STATUSES = (
    "CONNECTED",
    "CONNECTING",
    "DISCONNECTED",
    "DISCONNECTING",
    "OFFLOADING",
    "OFFLOADED",
    "REMOVED",
)


class ClusterCollector(BaseCollector):
    name = "cluster"

    def __init__(self, client, cluster_name: str, timezone: str = "UTC") -> None:
        super().__init__(client, cluster_name)
        self._tz = timezone
        self._warned_heartbeat = False
        self._standalone_logged = False

    def collect(self) -> list[Metric]:
        try:
            body = self.client.get_json("/controller/cluster", endpoint="controller_cluster")
        except NiFiAPIError as e:
            if e.status != 404:
                raise
            return self._not_clustered()
        nodes = (body.get("cluster") or {}).get("nodes") or []
        now = time.time()
        ms = self.new_set()
        ms.gauge("nifi_cluster_clustered", "1 if NiFi runs as a cluster, 0 if standalone.", []).add(
            [], 1
        )

        total = ms.gauge("nifi_cluster_nodes_total", "Number of nodes known to the cluster.", [])
        connected = ms.gauge(
            "nifi_cluster_nodes_connected", "Number of nodes in CONNECTED state.", []
        )
        info = ms.info(
            "nifi_node_info",
            "Static node attributes. Value is always 1.",
            ["node_id", "address", "api_port", "roles"],
        )
        is_connected = ms.gauge(
            "nifi_node_connected", "1 if the node status is CONNECTED, else 0.", ["node_id"]
        )
        status = ms.gauge(
            "nifi_node_status",
            "Node status as a state set: 1 for the current status, 0 for the others.",
            ["node_id", "status"],
        )
        hb_age = ms.gauge(
            "nifi_node_heartbeat_age_seconds",
            "Seconds since the node's last heartbeat as reported by the coordinator.",
            ["node_id"],
        )
        threads = ms.gauge("nifi_node_active_threads", "Active threads on the node.", ["node_id"])
        queued_ff = ms.gauge(
            "nifi_node_queued_flowfiles", "FlowFiles queued on the node.", ["node_id"]
        )
        queued_bytes = ms.gauge(
            "nifi_node_queued_bytes",
            "Bytes queued on the node.",
            ["node_id"],
        )

        n_connected = 0
        for node in nodes:
            node_id = node.get("nodeId") or f"{node.get('address')}:{node.get('apiPort')}"
            st = str(node.get("status") or "UNKNOWN").upper()
            if st == "CONNECTED":
                n_connected += 1
            roles = ",".join(sorted(node.get("roles") or []))
            info.add([node_id, node.get("address"), node.get("apiPort"), roles], 1)
            is_connected.add([node_id], 1 if st == "CONNECTED" else 0)
            seen = set(NODE_STATUSES) | {st}
            for s in sorted(seen):
                status.add([node_id, s], 1 if s == st else 0)
            threads.add([node_id], to_float(node.get("activeThreadCount")))
            # NiFi 2.x는 숫자 flowFilesQueued/bytesQueued를 줍니다.
            # 이전 버전은 "1,200 / 3.5 MB" 문자열만 줍니다.
            count, qbytes = to_float(node.get("flowFilesQueued")), to_float(node.get("bytesQueued"))
            if count is None or qbytes is None:
                parsed = parse_queued(node.get("queued"))
                count = parsed[0] if count is None else count
                qbytes = parsed[1] if qbytes is None else qbytes
            queued_ff.add([node_id], count)
            queued_bytes.add([node_id], qbytes)
            hb = parse_heartbeat(node.get("heartbeat"), self._tz)
            if hb is not None:
                hb_age.add([node_id], max(0.0, now - hb.timestamp()))
            elif node.get("heartbeat") and not self._warned_heartbeat:
                self._warned_heartbeat = True
                log.warning(
                    "could not parse node heartbeat; nifi_node_heartbeat_age_seconds disabled",
                    extra={"heartbeat": node.get("heartbeat")},
                )

        total.add([], len(nodes))
        connected.add([], n_connected)
        return ms.families()

    def _not_clustered(self) -> list[Metric]:
        """``/controller/cluster``가 404일 때 단일 노드인지, 클러스터에서 끊긴 노드인지 가립니다.

        두 경우 모두 NiFi는 "Only a node connected to a cluster can process the request."로
        404를 줍니다. ``/flow/cluster/summary``의 ``clustered``가 false이면 단일 노드이므로
        정상으로 보고 ``nifi_cluster_clustered`` 0만 냅니다. true이면 이 노드가 클러스터에서
        끊긴 것이므로 실패로 처리합니다(노드 상태를 볼 수 없습니다).
        """
        summary = self.client.get_json("/flow/cluster/summary", endpoint="cluster_summary")
        if (summary.get("clusterSummary") or {}).get("clustered"):
            raise NiFiAPIError(
                "controller_cluster",
                "this NiFi node is not connected to its cluster; point nifi.base_url at a "
                "connected node or a load balancer",
                404,
            )
        if not self._standalone_logged:
            self._standalone_logged = True
            log.info("standalone NiFi: no cluster metrics, nifi_cluster_clustered=0")
        ms = self.new_set()
        ms.gauge("nifi_cluster_clustered", "1 if NiFi runs as a cluster, 0 if standalone.", []).add(
            [], 0
        )
        return ms.families()

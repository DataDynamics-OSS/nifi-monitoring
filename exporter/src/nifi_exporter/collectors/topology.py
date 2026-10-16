"""``GET /flow/process-groups/{id}`` 순회 → Connection 양 끝과 Backpressure 임계치입니다.

NiFi 2.6 status 스냅샷에는 Connection source/destination의 *이름*만 있습니다. 그래서
큐를 destination Processor와 조인하는 데 필요한 id는 flow 엔드포인트에서 가져옵니다.
Process Group마다 한 번씩, ``root``에서 시작해 하위 그룹을 단계별로 따라갑니다(한
단계의 요청은 클라이언트 동시성 한도 안에서 병렬로 실행합니다). 토폴로지는 자주
바뀌지 않으므로 긴 주기(기본 300s)로 실행합니다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from prometheus_client.core import Metric

from ..util import parse_size, to_float
from .base import BaseCollector


class TopologyCollector(BaseCollector):
    name = "topology"

    def __init__(
        self,
        client,
        cluster_name: str,
        exclude_pg_ids: list[str] | None = None,
        max_workers: int = 4,
    ) -> None:
        super().__init__(client, cluster_name)
        self._exclude = set(exclude_pg_ids or [])
        self._workers = max(1, max_workers)

    def collect(self) -> list[Metric]:
        ms = self.new_set()
        f = _Families(ms)
        level = ["root"]
        seen: set[str] = set()
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            while level:
                flows = list(pool.map(self._fetch, level))
                level = []
                for flow in flows:
                    pg_id = str(flow.get("id") or "")
                    if pg_id in seen:
                        continue
                    seen.add(pg_id)
                    content = flow.get("flow") or {}
                    for conn in content.get("connections") or []:
                        self._emit_connection(f, pg_id, conn)
                    for child in content.get("processGroups") or []:
                        cid = str(child.get("id") or "")
                        if cid and cid not in self._exclude and cid not in seen:
                            level.append(cid)
        return ms.families()

    def _fetch(self, pg_id: str) -> dict:
        body = self.client.get_json(f"/flow/process-groups/{pg_id}", endpoint="flow_process_group")
        flow = body.get("processGroupFlow")
        if not flow:
            raise ValueError(f"process group {pg_id}: response has no processGroupFlow")
        return flow

    @staticmethod
    def _emit_connection(f: _Families, pg_id: str, conn: dict) -> None:
        cid = str(conn.get("id") or "")
        # 엔티티 수준의 id/type은 컴포넌트 read 권한이 없어도 들어 있습니다.
        f.endpoints.add(
            [
                cid,
                pg_id,
                conn.get("sourceId"),
                conn.get("sourceType"),
                conn.get("sourceGroupId"),
                conn.get("destinationId"),
                conn.get("destinationType"),
                conn.get("destinationGroupId"),
            ],
            1,
        )
        comp = conn.get("component") or {}
        f.bp_objects.add([cid, pg_id], to_float(comp.get("backPressureObjectThreshold")))
        f.bp_bytes.add([cid, pg_id], parse_size(comp.get("backPressureDataSizeThreshold")))


class _Families:
    def __init__(self, ms) -> None:
        C = ["connection_id", "pg_id"]
        self.endpoints = ms.info(
            "nifi_connection_endpoints_info",
            "Connection source/destination component ids and types. Value is always 1.",
            [
                "connection_id",
                "pg_id",
                "source_id",
                "source_type",
                "source_group_id",
                "destination_id",
                "destination_type",
                "destination_group_id",
            ],
        )
        self.bp_objects = ms.gauge(
            "nifi_connection_backpressure_object_threshold",
            "Back pressure object count threshold of the connection (0 = disabled).",
            C,
        )
        self.bp_bytes = ms.gauge(
            "nifi_connection_backpressure_bytes_threshold",
            "Back pressure data size threshold of the connection in bytes (0 = disabled).",
            C,
        )

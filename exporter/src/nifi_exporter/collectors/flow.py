"""``GET /flow/process-groups/root/status?recursive=true`` → PG/processor/connection/port/RPG입니다.

요청 한 번으로 전체 flow를 ``processGroupStatusSnapshot`` 노드의 트리로 받습니다.
트리를 순회하며 계층 info 메트릭(``*_info``)과 스냅샷 수치를 만듭니다.
in/out/task 값은 모두 NiFi의 5분 롤링 통계입니다(gauge, ``_5m`` 접미사).
Funnel은 status 스냅샷이 없어 내보내지 않습니다.
"""

from __future__ import annotations

from collections import Counter as TallyCounter
from dataclasses import dataclass

from prometheus_client.core import Metric

from ..util import to_float
from .base import BaseCollector

RUN_STATUSES = ("Running", "Stopped", "Invalid", "Disabled", "Validating")
PORT_STATUSES = ("Running", "Stopped", "Invalid", "Disabled")
NANOS = 1e-9


@dataclass
class _PG:
    id: str
    name: str
    parent_id: str
    path: str
    depth: int


class FlowCollector(BaseCollector):
    name = "flow"

    def __init__(self, client, cluster_name: str, exclude_pg_ids: list[str] | None = None) -> None:
        super().__init__(client, cluster_name)
        self._exclude = set(exclude_pg_ids or [])

    def collect(self) -> list[Metric]:
        body = self.client.get_json(
            "/flow/process-groups/root/status",
            params={"recursive": "true"},
            endpoint="flow_status_recursive",
        )
        root = (body.get("processGroupStatus") or {}).get("aggregateSnapshot")
        if not root:
            raise ValueError("response has no processGroupStatus.aggregateSnapshot")
        ms = self.new_set()
        self._f = _Families(ms)
        self._walk(root, parent_id="", parent_path="", depth=0)
        return ms.families()

    # -- 트리 순회 ---------------------------------------------------------

    def _walk(self, snap: dict, *, parent_id: str, parent_path: str, depth: int) -> None:
        pg_id = str(snap.get("id") or "")
        if pg_id in self._exclude:
            return
        name = str(snap.get("name") or pg_id)
        path = "/" if depth == 0 else f"{parent_path.rstrip('/')}/{name}"
        pg = _PG(pg_id, name, parent_id, path, depth)
        self._emit_pg(pg, snap)

        tally: TallyCounter[str] = TallyCounter()
        for entry in snap.get("processorStatusSnapshots") or []:
            p = entry.get("processorStatusSnapshot") or {}
            if p:
                tally[str(p.get("runStatus") or "Unknown")] += 1
                self._emit_processor(pg, p)
        for status in sorted(set(RUN_STATUSES) | set(tally)):
            self._f.pg_processors.add([pg.id, status], tally.get(status, 0))

        for entry in snap.get("connectionStatusSnapshots") or []:
            c = entry.get("connectionStatusSnapshot") or {}
            if c:
                self._emit_connection(pg, c)

        for direction in ("input", "output"):
            for entry in snap.get(f"{direction}PortStatusSnapshots") or []:
                p = entry.get("portStatusSnapshot") or {}
                if p:
                    self._emit_port(pg, p, direction)

        for entry in snap.get("remoteProcessGroupStatusSnapshots") or []:
            r = entry.get("remoteProcessGroupStatusSnapshot") or {}
            if r:
                self._emit_rpg(pg, r)

        for entry in snap.get("processGroupStatusSnapshots") or []:
            child = entry.get("processGroupStatusSnapshot") or {}
            if child:
                self._walk(child, parent_id=pg.id, parent_path=path, depth=depth + 1)

    # -- 메트릭 생성 ----------------------------------------------------------

    def _emit_pg(self, pg: _PG, s: dict) -> None:
        f = self._f
        f.pg_info.add([pg.id, pg.name, pg.parent_id, pg.path, pg.depth], 1)
        f.pg_queued_ff.add([pg.id], to_float(s.get("flowFilesQueued")))
        f.pg_queued_bytes.add([pg.id], to_float(s.get("bytesQueued")))
        f.pg_active_threads.add([pg.id], to_float(s.get("activeThreadCount")))
        f.pg_terminated_threads.add([pg.id], to_float(s.get("terminatedThreadCount")))
        f.pg_ff_in.add([pg.id], to_float(s.get("flowFilesIn")))
        f.pg_bytes_in.add([pg.id], to_float(s.get("bytesIn")))
        f.pg_ff_out.add([pg.id], to_float(s.get("flowFilesOut")))
        f.pg_bytes_out.add([pg.id], to_float(s.get("bytesOut")))
        nanos = to_float(s.get("processingNanos"))
        f.pg_processing.add([pg.id], None if nanos is None else nanos * NANOS)

    def _emit_processor(self, pg: _PG, p: dict) -> None:
        f = self._f
        pid = str(p.get("id") or "")
        run = str(p.get("runStatus") or "Unknown")
        f.proc_info.add([pid, pg.id, p.get("name"), p.get("type"), p.get("executionNode") or ""], 1)
        for status in sorted(set(RUN_STATUSES) | {run}):
            f.proc_run_status.add([pid, pg.id, status], 1 if status == run else 0)
        f.proc_running.add([pid, pg.id], 1 if run == "Running" else 0)
        f.proc_active_threads.add([pid, pg.id], to_float(p.get("activeThreadCount")))
        f.proc_terminated_threads.add([pid, pg.id], to_float(p.get("terminatedThreadCount")))
        f.proc_ff_in.add([pid, pg.id], to_float(p.get("flowFilesIn")))
        f.proc_ff_out.add([pid, pg.id], to_float(p.get("flowFilesOut")))
        f.proc_bytes_in.add([pid, pg.id], to_float(p.get("bytesIn")))
        f.proc_bytes_out.add([pid, pg.id], to_float(p.get("bytesOut")))
        f.proc_bytes_read.add([pid, pg.id], to_float(p.get("bytesRead")))
        f.proc_bytes_written.add([pid, pg.id], to_float(p.get("bytesWritten")))
        f.proc_tasks.add([pid, pg.id], to_float(p.get("taskCount")))
        nanos = to_float(p.get("tasksDurationNanos"))
        f.proc_tasks_duration.add([pid, pg.id], None if nanos is None else nanos * NANOS)

    def _emit_connection(self, pg: _PG, c: dict) -> None:
        f = self._f
        cid = str(c.get("id") or "")
        f.conn_info.add(
            [
                cid,
                pg.id,
                c.get("name"),
                c.get("sourceName"),
                c.get("destinationName"),
            ],
            1,
        )
        f.conn_queued_ff.add([cid, pg.id], to_float(c.get("flowFilesQueued")))
        f.conn_queued_bytes.add([cid, pg.id], to_float(c.get("bytesQueued")))
        f.conn_pct_count.add([cid, pg.id], to_float(c.get("percentUseCount")))
        f.conn_pct_bytes.add([cid, pg.id], to_float(c.get("percentUseBytes")))
        f.conn_ff_in.add([cid, pg.id], to_float(c.get("flowFilesIn")))
        f.conn_ff_out.add([cid, pg.id], to_float(c.get("flowFilesOut")))
        f.conn_bytes_in.add([cid, pg.id], to_float(c.get("bytesIn")))
        f.conn_bytes_out.add([cid, pg.id], to_float(c.get("bytesOut")))

    def _emit_port(self, pg: _PG, p: dict, direction: str) -> None:
        f = self._f
        pid = str(p.get("id") or "")
        run = str(p.get("runStatus") or "Unknown")
        f.port_info.add([pid, pg.id, p.get("name"), direction], 1)
        for status in sorted(set(PORT_STATUSES) | {run}):
            f.port_run_status.add([pid, pg.id, status], 1 if status == run else 0)
        # site-to-site 포트(루트 그룹)에만 해당합니다. 내부 포트는 NiFi가 false로 보고합니다
        f.port_transmitting.add([pid, pg.id], 1 if p.get("transmitting") else 0)
        f.port_active_threads.add([pid, pg.id], to_float(p.get("activeThreadCount")))
        f.port_ff_in.add([pid, pg.id], to_float(p.get("flowFilesIn")))
        f.port_bytes_in.add([pid, pg.id], to_float(p.get("bytesIn")))
        f.port_ff_out.add([pid, pg.id], to_float(p.get("flowFilesOut")))
        f.port_bytes_out.add([pid, pg.id], to_float(p.get("bytesOut")))

    def _emit_rpg(self, pg: _PG, r: dict) -> None:
        f = self._f
        rid = str(r.get("id") or "")
        f.rpg_info.add([rid, pg.id, r.get("name"), r.get("targetUri")], 1)
        f.rpg_transmitting.add(
            [rid, pg.id], 1 if r.get("transmissionStatus") == "Transmitting" else 0
        )
        f.rpg_active_threads.add([rid, pg.id], to_float(r.get("activeThreadCount")))
        f.rpg_ff_sent.add([rid, pg.id], to_float(r.get("flowFilesSent")))
        f.rpg_bytes_sent.add([rid, pg.id], to_float(r.get("bytesSent")))
        f.rpg_ff_received.add([rid, pg.id], to_float(r.get("flowFilesReceived")))
        f.rpg_bytes_received.add([rid, pg.id], to_float(r.get("bytesReceived")))


class _Families:
    """flow collector의 모든 메트릭 family입니다. 주기마다 한 번 만듭니다."""

    def __init__(self, ms) -> None:
        g = ms.gauge
        PG = ["pg_id"]
        P = ["processor_id", "pg_id"]
        C = ["connection_id", "pg_id"]
        w5 = " (NiFi 5-minute rolling window)."

        self.pg_info = ms.info(
            "nifi_pg_info",
            "Process group hierarchy. Value is always 1.",
            ["pg_id", "pg_name", "parent_id", "pg_path", "depth"],
        )
        self.pg_queued_ff = g(
            "nifi_pg_queued_flowfiles", "FlowFiles queued in the process group (recursive).", PG
        )
        self.pg_queued_bytes = g(
            "nifi_pg_queued_bytes", "Bytes queued in the process group (recursive).", PG
        )
        self.pg_active_threads = g(
            "nifi_pg_active_threads", "Active threads in the process group.", PG
        )
        self.pg_terminated_threads = g(
            "nifi_pg_terminated_threads", "Terminated threads in the process group.", PG
        )
        self.pg_ff_in = g("nifi_pg_flowfiles_in_5m", "FlowFiles into the process group" + w5, PG)
        self.pg_bytes_in = g("nifi_pg_bytes_in_5m", "Bytes into the process group" + w5, PG)
        self.pg_ff_out = g(
            "nifi_pg_flowfiles_out_5m", "FlowFiles out of the process group" + w5, PG
        )
        self.pg_bytes_out = g("nifi_pg_bytes_out_5m", "Bytes out of the process group" + w5, PG)
        self.pg_processing = g(
            "nifi_pg_processing_seconds_5m", "Processing time in the process group" + w5, PG
        )
        self.pg_processors = g(
            "nifi_pg_processors",
            "Number of processors directly in the process group, by run status.",
            ["pg_id", "status"],
        )

        self.proc_info = ms.info(
            "nifi_processor_info",
            "Processor attributes. Value is always 1.",
            ["processor_id", "pg_id", "name", "type", "execution_node"],
        )
        self.proc_run_status = g(
            "nifi_processor_run_status",
            "Processor run status as a state set: 1 for the current status, 0 for the others.",
            ["processor_id", "pg_id", "status"],
        )
        self.proc_running = g(
            "nifi_processor_running", "1 if the processor run status is Running.", P
        )
        self.proc_active_threads = g(
            "nifi_processor_active_threads", "Active threads of the processor.", P
        )
        self.proc_terminated_threads = g(
            "nifi_processor_terminated_threads", "Terminated threads of the processor.", P
        )
        self.proc_ff_in = g(
            "nifi_processor_flowfiles_in_5m", "FlowFiles into the processor" + w5, P
        )
        self.proc_ff_out = g(
            "nifi_processor_flowfiles_out_5m", "FlowFiles out of the processor" + w5, P
        )
        self.proc_bytes_in = g("nifi_processor_bytes_in_5m", "Bytes into the processor" + w5, P)
        self.proc_bytes_out = g("nifi_processor_bytes_out_5m", "Bytes out of the processor" + w5, P)
        self.proc_bytes_read = g(
            "nifi_processor_bytes_read_5m", "Bytes read from content repository" + w5, P
        )
        self.proc_bytes_written = g(
            "nifi_processor_bytes_written_5m", "Bytes written to content repository" + w5, P
        )
        self.proc_tasks = g("nifi_processor_tasks_5m", "Tasks executed by the processor" + w5, P)
        self.proc_tasks_duration = g(
            "nifi_processor_tasks_duration_seconds_5m",
            "Total task duration of the processor" + w5,
            P,
        )

        self.conn_info = ms.info(
            "nifi_connection_info",
            "Connection name and endpoint names. Value is always 1. Endpoint ids are in "
            "nifi_connection_endpoints_info (topology collector).",
            ["connection_id", "pg_id", "name", "source_name", "destination_name"],
        )
        self.conn_queued_ff = g(
            "nifi_connection_queued_flowfiles", "FlowFiles queued in the connection.", C
        )
        self.conn_queued_bytes = g(
            "nifi_connection_queued_bytes", "Bytes queued in the connection.", C
        )
        self.conn_pct_count = g(
            "nifi_connection_percent_used_count",
            "Queue object count as percent of the back pressure threshold.",
            C,
        )
        self.conn_pct_bytes = g(
            "nifi_connection_percent_used_bytes",
            "Queue size as percent of the back pressure data size threshold.",
            C,
        )
        self.conn_ff_in = g(
            "nifi_connection_flowfiles_in_5m", "FlowFiles into the connection" + w5, C
        )
        self.conn_ff_out = g(
            "nifi_connection_flowfiles_out_5m", "FlowFiles out of the connection" + w5, C
        )
        self.conn_bytes_in = g("nifi_connection_bytes_in_5m", "Bytes into the connection" + w5, C)
        self.conn_bytes_out = g(
            "nifi_connection_bytes_out_5m", "Bytes out of the connection" + w5, C
        )

        PT = ["port_id", "pg_id"]
        self.port_info = ms.info(
            "nifi_port_info",
            "Input/output port attributes. Value is always 1.",
            ["port_id", "pg_id", "name", "direction"],
        )
        self.port_run_status = g(
            "nifi_port_run_status",
            "Port run status as a state set: 1 for the current status, 0 for the others.",
            ["port_id", "pg_id", "status"],
        )
        self.port_transmitting = g(
            "nifi_port_transmitting",
            "1 if a site-to-site (root group) port is transmitting.",
            PT,
        )
        self.port_active_threads = g("nifi_port_active_threads", "Active threads of the port.", PT)
        self.port_ff_in = g("nifi_port_flowfiles_in_5m", "FlowFiles into the port" + w5, PT)
        self.port_bytes_in = g("nifi_port_bytes_in_5m", "Bytes into the port" + w5, PT)
        self.port_ff_out = g("nifi_port_flowfiles_out_5m", "FlowFiles out of the port" + w5, PT)
        self.port_bytes_out = g("nifi_port_bytes_out_5m", "Bytes out of the port" + w5, PT)

        R = ["rpg_id", "pg_id"]
        self.rpg_info = ms.info(
            "nifi_rpg_info",
            "Remote process group attributes. Value is always 1.",
            ["rpg_id", "pg_id", "name", "target_uri"],
        )
        self.rpg_transmitting = g(
            "nifi_rpg_transmitting", "1 if the remote process group is transmitting.", R
        )
        self.rpg_active_threads = g(
            "nifi_rpg_active_threads", "Active threads of the remote process group.", R
        )
        self.rpg_ff_sent = g("nifi_rpg_flowfiles_sent_5m", "FlowFiles sent" + w5, R)
        self.rpg_bytes_sent = g("nifi_rpg_bytes_sent_5m", "Bytes sent" + w5, R)
        self.rpg_ff_received = g("nifi_rpg_flowfiles_received_5m", "FlowFiles received" + w5, R)
        self.rpg_bytes_received = g("nifi_rpg_bytes_received_5m", "Bytes received" + w5, R)

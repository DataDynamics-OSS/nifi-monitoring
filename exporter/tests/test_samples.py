"""``design/samples/``의 실제 NiFi 응답(NiFi 2.6.0)으로 collector를 시험합니다.

합성 fixture는 정확한 값을 고정하고, 이 테스트는 *형태*를 고정합니다. 실제 응답의
모든 컴포넌트가 메트릭으로 나와야 하므로, NiFi 업그레이드로 필드 이름이 바뀌거나
빠지면 여기서 실패합니다. ``deploy/local/capture_samples.py``로(또는 CFM에 대해)
샘플을 다시 수집한 뒤 다시 실행합니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry
from werkzeug.wrappers import Response

from nifi_exporter.collectors import (
    BulletinCollector,
    ClusterCollector,
    ControllerCollector,
    DiagnosticsCollector,
    FlowCollector,
    TopologyCollector,
)
from nifi_exporter.scheduler import CollectorRunner

from .conftest import sample

SAMPLES = Path(__file__).resolve().parents[2] / "design" / "samples"

pytestmark = pytest.mark.skipif(not SAMPLES.is_dir(), reason="design/samples not present")


def load(name: str):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def run(collector, harness) -> CollectorRegistry:
    registry, store, sm = harness
    assert CollectorRunner(collector, 30, store, sm).run_once()
    return registry


def series(registry: CollectorRegistry, name: str) -> list[dict[str, str]]:
    return [s.labels for m in registry.collect() for s in m.samples if s.name == name]


def walk_status(snap: dict):
    """status 트리의 모든 PG/processor/connection에 대해 (kind, snapshot)을 내놓습니다."""
    yield "pg", snap
    for e in snap.get("processorStatusSnapshots") or []:
        yield "processor", e["processorStatusSnapshot"]
    for e in snap.get("connectionStatusSnapshots") or []:
        yield "connection", e["connectionStatusSnapshot"]
    for e in snap.get("processGroupStatusSnapshots") or []:
        yield from walk_status(e["processGroupStatusSnapshot"])


def status_tree() -> dict:
    return load("flow_status_recursive.json")["processGroupStatus"]["aggregateSnapshot"]


def test_about_is_target_version():
    assert load("about.json")["about"]["version"].startswith("2.6.0")


def test_cluster_sample(httpserver, client, harness):
    body = load("cluster.json")
    httpserver.expect_request("/nifi-api/controller/cluster").respond_with_json(body)
    reg = run(ClusterCollector(client, "s"), harness)
    nodes = body["cluster"]["nodes"]
    assert sample(reg, "nifi_cluster_nodes_total", cluster="s") == len(nodes)
    for node in nodes:
        nid = node["nodeId"]
        assert sample(reg, "nifi_node_heartbeat_age_seconds", cluster="s", node_id=nid) is not None
        assert (
            sample(reg, "nifi_node_queued_flowfiles", cluster="s", node_id=nid)
            == node["flowFilesQueued"]
        )
        assert (
            sample(reg, "nifi_node_queued_bytes", cluster="s", node_id=nid) == node["bytesQueued"]
        )
    roles = {s["roles"] for s in series(reg, "nifi_node_info")}
    assert "Cluster Coordinator,Primary Node" in roles


def test_flow_sample(httpserver, client, harness):
    httpserver.expect_request("/nifi-api/flow/process-groups/root/status").respond_with_json(
        load("flow_status_recursive.json")
    )
    reg = run(FlowCollector(client, "s"), harness)
    items = list(walk_status(status_tree()))
    by_kind = {k: [s for kind, s in items if kind == k] for k in ("pg", "processor", "connection")}
    assert {s["pg_id"] for s in series(reg, "nifi_pg_info")} == {p["id"] for p in by_kind["pg"]}
    assert {s["processor_id"] for s in series(reg, "nifi_processor_info")} == {
        p["id"] for p in by_kind["processor"]
    }
    assert {s["connection_id"] for s in series(reg, "nifi_connection_info")} == {
        c["id"] for c in by_kind["connection"]
    }
    # 모든 컴포넌트에 수치가 있어야 합니다(필드 이름이 바뀌면 빈 곳이 생깁니다)
    per_component = {
        "processor": [
            "nifi_processor_tasks_5m",
            "nifi_processor_tasks_duration_seconds_5m",
            "nifi_processor_flowfiles_in_5m",
            "nifi_processor_bytes_written_5m",
            "nifi_processor_active_threads",
            "nifi_processor_terminated_threads",
        ],
        "connection": [
            "nifi_connection_queued_flowfiles",
            "nifi_connection_queued_bytes",
            "nifi_connection_percent_used_count",
            "nifi_connection_percent_used_bytes",
            "nifi_connection_flowfiles_in_5m",
        ],
        "pg": [
            "nifi_pg_queued_flowfiles",
            "nifi_pg_flowfiles_in_5m",
            "nifi_pg_processing_seconds_5m",
            "nifi_pg_active_threads",
        ],
    }
    for kind, names in per_component.items():
        for name in names:
            assert len(series(reg, name)) == len(by_kind[kind]), name
    run_status = {s["status"] for s in series(reg, "nifi_processor_run_status")}
    assert {"Running", "Stopped", "Invalid"} <= run_status
    # 포트와 Remote Process Group입니다(샘플 flow에 둘 다 있습니다)
    ports = [
        e["portStatusSnapshot"]
        for _, snap in items
        if _ == "pg"
        for k in ("inputPortStatusSnapshots", "outputPortStatusSnapshots")
        for e in snap.get(k) or []
    ]
    rpgs = [
        e["remoteProcessGroupStatusSnapshot"]
        for _, snap in items
        if _ == "pg"
        for e in snap.get("remoteProcessGroupStatusSnapshots") or []
    ]
    assert ports and rpgs
    assert {s["port_id"] for s in series(reg, "nifi_port_info")} == {p["id"] for p in ports}
    assert {s["rpg_id"] for s in series(reg, "nifi_rpg_info")} == {r["id"] for r in rpgs}
    assert len(series(reg, "nifi_rpg_transmitting")) == len(rpgs)


def test_diagnostics_sample(httpserver, client, harness):
    body = load("system_diagnostics_nodewise.json")
    httpserver.expect_request("/nifi-api/system-diagnostics").respond_with_json(body)
    reg = run(DiagnosticsCollector(client, "s"), harness)
    for ns in body["systemDiagnostics"]["nodeSnapshots"]:
        nid = ns["nodeId"]
        assert sample(reg, "nifi_jvm_heap_utilization", cluster="s", node_id=nid) is not None
        assert sample(reg, "nifi_system_load_average", cluster="s", node_id=nid) is not None
        repos = {s["repo"] for s in series(reg, "nifi_repo_utilization") if s["node_id"] == nid}
        assert repos == {"content", "flowfile", "provenance"}
        gcs = [s for s in series(reg, "nifi_jvm_gc_seconds_total") if s["node_id"] == nid]
        assert len(gcs) == len(ns["snapshot"]["garbageCollection"])
        n = {"cluster": "s", "node_id": nid}
        assert sample(reg, "nifi_jvm_heap_committed_bytes", **n) == ns["snapshot"]["totalHeapBytes"]
        assert sample(reg, "nifi_jvm_uptime_seconds", **n) > 0


def test_bulletin_sample(httpserver, client, harness):
    body = load("bulletin_board.json")
    responses = iter([{"bulletinBoard": {"bulletins": []}}, body])
    httpserver.expect_request("/nifi-api/flow/bulletin-board").respond_with_handler(
        lambda _req: Response(json.dumps(next(responses)), content_type="application/json")
    )
    registry, store, sm = harness
    runner = CollectorRunner(BulletinCollector(client, "s"), 30, store, sm)
    assert runner.run_once()  # 빈 board로 커서를 설정합니다
    assert runner.run_once()
    bulletins = [b["bulletin"] for b in body["bulletinBoard"]["bulletins"]]
    total = sum(
        s.value for m in registry.collect() for s in m.samples if s.name == "nifi_bulletins_total"
    )
    assert total == len(bulletins)
    errors = [b for b in bulletins if b["level"] == "ERROR"]
    if errors:
        assert (
            sample(
                registry,
                "nifi_bulletins_total",
                cluster="s",
                level="ERROR",
                pg_id=errors[0]["groupId"],
                source_id=errors[0]["sourceId"],
                source_type="PROCESSOR",
            )
            >= 1
        )


def test_topology_sample_joins_status(httpserver, client, harness):
    for key, body in load("flow_process_groups.json").items():
        httpserver.expect_request(f"/nifi-api/flow/process-groups/{key}").respond_with_json(body)
    reg = run(TopologyCollector(client, "s"), harness)
    endpoints = series(reg, "nifi_connection_endpoints_info")
    status_items = list(walk_status(status_tree()))
    status_conns = {s["id"] for kind, s in status_items if kind == "connection"}
    processors = {s["id"] for kind, s in status_items if kind == "processor"}
    # status 트리의 모든 Connection은 topology 순회에서 양 끝 id를 받습니다
    assert {e["connection_id"] for e in endpoints} == status_conns
    # destination id는 status 트리의 Processor로 이어져야 합니다
    # (nifi:connection_destination_running의 조인 기준입니다)
    for e in endpoints:
        if e["destination_type"] == "PROCESSOR":
            assert e["destination_id"] in processors
    assert len(series(reg, "nifi_connection_backpressure_object_threshold")) == len(endpoints)


def test_controller_sample(httpserver, client, harness):
    config, status = load("controller_config.json"), load("controller_status.json")
    httpserver.expect_request("/nifi-api/controller/config").respond_with_json(config)
    httpserver.expect_request("/nifi-api/flow/status").respond_with_json(status)
    reg = run(ControllerCollector(client, "s"), harness)
    assert (
        sample(reg, "nifi_controller_max_timer_driven_threads", cluster="s")
        == config["component"]["maxTimerDrivenThreadCount"]
    )
    assert (
        sample(reg, "nifi_controller_active_threads", cluster="s")
        == status["controllerStatus"]["activeThreadCount"]
    )


# -- TLS·인증 없는 단일 노드 NiFi 2.6.0 (design/samples/standalone) -----------------

STANDALONE = SAMPLES / "standalone"


def load_standalone(name: str):
    return json.loads((STANDALONE / name).read_text(encoding="utf-8"))


@pytest.mark.skipif(not STANDALONE.is_dir(), reason="design/samples/standalone not present")
def test_standalone_samples(httpserver, client, harness):
    """단일 노드 응답으로 cluster(404 → clustered 0), diagnostics, flow, controller를 돌립니다."""
    httpserver.expect_request("/nifi-api/controller/cluster").respond_with_data(
        "Only a node connected to a cluster can process the request.", status=404
    )
    for path, name in [
        ("/nifi-api/flow/cluster/summary", "cluster_summary.json"),
        ("/nifi-api/system-diagnostics", "system_diagnostics_nodewise.json"),
        ("/nifi-api/flow/process-groups/root/status", "flow_status_recursive.json"),
        ("/nifi-api/controller/config", "controller_config.json"),
        ("/nifi-api/flow/status", "controller_status.json"),
    ]:
        httpserver.expect_request(path).respond_with_json(load_standalone(name))
    registry, store, sm = harness
    for collector in [
        ClusterCollector(client, "s"),
        DiagnosticsCollector(client, "s"),
        FlowCollector(client, "s"),
        ControllerCollector(client, "s"),
    ]:
        assert CollectorRunner(collector, 30, store, sm).run_once(), collector.name
    assert sample(registry, "nifi_cluster_clustered", cluster="s") == 0
    assert sample(registry, "nifi_jvm_heap_used_bytes", cluster="s", node_id="standalone") > 0
    assert sample(registry, "nifi_jvm_uptime_seconds", cluster="s", node_id="standalone") > 0
    assert sample(registry, "nifi_controller_max_timer_driven_threads", cluster="s") > 0
    assert series(registry, "nifi_pg_info")


# -- CFM 4.12.0 SP1 (NiFi 2.6.0.4.12.0.1-9) 2노드, TLS·인증 없음 (design/samples/cfm) -----
# 운영 클러스터 응답을 deploy/local/mask_samples.py로 마스킹한 것입니다(이름·설정·호스트).

CFM = SAMPLES / "cfm"


def load_cfm(name: str):
    return json.loads((CFM / name).read_text(encoding="utf-8"))


@pytest.mark.skipif(not CFM.is_dir(), reason="design/samples/cfm not present")
def test_cfm_samples(httpserver, client, harness):
    """CFM 응답으로 모든 collector를 돌려 모든 컴포넌트가 메트릭이 되는지 확인합니다."""
    for path, name in [
        ("/nifi-api/controller/cluster", "cluster.json"),
        ("/nifi-api/system-diagnostics", "system_diagnostics_nodewise.json"),
        ("/nifi-api/flow/process-groups/root/status", "flow_status_recursive.json"),
        ("/nifi-api/controller/config", "controller_config.json"),
        ("/nifi-api/flow/status", "controller_status.json"),
    ]:
        httpserver.expect_request(path).respond_with_json(load_cfm(name))
    for key, body in load_cfm("flow_process_groups.json").items():
        httpserver.expect_request(f"/nifi-api/flow/process-groups/{key}").respond_with_json(body)
    registry, store, sm = harness
    for collector in [
        ClusterCollector(client, "s", "America/New_York"),
        DiagnosticsCollector(client, "s"),
        FlowCollector(client, "s"),
        TopologyCollector(client, "s"),
        ControllerCollector(client, "s"),
    ]:
        assert CollectorRunner(collector, 30, store, sm).run_once(), collector.name

    assert load_cfm("about.json")["about"]["version"].startswith("2.6.0.4.12.0")
    assert sample(registry, "nifi_cluster_clustered", cluster="s") == 1
    nodes = load_cfm("cluster.json")["cluster"]["nodes"]
    assert sample(registry, "nifi_cluster_nodes_connected", cluster="s") == len(nodes)
    status = load_cfm("flow_status_recursive.json")["processGroupStatus"]["aggregateSnapshot"]
    items = list(walk_status(status))
    for kind, metric, label in [
        ("pg", "nifi_pg_info", "pg_id"),
        ("processor", "nifi_processor_info", "processor_id"),
        ("connection", "nifi_connection_info", "connection_id"),
        ("connection", "nifi_connection_endpoints_info", "connection_id"),
    ]:
        ids = {s["id"] for k, s in items if k == kind}
        assert {s[label] for s in series(registry, metric)} == ids, metric
    for ns in load_cfm("system_diagnostics_nodewise.json")["systemDiagnostics"]["nodeSnapshots"]:
        nid = ns["nodeId"]
        repos = {
            s["repo"] for s in series(registry, "nifi_repo_utilization") if s["node_id"] == nid
        }
        assert repos == {"content", "flowfile", "provenance"}

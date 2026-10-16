import pytest
from werkzeug.wrappers import Response

from nifi_exporter.collectors import (
    ClusterCollector,
    ControllerCollector,
    DiagnosticsCollector,
    FlowCollector,
    TopologyCollector,
)
from nifi_exporter.scheduler import CollectorRunner

from .conftest import fixture, sample


def run(collector, harness, interval=30):
    registry, store, sm = harness
    runner = CollectorRunner(collector, interval, store, sm)
    ok = runner.run_once()
    return ok, registry


# -- cluster -----------------------------------------------------------------


def test_cluster_metrics(nifi, client, harness):
    ok, reg = run(ClusterCollector(client, "test"), harness)
    assert ok
    assert sample(reg, "nifi_cluster_nodes_total", cluster="test") == 2
    assert sample(reg, "nifi_cluster_nodes_connected", cluster="test") == 1
    assert sample(reg, "nifi_node_connected", cluster="test", node_id="node-1-id") == 1
    assert sample(reg, "nifi_node_connected", cluster="test", node_id="node-2-id") == 0
    assert (
        sample(reg, "nifi_node_status", cluster="test", node_id="node-2-id", status="DISCONNECTED")
        == 1
    )
    assert (
        sample(reg, "nifi_node_status", cluster="test", node_id="node-2-id", status="CONNECTED")
        == 0
    )
    assert (
        sample(
            reg,
            "nifi_node_info",
            cluster="test",
            node_id="node-1-id",
            address="nifi-1",
            api_port="8443",
            roles="Cluster Coordinator,Primary Node",
        )
        == 1
    )
    assert sample(reg, "nifi_node_active_threads", cluster="test", node_id="node-1-id") == 3
    # 2.x 숫자 필드가 사람이 읽는 "queued" 문자열보다 우선합니다
    assert sample(reg, "nifi_node_queued_flowfiles", cluster="test", node_id="node-1-id") == 1200
    assert sample(reg, "nifi_node_queued_bytes", cluster="test", node_id="node-1-id") == 3670100
    # 숫자 필드가 없으면 문자열로 대체합니다
    assert sample(reg, "nifi_node_queued_bytes", cluster="test", node_id="node-2-id") == 0
    age = sample(reg, "nifi_node_heartbeat_age_seconds", cluster="test", node_id="node-1-id")
    assert age is not None and age > 0
    assert sample(reg, "nifi_exporter_collector_success", collector="cluster") == 1
    assert sample(reg, "nifi_cluster_clustered", cluster="test") == 1


# -- flow --------------------------------------------------------------------


def test_flow_hierarchy_and_values(nifi, client, harness):
    ok, reg = run(FlowCollector(client, "test", exclude_pg_ids=["pg-excluded"]), harness)
    assert ok
    # 계층을 확인합니다
    assert (
        sample(
            reg,
            "nifi_pg_info",
            cluster="test",
            pg_id="root-id",
            pg_name="NiFi Flow",
            parent_id="",
            pg_path="/",
            depth="0",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_pg_info",
            cluster="test",
            pg_id="pg-ingest",
            pg_name="ingest",
            parent_id="root-id",
            pg_path="/ingest",
            depth="1",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_pg_info",
            cluster="test",
            pg_id="pg-deep",
            pg_name="deep/child",
            parent_id="pg-ingest",
            pg_path="/ingest/deep/child",
            depth="2",
        )
        == 1
    )
    assert sample(reg, "nifi_pg_queued_flowfiles", cluster="test", pg_id="pg-excluded") is None
    # PG 값을 확인합니다
    assert sample(reg, "nifi_pg_queued_flowfiles", cluster="test", pg_id="pg-ingest") == 190
    assert sample(reg, "nifi_pg_queued_bytes", cluster="test", pg_id="pg-ingest") == 786432000
    assert sample(reg, "nifi_pg_flowfiles_in_5m", cluster="test", pg_id="pg-ingest") == 1000
    assert sample(
        reg, "nifi_pg_processing_seconds_5m", cluster="test", pg_id="root-id"
    ) == pytest.approx(2534.2)
    assert (
        sample(reg, "nifi_pg_processors", cluster="test", pg_id="pg-ingest", status="Running") == 1
    )
    assert (
        sample(reg, "nifi_pg_processors", cluster="test", pg_id="pg-ingest", status="Invalid") == 1
    )
    assert (
        sample(reg, "nifi_pg_processors", cluster="test", pg_id="pg-ingest", status="Stopped") == 0
    )
    # Processor를 확인합니다
    assert (
        sample(
            reg,
            "nifi_processor_info",
            cluster="test",
            processor_id="proc-put",
            pg_id="pg-ingest",
            name="PutHDFS",
            type="PutHDFS",
            execution_node="ALL",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_processor_running",
            cluster="test",
            processor_id="proc-put",
            pg_id="pg-ingest",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_processor_running",
            cluster="test",
            processor_id="proc-bad",
            pg_id="pg-ingest",
        )
        == 0
    )
    assert (
        sample(
            reg,
            "nifi_processor_run_status",
            cluster="test",
            processor_id="proc-bad",
            pg_id="pg-ingest",
            status="Invalid",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_processor_run_status",
            cluster="test",
            processor_id="proc-bad",
            pg_id="pg-ingest",
            status="Running",
        )
        == 0
    )
    assert (
        sample(
            reg,
            "nifi_processor_tasks_5m",
            cluster="test",
            processor_id="proc-put",
            pg_id="pg-ingest",
        )
        == 100
    )
    assert sample(
        reg,
        "nifi_processor_tasks_duration_seconds_5m",
        cluster="test",
        processor_id="proc-put",
        pg_id="pg-ingest",
    ) == pytest.approx(60.0)
    assert (
        sample(
            reg,
            "nifi_processor_terminated_threads",
            cluster="test",
            processor_id="proc-put",
            pg_id="pg-ingest",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_processor_bytes_written_5m",
            cluster="test",
            processor_id="proc-gen",
            pg_id="root-id",
        )
        == 1024000
    )
    # Connection을 확인합니다
    assert (
        sample(
            reg,
            "nifi_connection_info",
            cluster="test",
            connection_id="conn-1",
            pg_id="pg-ingest",
            name="success",
            source_name="in",
            destination_name="PutHDFS",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_connection_queued_flowfiles",
            cluster="test",
            connection_id="conn-1",
            pg_id="pg-ingest",
        )
        == 190
    )
    assert (
        sample(
            reg,
            "nifi_connection_percent_used_bytes",
            cluster="test",
            connection_id="conn-1",
            pg_id="pg-ingest",
        )
        == 73
    )
    assert (
        sample(
            reg,
            "nifi_connection_flowfiles_out_5m",
            cluster="test",
            connection_id="conn-1",
            pg_id="pg-ingest",
        )
        == 810
    )


def test_flow_ports_and_remote_groups(nifi, client, harness):
    ok, reg = run(FlowCollector(client, "test"), harness)
    assert ok
    port = {"cluster": "test", "port_id": "port-in", "pg_id": "pg-ingest"}
    assert sample(reg, "nifi_port_info", name="in", direction="input", **port) == 1
    assert sample(reg, "nifi_port_run_status", status="Running", **port) == 1
    assert sample(reg, "nifi_port_flowfiles_out_5m", **port) == 1000
    assert sample(reg, "nifi_port_transmitting", **port) == 0
    out = {"cluster": "test", "port_id": "port-out", "pg_id": "pg-ingest"}
    assert sample(reg, "nifi_port_info", name="out", direction="output", **out) == 1
    assert sample(reg, "nifi_port_run_status", status="Invalid", **out) == 1
    rpg = {"cluster": "test", "rpg_id": "rpg-1", "pg_id": "root-id"}
    assert (
        sample(reg, "nifi_rpg_info", name="dc2", target_uri="https://dc2-nifi:8443/nifi", **rpg)
        == 1
    )
    assert sample(reg, "nifi_rpg_transmitting", **rpg) == 1
    assert sample(reg, "nifi_rpg_flowfiles_sent_5m", **rpg) == 50
    assert sample(reg, "nifi_rpg_bytes_received_5m", **rpg) == 0


def test_topology_endpoints_and_thresholds(nifi, client, harness):
    ok, reg = run(TopologyCollector(client, "test", exclude_pg_ids=["pg-excluded"]), harness)
    assert ok
    assert (
        sample(
            reg,
            "nifi_connection_endpoints_info",
            cluster="test",
            connection_id="conn-1",
            pg_id="pg-ingest",
            source_id="port-in",
            source_type="INPUT_PORT",
            source_group_id="pg-ingest",
            destination_id="proc-put",
            destination_type="PROCESSOR",
            destination_group_id="pg-ingest",
        )
        == 1
    )
    labels = {"cluster": "test", "connection_id": "conn-1", "pg_id": "pg-ingest"}
    assert sample(reg, "nifi_connection_backpressure_object_threshold", **labels) == 10000
    assert sample(reg, "nifi_connection_backpressure_bytes_threshold", **labels) == 1024**3
    # 컴포넌트 read 권한이 없어도 양 끝은 알 수 있고, 임계치는 없습니다
    assert (
        sample(
            reg,
            "nifi_connection_endpoints_info",
            cluster="test",
            connection_id="conn-2",
            pg_id="pg-ingest",
            source_id="proc-put",
            source_type="PROCESSOR",
            source_group_id="pg-ingest",
            destination_id="port-out",
            destination_type="OUTPUT_PORT",
            destination_group_id="pg-ingest",
        )
        == 1
    )
    assert (
        sample(
            reg,
            "nifi_connection_backpressure_object_threshold",
            cluster="test",
            connection_id="conn-2",
            pg_id="pg-ingest",
        )
        is None
    )
    # 제외하지 않은 그룹은 한 번씩 가져오고, 제외한 그룹은 가져오지 않습니다
    paths = [req.path for req, _ in nifi.log]
    assert paths.count("/nifi-api/flow/process-groups/pg-deep") == 1
    assert "/nifi-api/flow/process-groups/pg-excluded" not in paths


def test_topology_missing_flow_fails(httpserver, client, harness):
    httpserver.expect_request("/nifi-api/flow/process-groups/root").respond_with_json({})
    ok, reg = run(TopologyCollector(client, "test"), harness)
    assert not ok
    assert sample(reg, "nifi_exporter_collector_success", collector="topology") == 0


def test_flow_missing_snapshot_fails(httpserver, client, harness):
    httpserver.expect_request("/nifi-api/flow/process-groups/root/status").respond_with_json(
        {"processGroupStatus": {}}
    )
    ok, reg = run(FlowCollector(client, "test"), harness)
    assert not ok
    assert sample(reg, "nifi_exporter_collector_success", collector="flow") == 0


# -- diagnostics -------------------------------------------------------------


def test_diagnostics_nodewise(nifi, client, harness):
    ok, reg = run(DiagnosticsCollector(client, "test"), harness)
    assert ok
    assert sample(reg, "nifi_jvm_heap_used_bytes", cluster="test", node_id="node-1-id") == 2e9
    assert sample(reg, "nifi_jvm_heap_utilization", cluster="test", node_id="node-1-id") == 0.5
    assert sample(reg, "nifi_jvm_heap_utilization", cluster="test", node_id="node-2-id") == 0.25
    assert (
        sample(
            reg,
            "nifi_jvm_gc_collections_total",
            cluster="test",
            node_id="node-1-id",
            collector="G1 Old Generation",
        )
        == 3
    )
    assert (
        sample(
            reg,
            "nifi_jvm_gc_seconds_total",
            cluster="test",
            node_id="node-1-id",
            collector="G1 Young Generation",
        )
        == 18.0
    )
    assert (
        sample(
            reg,
            "nifi_repo_utilization",
            cluster="test",
            node_id="node-1-id",
            repo="content",
            repo_id="default",
        )
        == 0.9
    )
    assert (
        sample(
            reg,
            "nifi_repo_used_bytes",
            cluster="test",
            node_id="node-1-id",
            repo="flowfile",
            repo_id="default",
        )
        == 1e10
    )
    assert (
        sample(
            reg,
            "nifi_repo_total_bytes",
            cluster="test",
            node_id="node-1-id",
            repo="provenance",
            repo_id="default",
        )
        == 1e11
    )
    assert sample(reg, "nifi_system_load_average", cluster="test", node_id="node-2-id") == 1.0
    # nodeSnapshots가 있으면 aggregate가 노드처럼 섞여 들어오면 안 됩니다
    assert sample(reg, "nifi_jvm_heap_used_bytes", cluster="test", node_id="standalone") is None


def test_diagnostics_standalone(httpserver, client, harness):
    body = fixture("system_diagnostics.json")
    body["systemDiagnostics"].pop("nodeSnapshots")
    httpserver.expect_request("/nifi-api/system-diagnostics").respond_with_json(body)
    ok, reg = run(DiagnosticsCollector(client, "test"), harness)
    assert ok
    assert sample(reg, "nifi_jvm_heap_used_bytes", cluster="test", node_id="standalone") == 3e9
    assert (
        sample(
            reg,
            "nifi_repo_utilization",
            cluster="test",
            node_id="standalone",
            repo="flowfile",
            repo_id="default",
        )
        == 0.1
    )


# -- 실패 처리 -------------------------------------------------------


def test_failure_drops_previous_snapshot(httpserver, client, harness):
    state = {"fail": False}

    def handler(_req):
        if state["fail"]:
            return Response("down", status=503)
        import json

        return Response(json.dumps(fixture("cluster.json")), content_type="application/json")

    httpserver.expect_request("/nifi-api/controller/cluster").respond_with_handler(handler)
    registry, store, sm = harness
    runner = CollectorRunner(ClusterCollector(client, "test"), 15, store, sm)
    assert runner.run_once()
    assert sample(registry, "nifi_cluster_nodes_total", cluster="test") == 2
    state["fail"] = True
    assert not runner.run_once()
    assert sample(registry, "nifi_cluster_nodes_total", cluster="test") is None, (
        "stale values must not be served"
    )
    assert sample(registry, "nifi_exporter_collector_success", collector="cluster") == 0
    assert (
        sample(
            registry, "nifi_exporter_collector_last_success_timestamp_seconds", collector="cluster"
        )
        > 0
    )


# -- 단일 노드(비클러스터)와 끊긴 노드 ----------------------------------------------


def _cluster_404(httpserver, clustered: bool):
    httpserver.expect_request("/nifi-api/controller/cluster").respond_with_data(
        "Only a node connected to a cluster can process the request.", status=404
    )
    httpserver.expect_request("/nifi-api/flow/cluster/summary").respond_with_json(
        {"clusterSummary": {"clustered": clustered, "connectedToCluster": False}}
    )


def test_cluster_standalone_is_not_a_failure(httpserver, client, harness):
    _cluster_404(httpserver, clustered=False)
    ok, reg = run(ClusterCollector(client, "test"), harness)
    assert ok
    assert sample(reg, "nifi_cluster_clustered", cluster="test") == 0
    assert sample(reg, "nifi_cluster_nodes_total", cluster="test") is None


def test_cluster_disconnected_node_fails(httpserver, client, harness):
    _cluster_404(httpserver, clustered=True)
    ok, reg = run(ClusterCollector(client, "test"), harness)
    assert not ok
    assert sample(reg, "nifi_exporter_collector_success", collector="cluster") == 0


# -- controller (스레드 풀) --------------------------------------------------------


def test_controller_thread_pool(nifi, client, harness):
    ok, reg = run(ControllerCollector(client, "test"), harness)
    assert ok
    assert sample(reg, "nifi_controller_max_timer_driven_threads", cluster="test") == 10
    assert sample(reg, "nifi_controller_active_threads", cluster="test") == 7
    assert sample(reg, "nifi_controller_terminated_threads", cluster="test") == 1


def test_diagnostics_heap_committed_and_uptime(nifi, client, harness):
    ok, reg = run(DiagnosticsCollector(client, "test"), harness)
    assert ok
    n1 = {"cluster": "test", "node_id": "node-1-id"}
    assert sample(reg, "nifi_jvm_heap_committed_bytes", **n1) == 3e9
    assert sample(reg, "nifi_jvm_nonheap_committed_bytes", **n1) == 3e8
    assert sample(reg, "nifi_jvm_uptime_seconds", **n1) == 26 * 3600 + 62.5


def test_failed_collector_retries_sooner(httpserver, client, harness):
    """주기가 긴 collector도 실패하면 30초 뒤 다시 시도합니다(짧은 주기는 그대로)."""
    registry, store, sm = harness
    slow = CollectorRunner(ClusterCollector(client, "test"), 300, store, sm)
    fast = CollectorRunner(ClusterCollector(client, "test"), 15, store, sm)
    assert slow.next_delay(ok=True) == 300
    assert slow.next_delay(ok=False) == 30
    assert fast.next_delay(ok=False) == 15

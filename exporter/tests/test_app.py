import httpx
from prometheus_client import generate_latest

from nifi_exporter import config
from nifi_exporter.app import Exporter


def _cfg(base_url: str) -> config.Config:
    return config.from_dict(
        {
            "nifi": {
                "base_url": base_url,
                "cluster_name": "e2e",
                "auth": {"mode": "none"},
                "retry_backoff": "10ms",
            },
            "collectors": {"bulletin": {"enabled": False}},
            "server": {"listen": "127.0.0.1:0", "log_format": "text"},
        }
    )


def test_exporter_end_to_end(nifi, monkeypatch):
    monkeypatch.delenv("NIFI_USERNAME", raising=False)
    monkeypatch.delenv("NIFI_PASSWORD", raising=False)
    ex = Exporter(_cfg(nifi.url_for("").rstrip("/")))
    assert [r.collector.name for r in ex.runners] == [
        "cluster",
        "flow",
        "diagnostics",
        "controller",
        "topology",
    ]
    assert not ex.ready()

    for r in ex.runners:
        assert r.run_once()
    assert ex.ready()

    text = generate_latest(ex.registry).decode()
    assert 'nifi_cluster_nodes_connected{cluster="e2e"} 1.0' in text
    assert (
        'nifi_connection_queued_flowfiles{cluster="e2e",connection_id="conn-1",pg_id="pg-ingest"} 190.0'
        in text
    )
    assert (
        'nifi_repo_utilization{cluster="e2e",node_id="node-1-id",repo="content",repo_id="default"} 0.9'
        in text
    )
    assert 'nifi_exporter_collector_success{collector="flow"} 1.0' in text
    assert 'nifi_controller_max_timer_driven_threads{cluster="e2e"} 10.0' in text
    assert (
        'nifi_connection_backpressure_object_threshold{cluster="e2e",connection_id="conn-1"' in text
    )
    assert 'nifi_exporter_build_info{version="0.1.0"} 1.0' in text
    assert "process_cpu_seconds_total" in text
    assert "nifi_exporter_api_requests_total" in text
    assert 'nifi_exporter_api_response_bytes{endpoint="flow_status_recursive"}' in text

    # 임시 포트에서 실제 HTTP 서버를 띄웁니다
    ex.start()
    try:
        base = f"http://127.0.0.1:{ex.server.port}"
        assert httpx.get(f"{base}/healthz").status_code == 200
        assert httpx.get(f"{base}/readyz").status_code == 200
        body = httpx.get(f"{base}/metrics").text
        assert "nifi_pg_queued_flowfiles" in body
        assert httpx.get(f"{base}/nope").status_code == 404
    finally:
        ex.stop()


def test_readyz_503_before_first_success(nifi, monkeypatch):
    monkeypatch.delenv("NIFI_USERNAME", raising=False)
    monkeypatch.delenv("NIFI_PASSWORD", raising=False)
    cfg = _cfg("http://127.0.0.1:9")  # 접근할 수 없는 NiFi입니다
    cfg.collectors.cluster.enabled = False
    cfg.collectors.diagnostics.enabled = False
    cfg.nifi.timeout = 0.3
    cfg.nifi.retries = 0
    ex = Exporter(cfg)
    ex.server = None
    from nifi_exporter.server import HTTPServer

    ex.server = HTTPServer("127.0.0.1", 0, ex.registry, ex.ready)
    ex.server.start()
    try:
        assert httpx.get(f"http://127.0.0.1:{ex.server.port}/readyz").status_code == 503
    finally:
        ex.server.stop()
        ex.client.close()


def test_metrics_basic_auth(nifi, monkeypatch):
    monkeypatch.delenv("NIFI_USERNAME", raising=False)
    monkeypatch.delenv("NIFI_PASSWORD", raising=False)
    monkeypatch.setenv("NIFI_EXPORTER_BASIC_AUTH_PASSWORD", "pw")
    raw_cfg = _cfg(nifi.url_for("").rstrip("/"))
    raw_cfg.server.basic_auth = config.BasicAuthConfig(username="prom", password="pw")
    ex = Exporter(raw_cfg)
    ex.start()
    try:
        base = f"http://127.0.0.1:{ex.server.port}"
        r = httpx.get(f"{base}/metrics")
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"].startswith("Basic")
        assert httpx.get(f"{base}/metrics", auth=("prom", "wrong")).status_code == 401
        assert httpx.get(f"{base}/metrics", auth=("other", "pw")).status_code == 401
        assert httpx.get(f"{base}/metrics", auth=("prom", "pw")).status_code == 200
        assert httpx.get(f"{base}/", auth=("prom", "pw")).status_code == 200
        assert httpx.get(f"{base}/").status_code == 401
        # 프로브는 열려 있어야 합니다
        assert httpx.get(f"{base}/healthz").status_code == 200
        assert httpx.get(f"{base}/readyz").status_code in (200, 503)
        bad = httpx.get(f"{base}/metrics", headers={"Authorization": "Basic !!notb64"})
        assert bad.status_code == 401
    finally:
        ex.stop()

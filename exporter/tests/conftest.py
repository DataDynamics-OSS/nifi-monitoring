from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx
import pytest
from prometheus_client import CollectorRegistry
from pytest_httpserver import HTTPServer

from nifi_exporter.metrics import SelfMetrics, SnapshotStore
from nifi_exporter.nifi import NiFiClient, NoAuth

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_jwt(exp: float | None = None, sub: str = "nifi-monitor") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    claims = {"sub": sub}
    if exp is not None:
        claims["exp"] = int(exp)
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


@pytest.fixture
def nifi(httpserver: HTTPServer) -> HTTPServer:
    """표준 엔드포인트에서 fixture 응답을 돌려주는 가짜 NiFi입니다."""
    httpserver.expect_request("/nifi-api/controller/cluster").respond_with_json(
        fixture("cluster.json")
    )
    httpserver.expect_request(
        "/nifi-api/flow/process-groups/root/status", query_string={"recursive": "true"}
    ).respond_with_json(fixture("flow_status.json"))
    httpserver.expect_request(
        "/nifi-api/system-diagnostics", query_string={"nodewise": "true"}
    ).respond_with_json(fixture("system_diagnostics.json"))
    httpserver.expect_request("/nifi-api/controller/config").respond_with_json(
        fixture("controller_config.json")
    )
    httpserver.expect_request("/nifi-api/flow/status").respond_with_json(
        fixture("controller_status.json")
    )
    for pg_id, body in fixture("flow_topology.json").items():
        httpserver.expect_request(f"/nifi-api/flow/process-groups/{pg_id}").respond_with_json(body)
    return httpserver


@pytest.fixture
def client(httpserver: HTTPServer) -> NiFiClient:
    http = httpx.Client(timeout=5.0)
    c = NiFiClient(
        http, httpserver.url_for("").rstrip("/"), NoAuth(), retries=1, retry_backoff=0.01
    )
    yield c
    c.close()


@pytest.fixture
def harness():
    """실제 앱이 연결하는 것과 같은 registry + store + 자체 메트릭입니다."""
    registry = CollectorRegistry()
    store = SnapshotStore()
    registry.register(store)
    sm = SelfMetrics(registry)
    return registry, store, sm


def sample(registry: CollectorRegistry, metric: str, **labels) -> float | None:
    return registry.get_sample_value(metric, labels or None)


def now() -> float:
    return time.time()

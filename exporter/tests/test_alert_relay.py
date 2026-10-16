import base64
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from prometheus_client import CollectorRegistry

from nifi_exporter.alert_relay import (
    ConfigError,
    Relay,
    config_from_dict,
    make_app,
    render,
)

FIRING = {
    "status": "firing",
    "labels": {
        "alertname": "NiFiQueueBackpressureEngaged",
        "severity": "critical",
        "cluster": "cfm",
        "connection_id": "c1",
        "pg_id": "p1",
    },
    "annotations": {"summary": "큐 Backpressure 발동", "description": "a → b"},
    "startsAt": "2026-10-15T10:00:00Z",
    "endsAt": "0001-01-01T00:00:00Z",
    "generatorURL": "http://prom/graph",
    "fingerprint": "f1",
}
WARNING = {
    **FIRING,
    "labels": {**FIRING["labels"], "alertname": "NiFiQueueGrowing", "severity": "warning"},
    "fingerprint": "f2",
}
RESOLVED = {**FIRING, "status": "resolved", "endsAt": "2026-10-15T10:05:00Z", "fingerprint": "f3"}


def notification(*alerts, status="firing"):
    return {
        "version": "4",
        "groupKey": '{}:{alertname="x"}',
        "status": status,
        "receiver": "custom-relay",
        "groupLabels": {"alertname": "x"},
        "commonLabels": {"cluster": "cfm"},
        "commonAnnotations": {},
        "externalURL": "http://am",
        "alerts": list(alerts),
    }


class Recorder:
    """대상 HTTP 서버 대신 요청을 기록하고, 정한 상태 코드를 차례로 돌려줍니다."""

    def __init__(self, *codes):
        self.codes = list(codes)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        code = self.codes.pop(0) if self.codes else 200
        return httpx.Response(code, text="ok" if code < 300 else "boom")

    def bodies(self, host=None):
        return [json.loads(r.content) for r in self.requests if host is None or r.url.host == host]


def make_relay(targets, recorder, **extra):
    cfg = config_from_dict({"targets": targets, **extra})
    clock = {"t": 0.0}
    relay = Relay(
        cfg,
        CollectorRegistry(),
        sleep=lambda s: None,
        clock=lambda: clock["t"],
        transport=httpx.MockTransport(recorder),
    )
    return relay, clock


def test_config_log_file():
    target = [{"name": "a", "url": "http://x"}]
    cfg = config_from_dict({"targets": target})
    assert (cfg.log_file, cfg.log_max_size, cfg.log_backups) == (None, 50 * 1024**2, 5)
    cfg = config_from_dict(
        {"targets": target, "log_file": "logs/r.log", "log_max_size": "1 MB", "log_backups": 0}
    )
    assert (cfg.log_file, cfg.log_max_size, cfg.log_backups) == ("logs/r.log", 1024**2, 0)
    with pytest.raises(ConfigError, match="log_max_size"):
        config_from_dict({"targets": target, "log_max_size": 0})


def test_config_validation(monkeypatch):
    with pytest.raises(ConfigError, match="at least one target"):
        config_from_dict({})
    with pytest.raises(ConfigError, match="name and url"):
        config_from_dict({"targets": [{"name": "a"}]})
    with pytest.raises(ConfigError, match="mode"):
        config_from_dict({"targets": [{"name": "a", "url": "http://x", "mode": "batch"}]})
    with pytest.raises(ConfigError, match="duplicate"):
        config_from_dict({"targets": [{"name": "a", "url": "http://x"}] * 2})
    with pytest.raises(ConfigError, match="OPS_TOKEN"):
        config_from_dict(
            {"targets": [{"name": "a", "url": "http://x", "headers": {"A": "Bearer ${OPS_TOKEN}"}}]}
        )
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    cfg = config_from_dict(
        {"targets": [{"name": "a", "url": "http://x", "headers": {"A": "Bearer ${OPS_TOKEN}"}}]}
    )
    assert cfg.targets[0].headers == {"A": "Bearer s3cret"}
    assert cfg.targets[0].method == "POST" and cfg.targets[0].mode == "alert"


def test_render_fills_fields_and_objects():
    fields = {
        "alertname": "X",
        "labels": {"pg_id": "p1"},
        "alerts": [1, 2],
    }

    class Blank(dict):
        def __missing__(self, k):
            return ""

    fields = Blank(fields)
    fields["labels"] = Blank(fields["labels"])
    out = render(
        {
            "title": "[{alertname}] {labels[pg_id]} {labels[nope]} {missing}",
            "items": "{alerts}",
            "literal": "a {broken",
            "n": 3,
            "list": ["{alertname}"],
        },
        fields,
    )
    assert out == {
        "title": "[X] p1  ",
        "items": [1, 2],
        "literal": "a {broken",
        "n": 3,
        "list": ["X"],
    }


def test_alert_mode_template_and_filters():
    rec = Recorder()
    relay, _ = make_relay(
        [
            {
                "name": "ops",
                "url": "http://ops/api",
                "headers": {"X-Key": "k"},
                "match": {"severity": ["critical"]},
                "send_resolved": False,
                "payload": {
                    "title": "[{status}] {alertname} ({cluster})",
                    "message": "{summary}",
                    "pg": "{labels[pg_id]}",
                    "labels": "{labels}",
                },
            }
        ],
        rec,
    )
    assert relay.handle(notification(FIRING, WARNING, RESOLVED)) == []
    # warning은 match에서, resolved는 send_resolved: false에서 빠집니다
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.method == "POST" and req.headers["X-Key"] == "k"
    assert req.headers["Content-Type"] == "application/json"
    assert json.loads(req.content) == {
        "title": "[firing] NiFiQueueBackpressureEngaged (cfm)",
        "message": "큐 Backpressure 발동",
        "pg": "p1",
        "labels": FIRING["labels"],
    }


def test_group_mode_raw_and_template():
    rec = Recorder()
    relay, _ = make_relay(
        [
            {"name": "raw", "url": "http://raw/", "mode": "group"},
            {
                "name": "summary",
                "url": "http://summary/",
                "mode": "group",
                "method": "PUT",
                "payload": {
                    "text": "{count}건 (발화 {firing}, 해소 {resolved})",
                    "alerts": "{alerts}",
                },
            },
        ],
        rec,
    )
    assert relay.handle(notification(FIRING, RESOLVED)) == []
    raw = rec.bodies("raw")
    assert len(raw) == 1 and raw[0]["groupKey"] and len(raw[0]["alerts"]) == 2
    summary = rec.bodies("summary")[0]
    assert summary["text"] == "2건 (발화 1, 해소 1)"
    assert [a["fingerprint"] for a in summary["alerts"]] == ["f1", "f3"]
    assert [r.method for r in rec.requests if r.url.host == "summary"] == ["PUT"]


def test_retries_then_reports_failure_and_dedupes_successes():
    rec_codes = Recorder(503, 503, 503, 200)
    relay, clock = make_relay(
        [
            {"name": "flaky", "url": "http://flaky/", "retries": 2},
            {"name": "good", "url": "http://good/"},
        ],
        rec_codes,
    )
    # flaky: 503 세 번(첫 시도 + 재시도 2번) → 실패. good: 200
    assert relay.handle(notification(FIRING)) == ["flaky"]
    hosts = [r.url.host for r in rec_codes.requests]
    assert hosts == ["flaky", "flaky", "flaky", "good"]
    # Alertmanager가 다시 보내면 good은 건너뛰고 flaky만 다시 보냅니다
    assert relay.handle(notification(FIRING)) == []
    assert [r.url.host for r in rec_codes.requests][4:] == ["flaky"]
    reg = relay.registry
    assert (
        reg.get_sample_value(
            "nifi_alert_relay_deliveries_total", {"target": "good", "result": "duplicate"}
        )
        == 1
    )
    assert (
        reg.get_sample_value(
            "nifi_alert_relay_deliveries_total", {"target": "flaky", "result": "failed"}
        )
        == 1
    )
    # 중복 방지 기간이 지나면 다시 보냅니다(Alertmanager의 반복 통지)
    clock["t"] = 301
    relay.handle(notification(FIRING))
    assert [r.url.host for r in rec_codes.requests][5:] == ["flaky", "good"]


def test_client_errors_are_not_retried():
    rec = Recorder(400)
    relay, _ = make_relay([{"name": "a", "url": "http://a/", "retries": 3}], rec)
    assert relay.handle(notification(FIRING)) == ["a"]
    assert len(rec.requests) == 1


@pytest.mark.parametrize("first_code", [200, 503])
@pytest.mark.parametrize("mode", ["alert", "group"])
def test_concurrent_duplicate_is_not_sent_or_acknowledged_early(first_code, mode):
    entered, release = threading.Event(), threading.Event()
    requests = []

    def transport(request):
        requests.append(request)
        if len(requests) == 1:
            entered.set()
            assert release.wait(5)
            return httpx.Response(first_code)
        return httpx.Response(200)

    relay, _ = make_relay(
        [{"name": "ops", "url": "http://ops/", "retries": 0, "mode": mode}], transport
    )
    app = make_app(relay)
    msg = notification(FIRING)
    try:
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(_call, app, "/alerts", msg)
            try:
                assert entered.wait(5)
                # 진행 중인 전송을 성공으로 ACK하면 첫 전송 실패 시 알림이 유실됩니다.
                assert _call(app, "/alerts", msg)[0] == 502
                assert len(requests) == 1
                # 다른 키는 느린 요청이 끝나기 전에도 전송할 수 있습니다.
                assert _call(app, "/alerts", notification(WARNING))[0] == 200
            finally:
                release.set()
            assert first.result(timeout=5)[0] == (200 if first_code == 200 else 502)
        assert _call(app, "/alerts", msg)[0] == 200
        assert len(requests) == (2 if first_code == 200 else 3)
    finally:
        relay.close()


def test_unexpected_delivery_error_releases_in_flight_key():
    calls = []

    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            raise RuntimeError("unexpected delivery failure")
        return httpx.Response(200)

    relay, _ = make_relay([{"name": "ops", "url": "http://ops/"}], transport)
    try:
        with pytest.raises(RuntimeError):
            relay.handle(notification(FIRING))
        assert relay.handle(notification(FIRING)) == []
        assert len(calls) == 2
    finally:
        relay.close()


@pytest.mark.parametrize("templated", [False, True])
@pytest.mark.parametrize("status", ["resolved", "firing"])
def test_filtered_group_recomputes_status_and_common_fields(templated, status):
    rec = Recorder()
    target = {"name": "ops", "url": "http://ops/", "mode": "group", "match": {"status": status}}
    if templated:
        target["payload"] = {
            "status": "{status}",
            "commonLabels": "{commonLabels}",
            "commonAnnotations": "{annotations}",
            "alerts": "{alerts}",
        }
    relay, _ = make_relay([target], rec)
    msg = notification(WARNING, RESOLVED)
    try:
        assert relay.handle(msg) == []
        body = rec.bodies()[0]
        chosen = RESOLVED if status == "resolved" else WARNING
        assert body["status"] == status
        assert body["alerts"] == [chosen]
        assert body["commonLabels"] == chosen["labels"]
        assert body["commonAnnotations"] == chosen["annotations"]
        assert msg["status"] == "firing" and msg["alerts"] == [WARNING, RESOLVED]
    finally:
        relay.close()


def test_group_common_fields_are_intersection_of_selected_alerts():
    rec = Recorder()
    relay, _ = make_relay([{"name": "ops", "url": "http://ops/", "mode": "group"}], rec)
    other = {**RESOLVED, "annotations": {"summary": "different", "description": "a → b"}}
    try:
        assert relay.handle(notification(WARNING, other)) == []
        body = rec.bodies()[0]
        assert body["status"] == "firing"
        assert body["commonLabels"] == {"cluster": "cfm", "connection_id": "c1", "pg_id": "p1"}
        assert body["commonAnnotations"] == {"description": "a → b"}
    finally:
        relay.close()


def _call(app, path, body=None, method="POST", auth=None):
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    environ = {
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    if auth:
        environ["HTTP_AUTHORIZATION"] = "Basic " + base64.b64encode(auth.encode()).decode()
    out = {}

    def start_response(status, headers):
        out["code"] = int(status.split()[0])

    text = b"".join(app(environ, start_response)).decode()
    return out["code"], text


def test_http_endpoint():
    rec = Recorder(500, 500, 500)
    relay, _ = make_relay([{"name": "a", "url": "http://a/"}], rec)
    app = make_app(relay, basic_auth=("alertmanager", "pw"))
    assert _call(app, "/healthz", method="GET")[0] == 200
    assert _call(app, "/alerts", notification(FIRING))[0] == 401
    auth = "alertmanager:pw"
    assert _call(app, "/alerts", b"{not json", auth=auth)[0] == 400
    assert _call(app, "/alerts", method="GET", auth=auth)[0] == 405
    code, text = _call(app, "/alerts", notification(FIRING), auth=auth)
    assert code == 502 and "a" in text
    assert _call(app, "/alerts", notification(FIRING), auth=auth)[0] == 200
    code, metrics = _call(app, "/metrics", method="GET", auth=auth)
    assert code == 200
    assert 'nifi_alert_relay_notifications_total{result="partial_failure"} 1.0' in metrics
    assert 'nifi_alert_relay_alerts_total{target="a"} 1.0' in metrics

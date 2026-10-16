import base64
import io
import json

import pytest

from nifi_exporter import config
from nifi_exporter.provenance import (
    ProvenanceQuery,
    QueryError,
    QueryRequest,
    make_app,
    parse_request,
    render_html,
)

from .conftest import fixture

PID = "3e101a53-01a1-1000-ffff-ffffb97c8c1c"
QID = "3eda9878-01a1-1000-ffff-ffffac4d9953"


def _cfg(**overrides) -> config.ProvenanceConfig:
    raw = {"max_range": "1h", "default_window": "5m", "max_results": 1000, **overrides}
    cfg = config.from_dict({"nifi": {"auth": {"mode": "none"}}, "provenance": raw})
    return cfg.provenance


# -- 요청 검증 -------------------------------------------------------------------


def test_requires_processor_id_and_range():
    cfg = _cfg()
    with pytest.raises(QueryError, match="processor_id"):
        parse_request({"at": "1000"}, cfg, "c")
    with pytest.raises(QueryError, match="processor_id"):
        parse_request({"processor_id": "not-a-uuid", "at": "1000"}, cfg, "c")
    with pytest.raises(QueryError, match="시간 범위"):
        parse_request({"processor_id": PID}, cfg, "c")
    with pytest.raises(QueryError, match="시간 범위"):
        parse_request({"processor_id": PID, "from": "1000"}, cfg, "c")
    with pytest.raises(QueryError, match="늦어야"):
        parse_request({"processor_id": PID, "from": "2000", "to": "1000"}, cfg, "c")


def test_at_uses_window_and_epoch_millis():
    req = parse_request({"processor_id": PID.upper(), "at": "1800000000000"}, _cfg(), "c")
    assert req.processor_id == PID
    assert (req.start, req.end) == (1800000000 - 300, 1800000000)
    req = parse_request({"processor_id": PID, "at": "1800000000000", "window": "1m"}, _cfg(), "c")
    assert req.start == 1800000000 - 60


def test_from_to_iso_and_clamp_to_max_range():
    req = parse_request(
        {"processor_id": PID, "from": "2026-10-15T00:00:00Z", "to": "2026-10-15T03:00:00+00:00"},
        _cfg(),
        "c",
    )
    assert req.clamped
    assert req.end - req.start == 3600
    req = parse_request(
        {"processor_id": PID, "from": "2026-10-15T00:00:00", "to": "2026-10-15T00:10:00"},
        _cfg(),
        "c",
    )
    assert not req.clamped and req.end - req.start == 600


def test_cluster_mismatch_and_max_results_cap():
    with pytest.raises(QueryError, match="prod"):
        parse_request({"processor_id": PID, "at": "1000", "cluster": "prod"}, _cfg(), "local")
    req = parse_request(
        {"processor_id": PID, "at": "1000", "cluster": "local", "max_results": "99999"},
        _cfg(),
        "local",
    )
    assert req.max_results == 1000
    with pytest.raises(QueryError, match="max_results"):
        parse_request({"processor_id": PID, "at": "1000", "max_results": "x"}, _cfg(), "c")


def test_config_validation():
    with pytest.raises(config.ConfigError, match="default_window"):
        _cfg(default_window="2h")
    with pytest.raises(config.ConfigError, match="max_results"):
        _cfg(max_results=0)
    with pytest.raises(config.ConfigError, match="provenance.listen"):
        _cfg(listen="nope")


# -- NiFi 질의 -------------------------------------------------------------------


def _expect_nifi(httpserver, finished_after_polls: int = 1):
    """POST는 미완료 상태를, GET은 finished_after_polls번째부터 실제 2.6.0 응답을 돌려줍니다."""
    done = fixture("provenance.json")
    pending = json.loads(json.dumps(done))
    pending["provenance"].update(finished=False, percentCompleted=40, results={})
    httpserver.expect_request("/nifi-api/provenance", method="POST").respond_with_json(
        pending, status=201
    )
    for _ in range(finished_after_polls - 1):
        httpserver.expect_oneshot_request(
            f"/nifi-api/provenance/{QID}", method="GET"
        ).respond_with_json(pending)
    httpserver.expect_request(f"/nifi-api/provenance/{QID}", method="GET").respond_with_json(done)
    httpserver.expect_request(f"/nifi-api/provenance/{QID}", method="DELETE").respond_with_json(
        done
    )


def _methods(httpserver) -> list[str]:
    return [req.method for req, _ in httpserver.log]


def test_query_polls_until_finished_and_deletes(httpserver, client):
    _expect_nifi(httpserver, finished_after_polls=2)
    sleeps = []
    q = ProvenanceQuery(client, _cfg(), sleep=sleeps.append)
    result = q.run(QueryRequest(PID, 1800000000.5, 1800000059.5, 100))

    assert _methods(httpserver) == ["POST", "GET", "GET", "DELETE"]
    body = json.loads(httpserver.log[0][0].data)["provenance"]["request"]
    assert body["searchTerms"] == {"ProcessorID": {"value": PID, "inverse": False}}
    assert body["summarize"] is True and body["maxResults"] == 100
    # 초 단위로 바깥쪽 반올림합니다
    assert body["startDate"] == "01/15/2027 08:00:00 UTC"
    assert body["endDate"] == "01/15/2027 08:01:00 UTC"
    assert sleeps == [1.0, 1.0]

    assert len(result["events"]) == 2
    ev = result["events"][0]
    assert ev["componentName"] == "log-error" and ev["componentId"] == PID
    assert "previousAttributes" not in ev and "updatedAttributes" not in ev
    assert result["start"] == "2027-01-15T08:00:00Z"
    assert not result["truncated"]


def test_query_timeout_still_deletes(httpserver, client):
    pending = fixture("provenance.json")
    pending["provenance"].update(finished=False, percentCompleted=10, results={})
    httpserver.expect_request("/nifi-api/provenance", method="POST").respond_with_json(pending)
    httpserver.expect_request(f"/nifi-api/provenance/{QID}", method="GET").respond_with_json(
        pending
    )
    httpserver.expect_request(f"/nifi-api/provenance/{QID}", method="DELETE").respond_with_data("")
    ticks = iter(range(0, 1000, 30))
    q = ProvenanceQuery(client, _cfg(), sleep=lambda s: None, clock=lambda: next(ticks))
    with pytest.raises(QueryError) as e:
        q.run(QueryRequest(PID, 0, 60, 10))
    assert e.value.status == 504 and "10%" in e.value.message
    assert _methods(httpserver)[-1] == "DELETE"


def test_permission_denied_is_explained(httpserver, client):
    httpserver.expect_request("/nifi-api/provenance", method="POST").respond_with_data(
        "No applicable policies could be found.", status=403
    )
    with pytest.raises(QueryError) as e:
        ProvenanceQuery(client, _cfg()).run(QueryRequest(PID, 0, 60, 10))
    assert e.value.status == 502 and "view provenance" in e.value.message
    assert _methods(httpserver) == ["POST"]  # 질의가 만들어지지 않았으므로 DELETE도 없습니다


# -- HTTP ------------------------------------------------------------------------


def _call(app, path: str, query: str = "", auth: str | None = None):
    environ = {
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "REQUEST_METHOD": "GET",
        "wsgi.input": io.BytesIO(),
    }
    if auth:
        environ["HTTP_AUTHORIZATION"] = "Basic " + base64.b64encode(auth.encode()).decode()
    status = {}

    def start_response(s, headers):
        status["s"] = s
        status["h"] = dict(headers)

    body = b"".join(app(environ, start_response))
    return int(status["s"].split()[0]), status["h"], body.decode()


class FakeQuery:
    def __init__(self, result=None, on_run=None):
        self.result = result
        self.on_run = on_run
        self.requests = []

    def run(self, req):
        self.requests.append(req)
        if self.on_run:
            self.on_run()
        return self.result


RESULT = {
    "processor_id": PID,
    "start": "2026-10-15T09:00:00Z",
    "end": "2026-10-15T09:05:00Z",
    "clamped": True,
    "max_results": 2,
    "total": "2+",
    "truncated": True,
    "oldest_event": None,
    "errors": [],
    "events": [
        {"eventType": "DROP", "componentName": "<script>x</script>", "fileSizeBytes": 0},
    ],
}


def test_app_json_html_and_errors():
    q = FakeQuery(RESULT)
    app = make_app("local", _cfg(), q)
    code, headers, body = _call(app, "/provenance", f"processor_id={PID}&at=1000&format=json")
    assert code == 200 and headers["Content-Type"] == "application/json"
    assert json.loads(body)["events"][0]["eventType"] == "DROP"

    code, headers, body = _call(app, "/provenance", f"processor_id={PID}&at=1000")
    assert code == 200 and headers["Content-Type"].startswith("text/html")
    assert "&lt;script&gt;" in body and "<script>" not in body
    assert "줄였습니다" in body and "최대 2건" in body
    assert "<td>0</td>" in body  # 크기 0은 빈칸이 아니라 0입니다

    code, _, body = _call(app, "/provenance", "at=1000&format=json")
    assert code == 400 and "processor_id" in json.loads(body)["error"]
    assert len(q.requests) == 2
    assert _call(app, "/nope")[0] == 404
    assert _call(app, "/")[0] == 200


def test_app_rejects_over_concurrency():
    inner = {}
    app = None

    def reenter():
        inner["code"] = _call(app, "/provenance", f"processor_id={PID}&at=1000&format=json")[0]

    app = make_app("local", _cfg(max_concurrent=1), FakeQuery(RESULT, on_run=reenter))
    assert _call(app, "/provenance", f"processor_id={PID}&at=1000&format=json")[0] == 200
    assert inner["code"] == 429


def test_app_basic_auth_keeps_healthz_open():
    app = make_app("local", _cfg(), FakeQuery(RESULT), basic_auth=("ops", "pw"))
    assert _call(app, "/healthz")[0] == 200
    assert _call(app, "/provenance", f"processor_id={PID}&at=1000")[0] == 401
    assert _call(app, "/provenance", f"processor_id={PID}&at=1000", auth="ops:pw")[0] == 200


def test_render_html_without_events():
    out = render_html({**RESULT, "events": [], "clamped": False, "truncated": False}).decode()
    assert "이벤트 0건" in out and "줄였습니다" not in out

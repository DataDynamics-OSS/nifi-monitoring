import time

import httpx
import pytest
from werkzeug.wrappers import Response

from nifi_exporter.nifi import BearerAuth, NiFiAPIError, NiFiClient
from nifi_exporter.nifi.client import API_REQUESTS

from .conftest import make_jwt


def _bearer_client(httpserver, **kw):
    http = httpx.Client(timeout=5.0)
    base = httpserver.url_for("").rstrip("/")
    auth = BearerAuth(http, base, "nifi-monitor", "pw", refresh_margin=kw.pop("margin", 300))
    return NiFiClient(http, base, auth, retries=1, retry_backoff=0.01, **kw)


def test_bearer_login_and_header(httpserver):
    token = make_jwt(exp=time.time() + 3600)
    logins = []

    def login(req):
        logins.append(req.form.get("username"))
        return Response(token, status=201, content_type="text/plain")

    httpserver.expect_request("/nifi-api/access/token", method="POST").respond_with_handler(login)
    httpserver.expect_request(
        "/nifi-api/controller/cluster", headers={"Authorization": f"Bearer {token}"}
    ).respond_with_json({"cluster": {"nodes": []}})

    c = _bearer_client(httpserver)
    assert c.get_json("/controller/cluster", endpoint="x") == {"cluster": {"nodes": []}}
    assert c.get_json("/controller/cluster", endpoint="x") == {"cluster": {"nodes": []}}
    assert logins == ["nifi-monitor"], "token must be cached, not re-requested"
    assert c.auth.expiry == pytest.approx(time.time() + 3600, abs=5)


def test_bearer_refreshes_before_expiry(httpserver):
    calls = {"n": 0}

    def login(_req):
        calls["n"] += 1
        # 100초 뒤 만료, 여유 300초이므로 호출할 때마다 갱신합니다
        return Response(make_jwt(exp=time.time() + 100), status=201)

    httpserver.expect_request("/nifi-api/access/token", method="POST").respond_with_handler(login)
    httpserver.expect_request("/nifi-api/flow/status").respond_with_json({})
    c = _bearer_client(httpserver, margin=300)
    c.get_json("/flow/status", endpoint="x")
    c.get_json("/flow/status", endpoint="x")
    assert calls["n"] == 2


def test_relogin_once_on_401(httpserver):
    tokens = iter(["t-old", "t-new"])
    httpserver.expect_request("/nifi-api/access/token", method="POST").respond_with_handler(
        lambda _r: Response(next(tokens), status=201)
    )

    def status(req):
        if req.headers.get("Authorization") == "Bearer t-new":
            return Response('{"ok":true}', content_type="application/json")
        return Response("expired", status=401)

    httpserver.expect_request("/nifi-api/flow/status").respond_with_handler(status)
    c = _bearer_client(httpserver)
    assert c.get_json("/flow/status", endpoint="x") == {"ok": True}


def test_401_twice_fails(httpserver):
    httpserver.expect_request("/nifi-api/access/token", method="POST").respond_with_data(
        "t", status=201
    )
    httpserver.expect_request("/nifi-api/flow/status").respond_with_data("no", status=401)
    c = _bearer_client(httpserver)
    with pytest.raises(NiFiAPIError) as ei:
        c.get_json("/flow/status", endpoint="x")
    assert ei.value.status == 401


def test_retry_on_5xx_then_success(httpserver, client):
    hits = {"n": 0}

    def flaky(_req):
        hits["n"] += 1
        if hits["n"] == 1:
            return Response("boom", status=503)
        return Response('{"ok":1}', content_type="application/json")

    httpserver.expect_request("/nifi-api/flow/status").respond_with_handler(flaky)
    before = API_REQUESTS.labels("flow", "503")._value.get()
    assert client.get_json("/flow/status", endpoint="flow") == {"ok": 1}
    assert hits["n"] == 2
    assert API_REQUESTS.labels("flow", "503")._value.get() == before + 1


def test_transport_error_surfaces(client):
    bad = NiFiClient(httpx.Client(timeout=0.5), "http://127.0.0.1:9", client.auth, retries=0)
    with pytest.raises(NiFiAPIError, match="transport error"):
        bad.get_json("/flow/status", endpoint="x")


def test_invalid_json(httpserver, client):
    httpserver.expect_request("/nifi-api/flow/status").respond_with_data("<html>", status=200)
    with pytest.raises(NiFiAPIError, match="invalid JSON"):
        client.get_json("/flow/status", endpoint="x")

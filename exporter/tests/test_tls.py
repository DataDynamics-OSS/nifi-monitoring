"""클라이언트 인증서를 요구하는 서버와 실제 TLS 핸드셰이크를 합니다.

mtls 경로를 처음부터 끝까지 검증합니다. httpx 0.28은 ``verify``가 CA 경로이면
``cert=``를 조용히 버리는데, 이는 실제 핸드셰이크에서만 드러납니다.
"""

from __future__ import annotations

import http.server
import shutil
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from nifi_exporter.config import AuthConfig, NiFiConfig, TLSConfig
from nifi_exporter.nifi import NiFiAPIError
from nifi_exporter.nifi.client import build_client

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not found")


def _openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def pki(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("pki")
    _openssl(
        "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=test-ca",
        "-keyout", str(d / "ca.key"), "-out", str(d / "ca.pem"),
    )  # fmt: skip
    for name, ext in [
        ("server", "subjectAltName=DNS:localhost,IP:127.0.0.1"),
        ("client", "extendedKeyUsage=clientAuth"),
    ]:
        _openssl(
            "req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
            "-keyout", str(d / f"{name}.key"), "-out", str(d / f"{name}.csr"),
        )  # fmt: skip
        (d / f"{name}.ext").write_text(ext + "\n")
        _openssl(
            "x509", "-req", "-in", str(d / f"{name}.csr"), "-CA", str(d / "ca.pem"),
            "-CAkey", str(d / "ca.key"), "-CAcreateserial", "-days", "1",
            "-extfile", str(d / f"{name}.ext"), "-out", str(d / f"{name}.pem"),
        )  # fmt: skip
    return d


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API를 따릅니다
        cn = dict(x[0] for x in self.connection.getpeercert()["subject"])["commonName"]
        body = f'{{"about": {{"version": "2.6.0", "client": "{cn}"}}}}'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def mtls_server(pki):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pki / "server.pem", pki / "server.key")
    ctx.load_verify_locations(pki / "ca.pem")
    ctx.verify_mode = ssl.CERT_REQUIRED
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://localhost:{srv.server_address[1]}"
    srv.shutdown()


def _cfg(url: str, pki: Path, **auth) -> NiFiConfig:
    return NiFiConfig(
        base_url=url,
        timeout=5.0,
        retries=0,
        tls=TLSConfig(ca_file=str(pki / "ca.pem")),
        auth=AuthConfig(**auth),
    )


def test_mtls_sends_client_certificate(mtls_server, pki):
    cfg = _cfg(
        mtls_server,
        pki,
        mode="mtls",
        cert_file=str(pki / "client.pem"),
        key_file=str(pki / "client.key"),
    )
    client = build_client(cfg)
    try:
        body = client.get_json("/flow/about", endpoint="about")
    finally:
        client.close()
    assert body["about"]["client"] == "client"


def test_without_client_certificate_is_rejected(mtls_server, pki):
    client = build_client(_cfg(mtls_server, pki, mode="none"))
    try:
        with pytest.raises(NiFiAPIError, match="transport error"):
            client.get_json("/flow/about", endpoint="about")
    finally:
        client.close()

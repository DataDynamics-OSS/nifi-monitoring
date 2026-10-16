"""WSGI 앱입니다: /metrics(Prometheus), /healthz(프로세스 동작), /readyz(데이터 준비)."""

from __future__ import annotations

import base64
import hmac
import logging
import threading
from collections.abc import Callable, Iterable
from wsgiref.simple_server import WSGIRequestHandler, make_server

from prometheus_client import CollectorRegistry
from prometheus_client.exposition import ThreadingWSGIServer, make_wsgi_app

log = logging.getLogger(__name__)

ReadyFn = Callable[[], bool]


OPEN_PATHS = ("/healthz", "/readyz")


def _authorized(environ, credentials: tuple[str, str]) -> bool:
    header = environ.get("HTTP_AUTHORIZATION", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        user, _, password = base64.b64decode(value).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    # 둘 다 항상 상수 시간으로 비교합니다
    ok_user = hmac.compare_digest(user.encode(), credentials[0].encode())
    ok_pass = hmac.compare_digest(password.encode(), credentials[1].encode())
    return ok_user and ok_pass


def make_app(
    registry: CollectorRegistry, ready: ReadyFn, basic_auth: tuple[str, str] | None = None
):
    metrics_app = make_wsgi_app(registry)

    def app(environ, start_response) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        if basic_auth and path not in OPEN_PATHS and not _authorized(environ, basic_auth):
            start_response(
                "401 Unauthorized",
                [
                    ("Content-Type", "text/plain"),
                    ("WWW-Authenticate", 'Basic realm="nifi-exporter"'),
                ],
            )
            return [b"unauthorized\n"]
        if path == "/metrics":
            return metrics_app(environ, start_response)
        if path == "/healthz":
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"ok\n"]
        if path == "/readyz":
            if ready():
                start_response("200 OK", [("Content-Type", "text/plain")])
                return [b"ready\n"]
            start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
            return [b"no collector has succeeded yet\n"]
        if path == "/":
            start_response("200 OK", [("Content-Type", "text/html")])
            return [
                b"<html><body><h1>nifi-exporter</h1><a href='/metrics'>/metrics</a></body></html>"
            ]
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found\n"]

    return app


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - wsgiref 시그니처를 따릅니다
        log.debug("http %s", format % args)


class HTTPServer:
    def __init__(
        self,
        host: str,
        port: int,
        registry: CollectorRegistry,
        ready: ReadyFn,
        basic_auth: tuple[str, str] | None = None,
    ) -> None:
        self._httpd = make_server(
            host,
            port,
            make_app(registry, ready, basic_auth),
            ThreadingWSGIServer,
            handler_class=_QuietHandler,
        )
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="http", daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_port

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

"""얇은 NiFi REST 클라이언트입니다: TLS, 인증, 타임아웃, 동시성 제한, 재시도/backoff."""

from __future__ import annotations

import logging
import ssl
import threading
import time
from typing import Any

import httpx
from prometheus_client import Counter, Gauge

from ..config import NiFiConfig
from .auth import AuthError, BearerAuth, MTLSAuth, NoAuth

log = logging.getLogger(__name__)

API_REQUESTS = Counter(
    "nifi_exporter_api_requests_total",
    "NiFi REST API requests made by the exporter, by endpoint and HTTP status (or error).",
    ["endpoint", "code"],
    registry=None,
)
API_RESPONSE_BYTES = Gauge(
    "nifi_exporter_api_response_bytes",
    "Size of the last successful NiFi REST API response body, by endpoint. Watch the flow "
    "endpoint: above ~10MB raise the flow interval or exclude process groups.",
    ["endpoint"],
    registry=None,
)


class NiFiAPIError(RuntimeError):
    def __init__(self, endpoint: str, message: str, status: int | None = None) -> None:
        super().__init__(f"{endpoint}: {message}")
        self.endpoint = endpoint
        self.status = status


class NiFiClient:
    def __init__(
        self,
        http: httpx.Client,
        base_url: str,
        auth: BearerAuth | MTLSAuth | NoAuth,
        *,
        max_concurrency: int = 4,
        retries: int = 1,
        retry_backoff: float = 2.0,
    ) -> None:
        self._http = http
        self._base = f"{base_url}/nifi-api"
        self.auth = auth
        self._sem = threading.BoundedSemaphore(max_concurrency)
        self._retries = max(0, retries)
        self._backoff = retry_backoff

    def get_json(self, path: str, params: dict[str, Any] | None = None, *, endpoint: str) -> Any:
        """``/nifi-api{path}``를 GET하고 디코딩한 JSON 본문을 반환합니다.

        전송 오류와 5xx에는 ``retries``번 재시도합니다. 401을 받으면 실패하기 전에
        토큰 재로그인을 한 번 합니다(bearer 모드).
        """
        return self.request_json("GET", path, params=params, endpoint=endpoint)

    def request_json(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
        *,
        endpoint: str,
    ) -> Any:
        """``get_json``과 같지만 메서드와 JSON 본문을 지정합니다(Provenance 조회용).

        POST는 NiFi에 작업을 만들므로 전송 오류나 5xx에 재시도하지 않습니다.
        200·201·202 응답을 성공으로 봅니다.
        """
        url = f"{self._base}{path}"
        retries = 0 if method == "POST" else self._retries
        attempt = 0
        relogin_done = False
        while True:
            try:
                with self._sem:
                    resp = self._http.request(
                        method,
                        url,
                        params=params,
                        json=body,
                        headers={"Accept": "application/json", **self.auth.headers()},
                    )
            except AuthError as e:
                API_REQUESTS.labels(endpoint, "auth_error").inc()
                raise NiFiAPIError(endpoint, str(e)) from e
            except httpx.HTTPError as e:
                API_REQUESTS.labels(endpoint, "transport_error").inc()
                if attempt < retries:
                    attempt += 1
                    log.warning(
                        "nifi request failed, retrying",
                        extra={"endpoint": endpoint, "error": str(e)},
                    )
                    time.sleep(self._backoff * attempt)
                    continue
                raise NiFiAPIError(endpoint, f"transport error: {e}") from e

            API_REQUESTS.labels(endpoint, str(resp.status_code)).inc()
            if resp.status_code in (200, 201, 202):
                API_RESPONSE_BYTES.labels(endpoint).set(len(resp.content))
                try:
                    return resp.json()
                except ValueError as e:
                    raise NiFiAPIError(endpoint, "invalid JSON response", 200) from e
            if resp.status_code == 401 and not relogin_done:
                relogin_done = True
                self.auth.invalidate()
                continue
            if resp.status_code >= 500 and attempt < retries:
                attempt += 1
                time.sleep(self._backoff * attempt)
                continue
            raise NiFiAPIError(
                endpoint, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code
            )

    def close(self) -> None:
        self._http.close()


def build_ssl_context(cfg: NiFiConfig) -> ssl.SSLContext:
    """CA 번들과, mtls 모드에서는 클라이언트 인증서를 담은 TLS 컨텍스트입니다.

    직접 만드는 이유는 httpx 0.28이 ``verify``가 CA 경로일 때 ``cert=``를 무시해
    클라이언트 인증서가 아무 경고 없이 전송되지 않기 때문입니다.
    """
    ctx = ssl.create_default_context(cafile=cfg.tls.ca_file or None)
    if cfg.tls.insecure_skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if cfg.auth.mode == "mtls":
        ctx.load_cert_chain(cfg.auth.cert_file, cfg.auth.key_file)
    return ctx


def build_client(cfg: NiFiConfig) -> NiFiClient:
    http = httpx.Client(
        verify=build_ssl_context(cfg),
        timeout=httpx.Timeout(cfg.timeout, connect=min(cfg.timeout, 5.0)),
        headers={"User-Agent": "nifi-exporter"},
    )
    auth: BearerAuth | MTLSAuth | NoAuth
    if cfg.auth.mode == "bearer":
        auth = BearerAuth(
            http,
            cfg.base_url,
            cfg.auth.username or "",
            cfg.auth.password or "",
            cfg.auth.refresh_margin,
        )
    elif cfg.auth.mode == "mtls":
        auth = MTLSAuth()
    else:
        auth = NoAuth()
    return NiFiClient(
        http,
        cfg.base_url,
        auth,
        max_concurrency=cfg.max_concurrency,
        retries=cfg.retries,
        retry_backoff=cfg.retry_backoff,
    )

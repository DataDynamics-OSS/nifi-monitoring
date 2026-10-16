"""NiFi REST API용 인증 제공자입니다."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time

import httpx

log = logging.getLogger(__name__)


class AuthError(RuntimeError):
    pass


class NoAuth:
    """자격 증명이 없습니다(익명 접근 또는 앞단 프록시가 주입하는 경우입니다)."""

    def headers(self) -> dict[str, str]:
        return {}

    def invalidate(self) -> None:
        pass

    @property
    def expiry(self) -> float | None:
        return None


class MTLSAuth(NoAuth):
    """클라이언트 인증서 인증입니다. 요청마다 더할 것이 없고 TLS 계층이 처리합니다."""


class BearerAuth:
    """``POST /access/token``으로 Single User / LDAP / Kerberos 로그인을 합니다.

    JWT ``exp`` 클레임을 읽어 만료 ``refresh_margin``초 전에 갱신합니다.
    ``invalidate()``는 새 로그인을 강제합니다(클라이언트가 401을 받으면 호출합니다).
    """

    def __init__(
        self,
        http: httpx.Client,
        base_url: str,
        username: str,
        password: str,
        refresh_margin: float = 300.0,
    ) -> None:
        self._http = http
        self._url = f"{base_url}/nifi-api/access/token"
        self._username = username
        self._password = password
        self._margin = refresh_margin
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expiry: float | None = None

    @property
    def expiry(self) -> float | None:
        return self._expiry

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token_valid()}"}

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expiry = None

    def _token_valid(self) -> str:
        with self._lock:
            now = time.time()
            if self._token and (self._expiry is None or self._expiry - self._margin > now):
                return self._token
            self._login()
            assert self._token is not None
            return self._token

    def _login(self) -> None:
        try:
            resp = self._http.post(
                self._url,
                data={"username": self._username, "password": self._password},
                headers={"Accept": "text/plain"},
            )
        except httpx.HTTPError as e:
            raise AuthError(f"token request failed: {e}") from e
        if resp.status_code != 201 and resp.status_code != 200:
            raise AuthError(f"token request returned HTTP {resp.status_code}: {resp.text[:200]}")
        token = resp.text.strip()
        if not token:
            raise AuthError("token response was empty")
        self._token = token
        self._expiry = _jwt_expiry(token)
        log.info(
            "nifi token acquired",
            extra={
                "expires_in": None if self._expiry is None else round(self._expiry - time.time())
            },
        )


def _jwt_expiry(token: str) -> float | None:
    """JWT의 ``exp`` 클레임을 epoch 초로 반환합니다. 읽을 수 없으면 None을 반환합니다."""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except (ValueError, TypeError):
        return None

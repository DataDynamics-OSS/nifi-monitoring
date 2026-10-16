"""Alertmanager 알림을 사용자 정의 HTTP 대상으로 중계하는 서비스 ``nifi-alert-relay``입니다.

Alertmanager의 webhook 수신처(`webhook_configs`)로 이 서비스의 ``POST /alerts``를 등록하면,
설정 파일의 대상(target)마다 필터를 적용하고 요청 본문을 만들어 HTTP로 보냅니다. Slack·메일
외에 사내 당직 시스템, 티켓 시스템, 문자 게이트웨이처럼 고유 형식의 HTTP API를 부를 때
씁니다.

대상별 설정:

- ``url``, ``method``(기본 POST), ``headers``(값의 ``${ENV}``는 시작할 때 환경변수로 바꿉니다)
- ``mode``: ``alert``이면 알림 하나에 요청 하나, ``group``이면 Alertmanager 통지 하나에 요청 하나
- ``payload``: 생략하면 Alertmanager 본문(또는 알림 하나)을 그대로 JSON으로 보냅니다. 지정하면
  그 구조를 그대로 쓰되 문자열 값의 ``{alertname}``, ``{labels[pg_id]}`` 같은 자리를 채웁니다.
  값이 정확히 ``{labels}``, ``{annotations}``, ``{alert}``, ``{alerts}``이면 객체를 그대로 넣습니다.
- ``match``: 레이블(또는 ``status``) 값 목록. 모두 맞는 알림만 보냅니다.
- ``send_resolved``, ``timeout``, ``retries``, ``retry_backoff``, ``tls``

같은 통지를 Alertmanager가 다시 보내도(대상 하나라도 실패하면 5xx를 돌려주므로 재시도합니다)
이미 성공한 대상에는 ``dedupe_window`` 동안 다시 보내지 않습니다.
"""

from __future__ import annotations

import argparse
import hashlib
import http
import json
import logging
import os
import re
import signal
import ssl
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Any
from wsgiref.simple_server import make_server

import httpx
import yaml
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST, ThreadingWSGIServer

from . import __version__, logging_setup
from .server import _authorized, _QuietHandler
from .util import parse_byte_size, parse_duration

log = logging.getLogger(__name__)

ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
OBJECT_FIELDS = {"labels", "annotations", "alert", "alerts", "groupLabels", "commonLabels"}
MAX_BODY = 5 * 1024 * 1024  # Alertmanager 통지 본문 상한입니다


class ConfigError(ValueError):
    pass


@dataclass
class TLS:
    ca_file: str | None = None
    insecure_skip_verify: bool = False
    cert_file: str | None = None
    key_file: str | None = None


@dataclass
class Target:
    name: str
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    mode: str = "alert"  # alert | group
    payload: Any = None
    match: dict[str, list[str]] = field(default_factory=dict)
    send_resolved: bool = True
    timeout: float = 10.0
    retries: int = 2
    retry_backoff: float = 2.0
    tls: TLS = field(default_factory=TLS)


@dataclass
class RelayConfig:
    listen: str = "0.0.0.0:9105"
    log_level: str = "INFO"
    log_format: str = "json"
    log_file: str | None = None  # 없으면 stdout으로 씁니다
    log_max_size: int = 50 * 1024**2
    log_backups: int = 5
    basic_auth: tuple[str, str] | None = None
    dedupe_window: float = 300.0
    targets: list[Target] = field(default_factory=list)


def _expand_env(value: str, where: str) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) not in os.environ:
            raise ConfigError(f"{where}: environment variable {m.group(1)} is not set")
        return os.environ[m.group(1)]

    return ENV_RE.sub(sub, value)


def load_config(path: str | os.PathLike) -> RelayConfig:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    return config_from_dict(raw)


def config_from_dict(raw: dict) -> RelayConfig:
    ba = raw.get("basic_auth") or {}
    credentials = None
    if ba.get("username"):
        password = ba.get("password")
        if password is None and ba.get("password_file"):
            password = Path(ba["password_file"]).read_text(encoding="utf-8").strip()
        password = os.environ.get("NIFI_ALERT_RELAY_PASSWORD", password)
        if not password:
            raise ConfigError("basic_auth requires password/password_file")
        credentials = (str(ba["username"]), password)
    cfg = RelayConfig(
        listen=str(os.environ.get("NIFI_ALERT_RELAY_LISTEN", raw.get("listen", "0.0.0.0:9105"))),
        log_level=str(raw.get("log_level", "INFO")).upper(),
        log_format=str(raw.get("log_format", "json")).lower(),
        log_file=raw.get("log_file") or None,
        log_max_size=parse_byte_size(raw.get("log_max_size", RelayConfig.log_max_size)),
        log_backups=int(raw.get("log_backups", RelayConfig.log_backups)),
        basic_auth=credentials,
        dedupe_window=parse_duration(raw.get("dedupe_window", 300)),
    )
    try:
        int(cfg.listen.rsplit(":", 1)[1])
    except (IndexError, ValueError) as e:
        raise ConfigError(f"listen must be host:port, got {cfg.listen!r}") from e
    if cfg.log_format not in ("json", "text"):
        raise ConfigError("log_format must be json|text")
    if cfg.log_max_size < 1 or cfg.log_backups < 0:
        raise ConfigError("log_max_size must be > 0 and log_backups >= 0")
    names = set()
    for i, t in enumerate(raw.get("targets") or []):
        where = f"targets[{i}]"
        if not t.get("name") or not t.get("url"):
            raise ConfigError(f"{where}: name and url are required")
        if t["name"] in names:
            raise ConfigError(f"{where}: duplicate target name {t['name']!r}")
        names.add(t["name"])
        url = _expand_env(str(t["url"]), where)
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"{where}: url must start with http:// or https://")
        mode = str(t.get("mode", "alert"))
        if mode not in ("alert", "group"):
            raise ConfigError(f"{where}: mode must be alert|group")
        match = {}
        for k, v in (t.get("match") or {}).items():
            match[str(k)] = [str(x) for x in (v if isinstance(v, list) else [v])]
        tls = t.get("tls") or {}
        cfg.targets.append(
            Target(
                name=str(t["name"]),
                url=url,
                method=str(t.get("method", "POST")).upper(),
                headers={
                    str(k): _expand_env(str(v), f"{where}.headers.{k}")
                    for k, v in (t.get("headers") or {}).items()
                },
                mode=mode,
                payload=t.get("payload"),
                match=match,
                send_resolved=bool(t.get("send_resolved", True)),
                timeout=parse_duration(t.get("timeout", 10)),
                retries=int(t.get("retries", 2)),
                retry_backoff=parse_duration(t.get("retry_backoff", 2)),
                tls=TLS(
                    ca_file=tls.get("ca_file"),
                    insecure_skip_verify=bool(tls.get("insecure_skip_verify", False)),
                    cert_file=tls.get("cert_file"),
                    key_file=tls.get("key_file"),
                ),
            )
        )
    if not cfg.targets:
        raise ConfigError("at least one target is required")
    return cfg


# -- 본문 만들기 ------------------------------------------------------------------


class _Blank(dict):
    """없는 키는 빈 문자열로 채웁니다(레이블이 없는 알림도 템플릿이 깨지지 않게)."""

    def __missing__(self, key):
        return ""


class _SafeFormatter(Formatter):
    def get_value(self, key, args, kwargs):
        return kwargs.get(key, "") if isinstance(key, str) else super().get_value(key, args, kwargs)

    def get_field(self, field_name, args, kwargs):
        try:
            return super().get_field(field_name, args, kwargs)
        except (KeyError, IndexError, AttributeError, TypeError):
            return "", field_name


_FORMATTER = _SafeFormatter()


def render(template: Any, fields: dict) -> Any:
    """payload 구조의 문자열 값을 채웁니다. 구조(키, 목록)는 그대로 둡니다."""
    if isinstance(template, dict):
        return {k: render(v, fields) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, fields) for v in template]
    if isinstance(template, str):
        m = re.fullmatch(r"\{(\w+)\}", template)
        if m and m.group(1) in OBJECT_FIELDS:
            return fields.get(m.group(1))
        try:
            return _FORMATTER.vformat(template, (), fields)
        except ValueError:  # 짝이 맞지 않는 중괄호 등은 원문을 보냅니다
            return template
    return template


def alert_fields(alert: dict, notification: dict) -> dict:
    labels = _Blank(alert.get("labels") or {})
    annotations = _Blank(alert.get("annotations") or {})
    return {
        "status": alert.get("status", notification.get("status", "")),
        "alertname": labels["alertname"],
        "severity": labels["severity"],
        "cluster": labels["cluster"],
        "summary": annotations["summary"],
        "description": annotations["description"],
        "startsAt": alert.get("startsAt", ""),
        "endsAt": alert.get("endsAt", ""),
        "generatorURL": alert.get("generatorURL", ""),
        "fingerprint": alert.get("fingerprint", ""),
        "receiver": notification.get("receiver", ""),
        "externalURL": notification.get("externalURL", ""),
        "labels": labels,
        "annotations": annotations,
        "alert": alert,
    }


def _common_fields(alerts: list[dict], field: str) -> dict:
    common = dict(alerts[0].get(field) or {}) if alerts else {}
    for alert in alerts[1:]:
        values = alert.get(field) or {}
        common = {k: v for k, v in common.items() if k in values and values[k] == v}
    return common


def group_fields(notification: dict, alerts: list[dict]) -> dict:
    common = _Blank(_common_fields(alerts, "labels"))
    annotations = _Blank(_common_fields(alerts, "annotations"))
    firing = sum(1 for a in alerts if a.get("status") == "firing")
    return {
        "status": "firing" if firing else "resolved",
        "alertname": common["alertname"],
        "severity": common["severity"],
        "cluster": common["cluster"],
        "summary": annotations["summary"],
        "description": annotations["description"],
        "receiver": notification.get("receiver", ""),
        "externalURL": notification.get("externalURL", ""),
        "groupKey": notification.get("groupKey", ""),
        "count": len(alerts),
        "firing": firing,
        "resolved": len(alerts) - firing,
        "labels": common,
        "commonLabels": common,
        "groupLabels": _Blank(notification.get("groupLabels") or {}),
        "annotations": annotations,
        "alerts": alerts,
    }


def matches(target: Target, alert: dict) -> bool:
    if alert.get("status") == "resolved" and not target.send_resolved:
        return False
    labels = alert.get("labels") or {}
    for key, allowed in target.match.items():
        value = alert.get("status") if key == "status" else labels.get(key)
        if value not in allowed:
            return False
    return True


# -- 전송 -----------------------------------------------------------------------


@dataclass
class Delivery:
    target: Target
    key: str  # 중복 방지 키입니다
    body: Any
    count: int


class DeliveryError(Exception):
    pass


class Relay:
    def __init__(
        self,
        cfg: RelayConfig,
        registry: CollectorRegistry | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self._sleep = sleep
        self._clock = clock
        self._sent: dict[str, float] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        self._clients = {
            t.name: httpx.Client(
                verify=_ssl_context(t.tls),
                timeout=httpx.Timeout(t.timeout, connect=min(t.timeout, 5.0)),
                headers={"User-Agent": f"nifi-alert-relay/{__version__}"},
                transport=transport,
            )
            for t in cfg.targets
        }
        registry = registry or CollectorRegistry()
        self.registry = registry
        self.deliveries = Counter(
            "nifi_alert_relay_deliveries_total",
            "Requests sent to each relay target, by result (success, failed, skipped duplicate).",
            ["target", "result"],
            registry=registry,
        )
        self.alerts = Counter(
            "nifi_alert_relay_alerts_total",
            "Alerts delivered to each relay target.",
            ["target"],
            registry=registry,
        )
        self.last_success = Gauge(
            "nifi_alert_relay_last_success_timestamp_seconds",
            "Unix time of the last successful delivery to each relay target.",
            ["target"],
            registry=registry,
        )
        self.notifications = Counter(
            "nifi_alert_relay_notifications_total",
            "Alertmanager notifications received, by result (ok, partial failure, bad request).",
            ["result"],
            registry=registry,
        )
        for t in cfg.targets:
            for result in ("success", "failed", "duplicate"):
                self.deliveries.labels(t.name, result)

    def plan(self, notification: dict) -> list[Delivery]:
        out = []
        alerts = [a for a in notification.get("alerts") or [] if isinstance(a, dict)]
        for t in self.cfg.targets:
            chosen = [a for a in alerts if matches(t, a)]
            if not chosen:
                continue
            if t.mode == "alert":
                for a in chosen:
                    fields = alert_fields(a, notification)
                    body = a if t.payload is None else render(t.payload, fields)
                    key = f"{t.name}|{a.get('fingerprint')}|{a.get('status')}|{a.get('startsAt')}"
                    out.append(Delivery(t, key, body, 1))
            else:
                fields = group_fields(notification, chosen)
                body = (
                    {
                        **notification,
                        "alerts": chosen,
                        "status": fields["status"],
                        "commonLabels": fields["commonLabels"],
                        "commonAnnotations": fields["annotations"],
                    }
                    if t.payload is None
                    else render(t.payload, fields)
                )
                state = sorted(
                    f"{a.get('fingerprint')}:{a.get('status')}:{a.get('startsAt')}" for a in chosen
                )
                digest = hashlib.sha256("|".join(state).encode()).hexdigest()[:16]
                out.append(
                    Delivery(
                        t, f"{t.name}|{notification.get('groupKey')}|{digest}", body, len(chosen)
                    )
                )
        return out

    def handle(self, notification: dict) -> list[str]:
        """통지 하나를 모든 대상에 보냅니다. 실패한 대상 이름 목록을 돌려줍니다."""
        failed = []
        for d in self.plan(notification):
            state = self._claim(d.key)
            if state == "duplicate":
                self.deliveries.labels(d.target.name, "duplicate").inc()
                continue
            if state == "in_flight":
                # 다른 요청이 아직 전송 중입니다. 먼저 성공으로 ACK하면 그 전송이
                # 실패할 때 알림이 유실될 수 있으므로 502로 재시도를 요청합니다.
                failed.append(d.target.name)
                continue
            succeeded = False
            try:
                self.send(d)
                succeeded = True
            except DeliveryError as e:
                self.deliveries.labels(d.target.name, "failed").inc()
                log.warning(
                    "alert relay delivery failed",
                    extra={"target": d.target.name, "error": str(e), "alerts": d.count},
                )
                failed.append(d.target.name)
                continue
            finally:
                self._finish(d.key, succeeded)
            self.deliveries.labels(d.target.name, "success").inc()
            self.alerts.labels(d.target.name).inc(d.count)
            self.last_success.labels(d.target.name).set(time.time())
            log.info(
                "alert relayed",
                extra={
                    "target": d.target.name,
                    "alerts": d.count,
                    "status": notification.get("status"),
                },
            )
        return sorted(set(failed))

    def send(self, d: Delivery) -> None:
        t = d.target
        client = self._clients[t.name]
        headers = {"Content-Type": "application/json", **t.headers}
        body = json.dumps(d.body, ensure_ascii=False).encode()
        attempt = 0
        while True:
            try:
                resp = client.request(t.method, t.url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    return
                error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                retryable = resp.status_code >= 500 or resp.status_code == 429
            except httpx.HTTPError as e:
                error, retryable = f"transport error: {e}", True
            if not retryable or attempt >= t.retries:
                raise DeliveryError(error)
            attempt += 1
            self._sleep(t.retry_backoff * attempt)

    def _claim(self, key: str) -> str:
        """중복 확인과 전송 예약을 원자적으로 처리합니다. HTTP 중에는 lock을 놓습니다."""
        with self._lock:
            now = self._clock()
            for k in [k for k, ts in self._sent.items() if now - ts > self.cfg.dedupe_window]:
                del self._sent[k]
            if key in self._sent:
                return "duplicate"
            if key in self._in_flight:
                return "in_flight"
            self._in_flight.add(key)
            return "send"

    def _finish(self, key: str, succeeded: bool) -> None:
        with self._lock:
            if succeeded:
                self._sent[key] = self._clock()
            self._in_flight.discard(key)

    def close(self) -> None:
        for c in self._clients.values():
            c.close()


def _ssl_context(tls: TLS) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=tls.ca_file or None)
    if tls.insecure_skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if tls.cert_file and tls.key_file:
        ctx.load_cert_chain(tls.cert_file, tls.key_file)
    return ctx


# -- HTTP ------------------------------------------------------------------------


def make_app(relay: Relay, basic_auth: tuple[str, str] | None = None):
    def respond(start_response, code: int, body: bytes, ctype: str = "text/plain") -> list[bytes]:
        start_response(f"{code} {http.HTTPStatus(code).phrase}", [("Content-Type", ctype)])
        return [body]

    def app(environ, start_response) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        if path == "/healthz":
            return respond(start_response, 200, b"ok\n")
        if basic_auth and not _authorized(environ, basic_auth):
            start_response(
                "401 Unauthorized",
                [
                    ("Content-Type", "text/plain"),
                    ("WWW-Authenticate", 'Basic realm="nifi-alert-relay"'),
                ],
            )
            return [b"unauthorized\n"]
        if path == "/metrics":
            return respond(
                start_response, 200, generate_latest(relay.registry), CONTENT_TYPE_LATEST
            )
        if path != "/alerts":
            return respond(start_response, 404, b"not found\n")
        if environ.get("REQUEST_METHOD") != "POST":
            return respond(start_response, 405, b"use POST\n")
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            relay.notifications.labels("bad_request").inc()
            return respond(start_response, 400, b"missing or too large body\n")
        try:
            notification = json.loads(environ["wsgi.input"].read(length))
            if not isinstance(notification, dict):
                raise ValueError("not an object")
        except ValueError:
            relay.notifications.labels("bad_request").inc()
            return respond(start_response, 400, b"invalid JSON\n")
        failed = relay.handle(notification)
        if failed:
            # Alertmanager가 다시 보내게 합니다. 이미 성공한 대상은 중복 방지로 건너뜁니다
            relay.notifications.labels("partial_failure").inc()
            return respond(start_response, 502, ("failed: " + ", ".join(failed) + "\n").encode())
        relay.notifications.labels("ok").inc()
        return respond(start_response, 200, b"ok\n")

    return app


def serve(cfg: RelayConfig) -> None:
    relay = Relay(cfg)
    host, port = cfg.listen.rsplit(":", 1)
    httpd = make_server(
        host,
        int(port),
        make_app(relay, cfg.basic_auth),
        ThreadingWSGIServer,
        handler_class=_QuietHandler,
    )

    def stop(signum, frame):  # noqa: ARG001 - signal 핸들러 시그니처입니다
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    log.info(
        "starting nifi-alert-relay",
        extra={
            "version": __version__,
            "listen": cfg.listen,
            "targets": [t.name for t in cfg.targets],
        },
    )
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        relay.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nifi-alert-relay",
        description="Relay Alertmanager webhook notifications to custom HTTP targets",
    )
    parser.add_argument("-c", "--config", required=True, help="path to YAML config")
    parser.add_argument("--check-config", action="store_true", help="validate config and exit")
    parser.add_argument("--version", action="version", version=f"nifi-alert-relay {__version__}")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError, ValueError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if args.check_config:
        print("config ok")
        return 0
    logging_setup.configure(
        cfg.log_level, cfg.log_format, cfg.log_file, cfg.log_max_size, cfg.log_backups
    )
    serve(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

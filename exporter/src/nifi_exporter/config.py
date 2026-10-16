"""설정을 불러옵니다(YAML 파일 + 환경변수 덮어쓰기)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .util import parse_byte_size, parse_duration


class ConfigError(ValueError):
    pass


@dataclass
class TLSConfig:
    ca_file: str | None = None
    insecure_skip_verify: bool = False


@dataclass
class AuthConfig:
    mode: str = "bearer"  # bearer | mtls | none 중 하나입니다
    username: str | None = None
    password: str | None = None
    password_file: str | None = None
    cert_file: str | None = None
    key_file: str | None = None
    refresh_margin: float = 300.0  # JWT 만료 몇 초 전에 갱신할지입니다


@dataclass
class NiFiConfig:
    base_url: str = "https://localhost:8443"
    cluster_name: str = "nifi"
    timezone: str = "UTC"  # 해석할 수 없는 시간대가 붙은 heartbeat 문자열을 해석할 때 씁니다
    timeout: float = 10.0
    max_concurrency: int = 4
    retries: int = 1
    retry_backoff: float = 2.0
    tls: TLSConfig = field(default_factory=TLSConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)


@dataclass
class CollectorConfig:
    enabled: bool = True
    interval: float = 30.0
    # flow와 topology collector용입니다
    exclude_pg_ids: list[str] = field(default_factory=list)
    # `bulletin` collector용입니다
    limit: int = 1000


@dataclass
class CollectorsConfig:
    cluster: CollectorConfig = field(default_factory=lambda: CollectorConfig(interval=15.0))
    flow: CollectorConfig = field(default_factory=lambda: CollectorConfig(interval=30.0))
    diagnostics: CollectorConfig = field(default_factory=lambda: CollectorConfig(interval=30.0))
    bulletin: CollectorConfig = field(default_factory=lambda: CollectorConfig(interval=30.0))
    topology: CollectorConfig = field(default_factory=lambda: CollectorConfig(interval=300.0))
    controller: CollectorConfig = field(default_factory=lambda: CollectorConfig(interval=30.0))


@dataclass
class BasicAuthConfig:
    username: str | None = None
    password: str | None = None
    password_file: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.username)


@dataclass
class ServerConfig:
    listen: str = "0.0.0.0:9103"
    log_level: str = "INFO"
    log_format: str = "json"  # json | text 중 하나입니다
    log_bulletin_messages: bool = False
    log_file: str | None = None  # 없으면 stdout으로 씁니다
    log_max_size: int = 50 * 1024**2  # 넘으면 돌립니다
    log_backups: int = 5
    # /metrics와 /를 보호합니다(큐와 Processor 이름이 노출되기 때문입니다).
    # /healthz와 /readyz는 오케스트레이터 프로브를 위해 열어 둡니다.
    basic_auth: BasicAuthConfig = field(default_factory=BasicAuthConfig)


@dataclass
class ProvenanceConfig:
    """``nifi-provenance-query`` 서비스 설정입니다.

    exporter는 이 절을 쓰지 않습니다.
    """

    listen: str = "0.0.0.0:9104"
    max_range: float = 3600.0  # 한 번에 조회할 수 있는 최대 시간 범위(초)입니다
    default_window: float = 300.0  # at만 주면 [at - window, at]을 조회합니다
    max_results: int = 1000  # NiFi에 요청하는 최대 이벤트 수의 상한입니다
    query_timeout: float = 60.0  # NiFi 질의가 끝나기를 기다리는 최대 시간(초)입니다
    poll_interval: float = 1.0
    max_concurrent: int = 2  # 동시에 실행하는 질의 수입니다. 넘으면 429로 거절합니다


@dataclass
class Config:
    nifi: NiFiConfig = field(default_factory=NiFiConfig)
    collectors: CollectorsConfig = field(default_factory=CollectorsConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    provenance: ProvenanceConfig = field(default_factory=ProvenanceConfig)

    @property
    def listen_host(self) -> str:
        return self.server.listen.rsplit(":", 1)[0]

    @property
    def listen_port(self) -> int:
        return int(self.server.listen.rsplit(":", 1)[1])


def _collector(raw: dict[str, Any] | None, default: CollectorConfig) -> CollectorConfig:
    raw = raw or {}
    return CollectorConfig(
        enabled=bool(raw.get("enabled", default.enabled)),
        interval=parse_duration(raw.get("interval", default.interval)),
        exclude_pg_ids=list(raw.get("exclude_pg_ids", default.exclude_pg_ids)),
        limit=int(raw.get("limit", default.limit)),
    )


def from_dict(raw: dict[str, Any]) -> Config:
    raw = raw or {}
    n = raw.get("nifi") or {}
    tls = n.get("tls") or {}
    auth = n.get("auth") or {}
    c = raw.get("collectors") or {}
    s = raw.get("server") or {}
    ba = s.get("basic_auth") or {}
    pv = raw.get("provenance") or {}
    defaults = CollectorsConfig()

    cfg = Config(
        nifi=NiFiConfig(
            base_url=str(n.get("base_url", NiFiConfig.base_url)).rstrip("/"),
            cluster_name=str(n.get("cluster_name", NiFiConfig.cluster_name)),
            timezone=str(n.get("timezone", NiFiConfig.timezone)),
            timeout=parse_duration(n.get("timeout", NiFiConfig.timeout)),
            max_concurrency=int(n.get("max_concurrency", NiFiConfig.max_concurrency)),
            retries=int(n.get("retries", NiFiConfig.retries)),
            retry_backoff=parse_duration(n.get("retry_backoff", NiFiConfig.retry_backoff)),
            tls=TLSConfig(
                ca_file=tls.get("ca_file"),
                insecure_skip_verify=bool(tls.get("insecure_skip_verify", False)),
            ),
            auth=AuthConfig(
                mode=str(auth.get("mode", "bearer")).lower(),
                username=auth.get("username"),
                password=auth.get("password"),
                password_file=auth.get("password_file"),
                cert_file=auth.get("cert_file"),
                key_file=auth.get("key_file"),
                refresh_margin=parse_duration(auth.get("refresh_margin", 300)),
            ),
        ),
        collectors=CollectorsConfig(
            cluster=_collector(c.get("cluster"), defaults.cluster),
            flow=_collector(c.get("flow"), defaults.flow),
            diagnostics=_collector(c.get("diagnostics"), defaults.diagnostics),
            bulletin=_collector(c.get("bulletin"), defaults.bulletin),
            topology=_collector(c.get("topology"), defaults.topology),
            controller=_collector(c.get("controller"), defaults.controller),
        ),
        server=ServerConfig(
            listen=str(s.get("listen", ServerConfig.listen)),
            log_level=str(s.get("log_level", ServerConfig.log_level)).upper(),
            log_format=str(s.get("log_format", ServerConfig.log_format)).lower(),
            log_bulletin_messages=bool(s.get("log_bulletin_messages", False)),
            log_file=s.get("log_file") or None,
            log_max_size=parse_byte_size(s.get("log_max_size", ServerConfig.log_max_size)),
            log_backups=int(s.get("log_backups", ServerConfig.log_backups)),
            basic_auth=BasicAuthConfig(
                username=ba.get("username"),
                password=ba.get("password"),
                password_file=ba.get("password_file"),
            ),
        ),
        provenance=ProvenanceConfig(
            listen=str(pv.get("listen", ProvenanceConfig.listen)),
            max_range=parse_duration(pv.get("max_range", ProvenanceConfig.max_range)),
            default_window=parse_duration(
                pv.get("default_window", ProvenanceConfig.default_window)
            ),
            max_results=int(pv.get("max_results", ProvenanceConfig.max_results)),
            query_timeout=parse_duration(pv.get("query_timeout", ProvenanceConfig.query_timeout)),
            poll_interval=parse_duration(pv.get("poll_interval", ProvenanceConfig.poll_interval)),
            max_concurrent=int(pv.get("max_concurrent", ProvenanceConfig.max_concurrent)),
        ),
    )
    _apply_env(cfg)
    _validate(cfg)
    return cfg


def _apply_env(cfg: Config) -> None:
    env = os.environ
    if env.get("NIFI_BASE_URL"):
        cfg.nifi.base_url = env["NIFI_BASE_URL"].rstrip("/")
    if env.get("NIFI_USERNAME"):
        cfg.nifi.auth.username = env["NIFI_USERNAME"]
    if env.get("NIFI_PASSWORD"):
        cfg.nifi.auth.password = env["NIFI_PASSWORD"]
    if env.get("NIFI_EXPORTER_LISTEN"):
        cfg.server.listen = env["NIFI_EXPORTER_LISTEN"]
    if env.get("NIFI_EXPORTER_BASIC_AUTH_PASSWORD"):
        cfg.server.basic_auth.password = env["NIFI_EXPORTER_BASIC_AUTH_PASSWORD"]
    if env.get("NIFI_PROVENANCE_LISTEN"):
        cfg.provenance.listen = env["NIFI_PROVENANCE_LISTEN"]
    if env.get("NIFI_EXPORTER_LOG_LEVEL"):
        cfg.server.log_level = env["NIFI_EXPORTER_LOG_LEVEL"].upper()


def _validate(cfg: Config) -> None:
    a = cfg.nifi.auth
    if a.mode not in ("bearer", "mtls", "none"):
        raise ConfigError(f"nifi.auth.mode must be bearer|mtls|none, got {a.mode!r}")
    scheme = urlsplit(cfg.nifi.base_url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ConfigError(
            f"nifi.base_url must start with http:// or https://, got {cfg.nifi.base_url!r}"
        )
    # TLS 없이(HTTP) 운영하는 NiFi에는 인증이 없습니다. NiFi는 토큰을 HTTPS로만 발급하고
    # mTLS는 TLS가 있어야 하므로, HTTP 주소에는 인증 없음(none)만 허용합니다.
    if scheme == "http" and a.mode != "none":
        raise ConfigError(
            "nifi.base_url is plain HTTP, so NiFi runs without authentication: "
            "set nifi.auth.mode: none (NiFi issues tokens only over HTTPS, and mtls needs TLS)"
        )
    if a.mode == "bearer":
        if a.password is None and a.password_file:
            a.password = Path(a.password_file).read_text(encoding="utf-8").strip()
        if not a.username or a.password is None:
            raise ConfigError(
                "bearer auth requires nifi.auth.username and password/password_file "
                "(or NIFI_USERNAME/NIFI_PASSWORD)"
            )
    if a.mode == "mtls" and not (a.cert_file and a.key_file):
        raise ConfigError("mtls auth requires nifi.auth.cert_file and key_file")
    if cfg.nifi.max_concurrency < 1:
        raise ConfigError("nifi.max_concurrency must be >= 1")
    ba = cfg.server.basic_auth
    if ba.enabled:
        if ba.password is None and ba.password_file:
            ba.password = Path(ba.password_file).read_text(encoding="utf-8").strip()
        if not ba.password:
            raise ConfigError(
                "server.basic_auth requires password/password_file "
                "(or NIFI_EXPORTER_BASIC_AUTH_PASSWORD)"
            )
    if cfg.server.log_format not in ("json", "text"):
        raise ConfigError("server.log_format must be json|text")
    if cfg.server.log_max_size < 1 or cfg.server.log_backups < 0:
        raise ConfigError("server.log_max_size must be > 0 and server.log_backups >= 0")
    for name, listen in (
        ("server.listen", cfg.server.listen),
        ("provenance.listen", cfg.provenance.listen),
    ):
        try:
            int(listen.rsplit(":", 1)[1])
        except (IndexError, ValueError) as e:
            raise ConfigError(f"{name} must be host:port, got {listen!r}") from e
    pv = cfg.provenance
    if not 0 < pv.default_window <= pv.max_range:
        raise ConfigError("provenance.default_window must be > 0 and <= provenance.max_range")
    if not 1 <= pv.max_results <= 10000:
        raise ConfigError("provenance.max_results must be between 1 and 10000")
    if pv.query_timeout <= 0 or pv.poll_interval <= 0 or pv.max_concurrent < 1:
        raise ConfigError(
            "provenance.query_timeout and poll_interval must be > 0, max_concurrent >= 1"
        )


def load(path: str | os.PathLike | None) -> Config:
    if path is None:
        return from_dict({})
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    return from_dict(raw)

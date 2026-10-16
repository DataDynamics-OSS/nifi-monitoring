import pytest

from nifi_exporter import config


def test_defaults_with_env(monkeypatch):
    monkeypatch.setenv("NIFI_USERNAME", "u")
    monkeypatch.setenv("NIFI_PASSWORD", "p")
    monkeypatch.setenv("NIFI_BASE_URL", "https://nifi:8443/")
    cfg = config.from_dict({})
    assert cfg.nifi.base_url == "https://nifi:8443"
    assert cfg.nifi.auth.username == "u" and cfg.nifi.auth.password == "p"
    assert cfg.collectors.cluster.interval == 15.0
    assert cfg.listen_port == 9103


def test_yaml_load(tmp_path):
    pw = tmp_path / "pw"
    pw.write_text("secret\n")
    f = tmp_path / "c.yaml"
    f.write_text(
        f"""
nifi:
  base_url: https://x:8443
  cluster_name: test
  timeout: 3s
  auth: {{mode: bearer, username: m, password_file: {pw}}}
collectors:
  cluster: {{enabled: false}}
  flow: {{interval: 1m, exclude_pg_ids: [a, b]}}
server:
  listen: 127.0.0.1:0
  log_format: text
"""
    )
    cfg = config.load(f)
    assert cfg.nifi.auth.password == "secret"
    assert cfg.nifi.timeout == 3.0
    assert cfg.collectors.cluster.enabled is False
    assert cfg.collectors.flow.interval == 60.0
    assert cfg.collectors.flow.exclude_pg_ids == ["a", "b"]
    assert cfg.listen_host == "127.0.0.1" and cfg.listen_port == 0


@pytest.mark.parametrize(
    "raw,msg",
    [
        ({"nifi": {"auth": {"mode": "bearer"}}}, "bearer auth requires"),
        ({"nifi": {"auth": {"mode": "mtls"}}}, "mtls auth requires"),
        ({"nifi": {"auth": {"mode": "magic"}}}, "auth.mode"),
        ({"nifi": {"auth": {"mode": "none"}}, "server": {"listen": "nope"}}, "host:port"),
        ({"nifi": {"auth": {"mode": "none"}, "max_concurrency": 0}}, "max_concurrency"),
        (
            {"nifi": {"auth": {"mode": "none"}}, "server": {"basic_auth": {"username": "p"}}},
            "basic_auth requires",
        ),
        # HTTP(TLS 없음)에는 인증 없음만 허용합니다
        (
            {
                "nifi": {
                    "base_url": "http://nifi:8080",
                    "auth": {"mode": "bearer", "username": "u", "password": "p"},
                }
            },
            "plain HTTP",
        ),  # fmt: skip
        (
            {
                "nifi": {
                    "base_url": "http://nifi:8080",
                    "auth": {"mode": "mtls", "cert_file": "c", "key_file": "k"},
                }
            },
            "plain HTTP",
        ),  # fmt: skip
        ({"nifi": {"base_url": "ftp://nifi", "auth": {"mode": "none"}}}, "http:// or https://"),
    ],
)
def test_validation_errors(raw, msg, monkeypatch):
    monkeypatch.delenv("NIFI_EXPORTER_BASIC_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("NIFI_USERNAME", raising=False)
    monkeypatch.delenv("NIFI_PASSWORD", raising=False)
    with pytest.raises(config.ConfigError, match=msg):
        config.from_dict(raw)


def test_basic_auth_from_file_and_env(tmp_path, monkeypatch):
    pw = tmp_path / "metrics-pw"
    pw.write_text("s3cret\n")
    raw = {
        "nifi": {"auth": {"mode": "none"}},
        "server": {"basic_auth": {"username": "prom", "password_file": str(pw)}},
    }
    monkeypatch.delenv("NIFI_EXPORTER_BASIC_AUTH_PASSWORD", raising=False)
    ba = config.from_dict(raw).server.basic_auth
    assert ba.enabled and (ba.username, ba.password) == ("prom", "s3cret")
    monkeypatch.setenv("NIFI_EXPORTER_BASIC_AUTH_PASSWORD", "from-env")
    assert config.from_dict(raw).server.basic_auth.password == "from-env"
    assert not config.from_dict({"nifi": {"auth": {"mode": "none"}}}).server.basic_auth.enabled


def test_plain_http_without_auth(monkeypatch):
    monkeypatch.delenv("NIFI_USERNAME", raising=False)
    monkeypatch.delenv("NIFI_PASSWORD", raising=False)
    cfg = config.from_dict({"nifi": {"base_url": "http://nifi:8080/", "auth": {"mode": "none"}}})
    assert cfg.nifi.base_url == "http://nifi:8080"
    assert cfg.nifi.auth.mode == "none"


def test_log_file_settings(tmp_path):
    raw = {"nifi": {"auth": {"mode": "none"}}}
    srv = config.from_dict(raw).server
    assert (srv.log_file, srv.log_max_size, srv.log_backups) == (None, 50 * 1024**2, 5)
    raw["server"] = {"log_file": "logs/x.log", "log_max_size": "10MB", "log_backups": 2}
    srv = config.from_dict(raw).server
    assert (srv.log_file, srv.log_max_size, srv.log_backups) == ("logs/x.log", 10 * 1024**2, 2)
    with pytest.raises(ValueError, match="invalid size"):
        config.from_dict({**raw, "server": {"log_max_size": "lots"}})
    with pytest.raises(config.ConfigError, match="log_backups"):
        config.from_dict({**raw, "server": {"log_backups": -1}})


def test_log_file_rotates(tmp_path):
    import logging

    from nifi_exporter import logging_setup

    path = tmp_path / "sub" / "x.log"  # 없는 디렉토리는 만듭니다
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        logging_setup.configure("INFO", "text", str(path), max_bytes=200, backups=2)
        for i in range(20):
            logging.getLogger("t").info("line %d", i)
        assert "line 19" in path.read_text()
        assert (tmp_path / "sub" / "x.log.1").exists()
        assert not (tmp_path / "sub" / "x.log.3").exists()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)

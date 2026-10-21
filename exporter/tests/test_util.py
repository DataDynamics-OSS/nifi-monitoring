from datetime import timezone

import pytest

from nifi_exporter.nifi.auth import _jwt_expiry
from nifi_exporter.util import (
    parse_duration,
    parse_heartbeat,
    parse_queued,
    parse_size,
    parse_uptime,
)

from .conftest import make_jwt


@pytest.mark.parametrize(
    "value,expected",
    [("15s", 15.0), ("5m", 300.0), ("1h", 3600.0), ("250ms", 0.25), ("30", 30.0), (12, 12.0)],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("soon")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0 bytes", 0),
        ("1,234 bytes", 1234),
        ("3.5 MB", 3.5 * 1024**2),
        ("1 GB", 1024**3),
        ("0 B", 0),
        ("10 KB", 10 * 1024),
        ("junk", None),
    ],
)
def test_parse_size(value, expected):
    assert parse_size(value) == expected


def test_parse_queued():
    assert parse_queued("1,200 / 3.5 MB") == (1200.0, 3.5 * 1024**2)
    assert parse_queued("39 / 39 KB") == (39.0, 39 * 1024.0)
    assert parse_queued(None) == (None, None)
    assert parse_queued("garbage") == (None, None)


def test_parse_heartbeat_utc_and_default_zone():
    utc = parse_heartbeat("10/15/2026 01:00:00 UTC")
    assert utc is not None and utc.tzinfo == timezone.utc and utc.hour == 1
    kst = parse_heartbeat("10/15/2026 10:00:00 KST", default_tz="Asia/Seoul")
    assert kst is not None and kst.timestamp() == utc.timestamp()
    assert parse_heartbeat("not a date") is None
    assert parse_heartbeat(None) is None


def test_jwt_expiry():
    assert _jwt_expiry(make_jwt(exp=1_800_000_000)) == 1_800_000_000.0
    assert _jwt_expiry(make_jwt()) is None
    assert _jwt_expiry("not-a-jwt") is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("02:40:08.262", 2 * 3600 + 40 * 60 + 8.262),
        ("100:00:00.000", 360000.0),
        ("2 days, 03:04:05.500", 2 * 86400 + 3 * 3600 + 4 * 60 + 5.5),
        ("00:00:01", 1.0),
        ("", None),
        (None, None),
        ("soon", None),
    ],
)
def test_parse_uptime(value, expected):
    if expected is None:
        assert parse_uptime(value) is None
    else:
        assert parse_uptime(value) == pytest.approx(expected)

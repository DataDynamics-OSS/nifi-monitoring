"""NiFi의 사람이 읽는 형식 값을 파싱하는 도우미입니다."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*$")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, None: 1.0}

_SIZE_RE = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*(bytes?|[KMGTP]?B)?\s*$", re.IGNORECASE)
_SIZE_UNITS = {
    None: 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
    "pb": 1024**5,
}

# NiFi는 heartbeat를 서버 시간대의 SimpleDateFormat("MM/dd/yyyy HH:mm:ss z")로 표시합니다.
_HEARTBEAT_RE = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})(?:\s+(\S+))?$")


def parse_duration(value: str | int | float) -> float:
    """'15s', '5m', '250ms', '1h' 또는 숫자(초)를 초 단위로 파싱합니다."""
    if isinstance(value, int | float):
        return float(value)
    m = _DURATION_RE.match(value)
    if not m:
        raise ValueError(f"invalid duration: {value!r}")
    return float(m.group(1)) * _DURATION_UNITS[m.group(2)]


def parse_size(value: str | None) -> float | None:
    """NiFi의 사람이 읽는 크기('3.4 MB', '1 GB', '1,234 bytes')를 바이트로 파싱합니다(1024 기준)."""
    if value is None:
        return None
    m = _SIZE_RE.match(value)
    if not m:
        return None
    number = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower() or None
    if unit and unit.startswith("byte"):
        unit = "bytes"
    return number * _SIZE_UNITS[unit]


def parse_byte_size(value: str | int) -> int:
    """설정의 크기('50MB', '512 KB', 1048576)를 바이트로 파싱합니다(1024 기준)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    size = parse_size(value) if isinstance(value, str) else None
    if size is None:
        raise ValueError(f"invalid size: {value!r}")
    return int(size)


def parse_queued(value: str | None) -> tuple[float | None, float | None]:
    """NiFi의 queued 요약 '12 / 3.4 MB'를 (count, approx_bytes)로 파싱합니다."""
    if not value or "/" not in value:
        return None, None
    left, right = value.split("/", 1)
    try:
        count = float(left.strip().replace(",", ""))
    except ValueError:
        count = None
    return count, parse_size(right.strip())


# NiFi는 JVM uptime을 "HH:mm:ss.SSS"로 줍니다. 시간이 24를 넘을 수 있고, 일 단위가 앞에 붙는
# 형식("2 days, 03:04:05.678")도 함께 받습니다.
_UPTIME_RE = re.compile(r"^\s*(?:(\d+)\s*days?,?\s*)?(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s*$")


def parse_uptime(value: str | None) -> float | None:
    """NiFi의 uptime 문자열을 초로 바꿉니다. 읽을 수 없으면 None을 반환합니다."""
    if not value:
        return None
    m = _UPTIME_RE.match(value)
    if not m:
        return None
    days, hours, minutes, seconds, frac = m.groups()
    total = int(days or 0) * 86400 + int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return total + (float(f"0.{frac}") if frac else 0.0)


def parse_heartbeat(value: str | None, default_tz: str = "UTC") -> datetime | None:
    """클러스터 노드 heartbeat 문자열을 시간대가 있는 datetime으로 파싱합니다.

    NiFi가 출력하는 시간대 약어는 안정적으로 파싱할 수 없으므로 'UTC'/'GMT'/'Z'만
    그대로 따르고, 나머지는 ``default_tz``(설정 가능한 NiFi 서버 시간대)로 해석합니다.
    """
    if not value:
        return None
    m = _HEARTBEAT_RE.match(value.strip())
    if not m:
        return None
    naive = datetime.strptime(m.group(1), "%m/%d/%Y %H:%M:%S")
    zone = (m.group(2) or "").upper()
    if zone in ("UTC", "GMT", "Z"):
        return naive.replace(tzinfo=UTC)
    try:
        return naive.replace(tzinfo=ZoneInfo(default_tz))
    except Exception:  # 설정의 시간대 이름을 모르면 UTC로 대체합니다
        return naive.replace(tzinfo=UTC)


def to_float(value, default: float | None = None) -> float | None:
    """없을 수도 있는 JSON 필드를 가능한 한 숫자로 변환합니다."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

"""``extra`` 필드를 함께 출력하는 JSON 또는 텍스트 로깅입니다."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def _extras(record: logging.LogRecord) -> dict:
    return {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extras(record)
        if extras:
            base += " " + " ".join(f"{k}={v!r}" for k, v in extras.items())
        return base


def configure(
    level: str = "INFO",
    fmt: str = "json",
    log_file: str | None = None,
    max_bytes: int = 50 * 1024**2,
    backups: int = 5,
) -> None:
    """로그를 stdout(기본) 또는 ``log_file``에 씁니다.

    파일은 ``max_bytes``를 넘으면 ``.1`` ~ ``.backups``로 돌립니다. 디렉토리가 없으면 만듭니다.
    """
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

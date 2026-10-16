#!/usr/bin/env python3
"""로컬 시험용 HTTP 수신처입니다. nifi-alert-relay가 보낸 요청을 메모리에 기록합니다.

    python3 alert_sink.py [--port 8080]

POST(또는 PUT)로 받은 요청을 경로·헤더·본문과 함께 기록하고, GET /requests로 돌려줍니다.
경로가 /fail로 시작하면 503을 돌려주어 재시도와 실패 처리를 시험할 수 있습니다.
표준 라이브러리만 씁니다.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECEIVED: list[dict] = []
LOCK = threading.Lock()
LIMIT = 500


class Handler(BaseHTTPRequestHandler):
    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode(errors="replace")
        with LOCK:
            RECEIVED.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                }
            )
            del RECEIVED[:-LIMIT]
        code = 503 if self.path.startswith("/fail") else 200
        self.send_response(code)
        self.end_headers()

    do_POST = do_PUT = _record

    def do_GET(self) -> None:
        if self.path != "/requests":
            self.send_response(404)
            self.end_headers()
            return
        with LOCK:
            data = json.dumps(RECEIVED, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_DELETE(self) -> None:
        with LOCK:
            RECEIVED.clear()
        self.send_response(204)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler 시그니처입니다
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

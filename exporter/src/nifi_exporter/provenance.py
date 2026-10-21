"""Provenance 온디맨드 조회 서비스 ``nifi-provenance-query``입니다.

Processor 하나와 시간 범위를 받아 NiFi Provenance를 조회하고 결과를 HTML 표나 JSON으로
돌려줍니다. Grafana 장애 분석 대시보드의 그래프 링크에서 호출합니다.

    POST /provenance          (searchTerms ProcessorID, startDate, endDate, maxResults)
    GET  /provenance/{id}     finished가 될 때까지 poll_interval 간격으로 폴링합니다
    DELETE /provenance/{id}   성공·실패·타임아웃과 관계없이 항상 정리합니다

범위 없는 조회를 막기 위해 Processor ID와 시간 범위(``at`` 또는 ``from``/``to``)를
필수로 받고, 범위는 ``provenance.max_range``로, 결과 수는 ``provenance.max_results``로
제한합니다. 이벤트 속성(attributes)과 내용(content)은 요청하지도 반환하지도 않습니다.
설정 파일 형식은 exporter와 같고 ``provenance`` 절을 추가로 읽습니다. NiFi 계정은
/provenance 읽기 권한이 필요하므로 보통 exporter와 다른 계정과 설정 파일을 씁니다.
"""

from __future__ import annotations

import argparse
import html
import http
import json
import logging
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from prometheus_client.exposition import ThreadingWSGIServer

from . import __version__, config, logging_setup
from .config import Config, ProvenanceConfig
from .nifi import build_client
from .nifi.client import NiFiAPIError, NiFiClient
from .server import _authorized, _QuietHandler
from .util import parse_duration

log = logging.getLogger(__name__)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# NiFi ProvenanceRequestDTO의 날짜 형식입니다(초 단위)
NIFI_DATE = "%m/%d/%Y %H:%M:%S UTC"
# 반환하는 이벤트 필드입니다. 속성·내용 관련 필드는 넣지 않습니다
EVENT_FIELDS = (
    "eventId",
    "eventTime",
    "eventType",
    "componentId",
    "componentName",
    "groupId",
    "flowFileUuid",
    "fileSizeBytes",
    "clusterNodeAddress",
    "relationship",
    "transitUri",
    "details",
)


class QueryError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class QueryRequest:
    processor_id: str
    start: float  # epoch 초입니다
    end: float
    max_results: int
    clamped: bool = False  # max_range를 넘어 시작 시각을 줄였는지입니다


def parse_time(value: str) -> float:
    """epoch 밀리초(Grafana ``${__from}``, ``${__value.time}``)나 ISO 8601을 epoch 초로 바꿉니다."""
    value = value.strip()
    if value.isdigit():
        return int(value) / 1000.0
    if value.endswith(("Z", "z")):  # Python 3.11 미만의 fromisoformat은 'Z'를 받지 않습니다
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise QueryError(400, f"시각을 해석할 수 없습니다: {value!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def parse_request(params: dict[str, str], cfg: ProvenanceConfig, cluster: str) -> QueryRequest:
    """쿼리 문자열을 검증합니다. Processor ID와 시간 범위가 없으면 거절합니다."""
    pid = params.get("processor_id", "").strip().lower()
    if not UUID_RE.match(pid):
        raise QueryError(400, "processor_id(UUID)가 필요합니다")
    if params.get("cluster") and params["cluster"] != cluster:
        raise QueryError(
            400,
            f"요청한 클러스터 {params['cluster']!r}는 이 서비스가 조회하는 클러스터"
            f"({cluster!r})가 아닙니다",
        )
    if "at" in params:
        end = parse_time(params["at"])
        try:
            window = parse_duration(params.get("window", cfg.default_window))
        except ValueError as e:
            raise QueryError(400, f"window를 해석할 수 없습니다: {params['window']!r}") from e
        start = end - window
    elif "from" in params and "to" in params:
        start, end = parse_time(params["from"]), parse_time(params["to"])
    else:
        raise QueryError(400, "시간 범위가 필요합니다: at(과 window) 또는 from과 to")
    if end <= start:
        raise QueryError(400, "시간 범위의 끝이 시작보다 늦어야 합니다")
    clamped = end - start > cfg.max_range
    if clamped:
        start = end - cfg.max_range
    try:
        max_results = int(params.get("max_results", cfg.max_results))
    except ValueError as e:
        raise QueryError(400, "max_results는 정수여야 합니다") from e
    max_results = max(1, min(max_results, cfg.max_results))
    return QueryRequest(pid, start, end, max_results, clamped)


def _nifi_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime(NIFI_DATE)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProvenanceQuery:
    """NiFi에 질의를 만들고, 끝날 때까지 기다리고, 항상 지웁니다."""

    def __init__(
        self,
        client: NiFiClient,
        cfg: ProvenanceConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._cfg = cfg
        self._sleep = sleep
        self._clock = clock

    def run(self, req: QueryRequest) -> dict:
        body = {
            "provenance": {
                "request": {
                    "maxResults": req.max_results,
                    "summarize": True,
                    "incrementalResults": False,
                    # NiFi는 초 단위로 받으므로 범위를 바깥쪽으로 반올림합니다
                    "startDate": _nifi_date(int(req.start)),
                    "endDate": _nifi_date(-int(-req.end // 1)),
                    "searchTerms": {"ProcessorID": {"value": req.processor_id, "inverse": False}},
                }
            }
        }
        try:
            prov = self._client.request_json(
                "POST", "/provenance", body=body, endpoint="provenance"
            )["provenance"]
        except NiFiAPIError as e:
            raise _api_error(e) from e
        qid = prov["id"]
        try:
            deadline = self._clock() + self._cfg.query_timeout
            while not prov.get("finished"):
                if self._clock() >= deadline:
                    raise QueryError(
                        504,
                        f"NiFi 질의가 {self._cfg.query_timeout:g}초 안에 끝나지 않았습니다"
                        f"({prov.get('percentCompleted', 0)}%). 시간 범위를 줄여 다시 조회합니다",
                    )
                self._sleep(self._cfg.poll_interval)
                prov = self._client.get_json(f"/provenance/{qid}", endpoint="provenance")[
                    "provenance"
                ]
        except NiFiAPIError as e:
            raise _api_error(e) from e
        finally:
            try:
                self._client.request_json("DELETE", f"/provenance/{qid}", endpoint="provenance")
            except NiFiAPIError as e:
                # NiFi가 만료 시각(기본 30분)이 지나면 스스로 지우므로 경고만 남깁니다
                log.warning("provenance query delete failed", extra={"error": str(e)})

        results = prov.get("results") or {}
        events = [
            {k: ev.get(k) for k in EVENT_FIELDS} for ev in results.get("provenanceEvents", [])
        ]
        return {
            "processor_id": req.processor_id,
            "start": _iso(req.start),
            "end": _iso(req.end),
            "clamped": req.clamped,
            "max_results": req.max_results,
            "total": results.get("total"),
            "truncated": len(events) >= req.max_results,
            "oldest_event": results.get("oldestEvent"),
            "errors": results.get("errors") or [],
            "events": events,
        }


def _api_error(e: NiFiAPIError) -> QueryError:
    if e.status in (401, 403):
        return QueryError(
            502,
            f"NiFi가 조회를 거부했습니다(HTTP {e.status}). 서비스 계정에 /provenance 읽기"
            "(query provenance) 권한과 대상 컴포넌트의 Provenance 보기(view provenance) "
            "권한이 필요합니다",
        )
    return QueryError(502, f"NiFi 요청이 실패했습니다: {e}")


# -- HTTP ----------------------------------------------------------------------

STYLE = """body{font-family:sans-serif;margin:16px;color:#222}
table{border-collapse:collapse;font-size:13px}th,td{border:1px solid #ccc;padding:3px 6px;
text-align:left;vertical-align:top}th{background:#f3f3f3}.note{color:#a15c00}.err{color:#b00}
code{font-size:12px}"""

USAGE = """<p>Processor 하나의 Provenance 이벤트를 조회합니다. 속성과 내용은 보여 주지 않습니다.</p>
<pre>GET /provenance?processor_id=&lt;UUID&gt;&amp;at=&lt;epoch ms|ISO 8601&gt;[&amp;window=5m]
GET /provenance?processor_id=&lt;UUID&gt;&amp;from=&lt;시각&gt;&amp;to=&lt;시각&gt;
선택: cluster=&lt;이름&gt; (다르면 거절), max_results=&lt;N&gt;, format=json</pre>"""


def _page(title: str, body: str) -> bytes:
    return (
        f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><h2>{html.escape(title)}</h2>{body}</body></html>"
    ).encode()


def _cell(value) -> str:
    return "" if value is None else str(value)


def render_html(result: dict) -> bytes:
    e = html.escape
    events = result["events"]
    name = next((ev["componentName"] for ev in events if ev.get("componentName")), None)
    parts = [
        f"<p>Processor <b>{e(name or '')}</b> <code>{e(result['processor_id'])}</code><br>"
        f"범위 {e(result['start'])} ~ {e(result['end'])} (UTC) · "
        f"이벤트 {len(events)}건 (NiFi 집계 {e(str(result['total']))})</p>"
    ]
    if result["clamped"]:
        parts.append(
            "<p class='note'>요청 범위가 최대 조회 범위를 넘어 끝 시각 기준으로 줄였습니다.</p>"
        )
    if result["truncated"]:
        parts.append(
            f"<p class='note'>최대 {result['max_results']}건까지만 가져왔습니다. "
            "범위를 좁혀 다시 조회합니다.</p>"
        )
    if result["oldest_event"]:
        parts.append(f"<p>NiFi에 남아 있는 가장 오래된 이벤트: {e(result['oldest_event'])}</p>")
    for err in result["errors"]:
        parts.append(f"<p class='err'>{e(str(err))}</p>")
    cols = [
        ("eventTime", "시각"),
        ("eventType", "이벤트"),
        ("clusterNodeAddress", "노드"),
        ("flowFileUuid", "FlowFile UUID"),
        ("fileSizeBytes", "크기(bytes)"),
        ("relationship", "Relationship"),
        ("transitUri", "Transit URI"),
        ("details", "상세"),
    ]
    head = "".join(f"<th>{label}</th>" for _, label in cols)
    rows = "".join(
        "<tr>" + "".join(f"<td>{e(_cell(ev.get(k)))}</td>" for k, _ in cols) + "</tr>"
        for ev in events
    )
    parts.append(f"<table><tr>{head}</tr>{rows}</table>")
    return _page("Provenance 조회", "".join(parts))


def make_app(
    cluster: str,
    cfg: ProvenanceConfig,
    query: ProvenanceQuery,
    basic_auth: tuple[str, str] | None = None,
):
    slots = threading.BoundedSemaphore(cfg.max_concurrent)

    def respond(start_response, status: str, body: bytes, ctype: str) -> list[bytes]:
        start_response(status, [("Content-Type", ctype), ("Cache-Control", "no-store")])
        return [body]

    def app(environ, start_response) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        if path == "/healthz":
            return respond(start_response, "200 OK", b"ok\n", "text/plain")
        if basic_auth and not _authorized(environ, basic_auth):
            start_response(
                "401 Unauthorized",
                [
                    ("Content-Type", "text/plain"),
                    ("WWW-Authenticate", 'Basic realm="nifi-provenance-query"'),
                ],
            )
            return [b"unauthorized\n"]
        if path == "/":
            return respond(
                start_response,
                "200 OK",
                _page("Provenance 조회", USAGE),
                "text/html; charset=utf-8",
            )
        if path != "/provenance":
            return respond(start_response, "404 Not Found", b"not found\n", "text/plain")

        params = {k: v[-1] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        as_json = params.get("format") == "json"
        started = time.monotonic()
        try:
            req = parse_request(params, cfg, cluster)
            if not slots.acquire(blocking=False):
                raise QueryError(
                    429, f"동시 조회가 {cfg.max_concurrent}건을 넘었습니다. 잠시 뒤 다시 조회합니다"
                )
            try:
                result = query.run(req)
            finally:
                slots.release()
        except QueryError as e:
            log.info(
                "provenance query rejected",
                extra={"status": e.status, "error": e.message, "params": params},
            )
            status = f"{e.status} {http.HTTPStatus(e.status).phrase}"
            if as_json:
                body = json.dumps({"error": e.message}, ensure_ascii=False).encode()
                return respond(start_response, status, body, "application/json")
            page = _page("Provenance 조회", f"<p class='err'>{html.escape(e.message)}</p>{USAGE}")
            return respond(start_response, status, page, "text/html; charset=utf-8")

        log.info(
            "provenance query",
            extra={
                "processor_id": req.processor_id,
                "start": result["start"],
                "end": result["end"],
                "events": len(result["events"]),
                "duration": round(time.monotonic() - started, 3),
                "remote": environ.get("REMOTE_ADDR"),
            },
        )
        if as_json:
            body = json.dumps(result, ensure_ascii=False).encode()
            return respond(start_response, "200 OK", body, "application/json")
        return respond(start_response, "200 OK", render_html(result), "text/html; charset=utf-8")

    return app


def serve(cfg: Config) -> None:
    client = build_client(cfg.nifi)
    ba = cfg.server.basic_auth
    credentials = (ba.username, ba.password) if ba.enabled and ba.password else None
    app = make_app(
        cfg.nifi.cluster_name, cfg.provenance, ProvenanceQuery(client, cfg.provenance), credentials
    )
    host, port = cfg.provenance.listen.rsplit(":", 1)
    httpd = make_server(host, int(port), app, ThreadingWSGIServer, handler_class=_QuietHandler)

    def stop(signum, frame):  # noqa: ARG001 - signal 핸들러 시그니처입니다
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    log.info(
        "starting nifi-provenance-query",
        extra={"version": __version__, "listen": cfg.provenance.listen},
    )
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nifi-provenance-query",
        description="On-demand NiFi Provenance query service (one processor, bounded time range)",
    )
    parser.add_argument("-c", "--config", help="path to YAML config (env overrides apply)")
    parser.add_argument("--check-config", action="store_true", help="validate config and exit")
    parser.add_argument(
        "--version", action="version", version=f"nifi-provenance-query {__version__}"
    )
    args = parser.parse_args(argv)
    try:
        cfg = config.load(args.config)
    except (config.ConfigError, OSError, ValueError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if args.check_config:
        print("config ok")
        return 0
    srv = cfg.server
    logging_setup.configure(
        srv.log_level, srv.log_format, srv.log_file, srv.log_max_size, srv.log_backups
    )
    serve(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

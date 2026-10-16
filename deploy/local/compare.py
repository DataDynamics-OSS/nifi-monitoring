#!/usr/bin/env python3
"""NiFi 자체 수치와 Prometheus에 저장된 값을 대조합니다 (체크리스트 3단계 "수치 대조").

CN=nifi-monitor로 NiFi를 읽고 Prometheus를 조회한 뒤, 항목마다 한 줄씩 출력합니다.
하나라도 실패하면 종료 코드 1로 끝납니다.

    python3 compare.py [--nifi https://localhost:18443] [--prom http://localhost:19090]

TLS 없는 NiFi(http:// 주소)는 인증서 없이 읽습니다. 내장 엔드포인트를 스크레이프하지 않는
환경(예: deploy/cfm)에서는 --no-builtin으로 내장 엔드포인트 합계 비교를 뺍니다.

exporter의 수집 시점과 이 스크립트의 조회 시점 사이에 변하는 값(heap, 5분 통계)은
비교하지 않습니다. 큐 적체는 비교하되, 그 사이에 계속 자라는 큐를 위해 허용 오차
(2%와 10개 중 큰 값)를 둡니다.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CERTS = Path(__file__).resolve().parent / "certs"


class Checker:
    def __init__(self, nifi: str, prom: str, cluster: str, tolerance: float, slack: float) -> None:
        self.nifi, self.prom, self.cluster = nifi.rstrip("/"), prom.rstrip("/"), cluster
        self.tolerance, self.slack = tolerance, slack
        self.ctx = None
        if self.nifi.startswith("https://"):
            self.ctx = ssl.create_default_context(cafile=str(CERTS / "ca.pem"))
            self.ctx.load_cert_chain(
                str(CERTS / "nifi-monitor.pem"), str(CERTS / "nifi-monitor.key")
            )
        self.failed = 0

    def api(self, path: str) -> dict:
        req = urllib.request.Request(self.nifi + "/nifi-api" + path)
        with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
            return json.load(resp)

    def query(self, expr: str) -> dict[tuple, float]:
        url = self.prom + "/api/v1/query?query=" + urllib.parse.quote(expr)
        with urllib.request.urlopen(url, timeout=30) as resp:
            result = json.load(resp)["data"]["result"]
        return {tuple(sorted(r["metric"].items())): float(r["value"][1]) for r in result}

    def scalar(self, expr: str) -> float | None:
        values = list(self.query(expr).values())
        return values[0] if len(values) == 1 else None

    def check(self, name: str, nifi_value, prom_value) -> None:
        if prom_value is None:
            status = "FAIL"
        elif nifi_value == prom_value:
            status = "ok  "
        elif abs(nifi_value - prom_value) <= max(self.tolerance * abs(nifi_value), self.slack):
            status = "ok ~"  # 허용 오차 이내입니다: 수집과 조회 사이에 값이 바뀌었습니다
        else:
            status = "FAIL"
        self.failed += status == "FAIL"
        print(f"{status} {name}: nifi={nifi_value} prometheus={prom_value}")


def walk(snap: dict):
    yield "pg", snap
    for e in snap.get("connectionStatusSnapshots") or []:
        yield "connection", e["connectionStatusSnapshot"]
    for e in snap.get("processorStatusSnapshots") or []:
        yield "processor", e["processorStatusSnapshot"]
    for e in snap.get("processGroupStatusSnapshots") or []:
        yield from walk(e["processGroupStatusSnapshot"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--nifi", default="https://localhost:18443", help="NiFi 주소 (모니터 계정 인증서로 접속)"
    )
    ap.add_argument("--prom", default="http://localhost:19090", help="Prometheus 주소")
    ap.add_argument("--cluster", default="local", help="cluster 레이블 값")
    ap.add_argument("--tolerance", type=float, default=0.02, help="계속 변하는 값의 상대 허용 오차")
    ap.add_argument("--slack", type=float, default=10, help="계속 변하는 값의 절대 허용 오차")
    ap.add_argument("--no-builtin", action="store_true", help="내장 엔드포인트 합계 비교를 뺍니다")
    args = ap.parse_args()
    c = Checker(args.nifi, args.prom, args.cluster, args.tolerance, args.slack)
    sel = f'cluster="{c.cluster}"'

    nodes = c.api("/controller/cluster")["cluster"]["nodes"]
    c.check("전체 노드 수", len(nodes), c.scalar(f"nifi_cluster_nodes_total{{{sel}}}"))
    c.check(
        "연결된 노드 수",
        sum(n["status"] == "CONNECTED" for n in nodes),
        c.scalar(f"nifi_cluster_nodes_connected{{{sel}}}"),
    )
    for n in nodes:
        c.check(
            f"노드 {n['address']} 적체 FlowFile",
            n["flowFilesQueued"],
            c.scalar(f'nifi_node_queued_flowfiles{{{sel},node_id="{n["nodeId"]}"}}'),
        )

    root = c.api("/flow/process-groups/root/status?recursive=true")["processGroupStatus"]
    items = list(walk(root["aggregateSnapshot"]))
    for kind, s in items:
        if kind == "connection":
            sel_c = f'{sel},connection_id="{s["id"]}"'
            c.check(
                f"큐 {s['sourceName']}→{s['destinationName']} 적체",
                s["flowFilesQueued"],
                c.scalar(f"nifi_connection_queued_flowfiles{{{sel_c}}}"),
            )
            c.check(
                f"큐 {s['sourceName']}→{s['destinationName']} 사용률(%)",
                s["percentUseCount"],
                c.scalar(f"nifi_connection_percent_used_count{{{sel_c}}}"),
            )
            # 내장 엔드포인트는 노드별 값이므로, 그 합이 exporter의 집계값과 같아야 합니다
            if args.no_builtin:
                continue
            c.check(
                f"큐 {s['sourceName']}→{s['destinationName']} 내장 엔드포인트 합계",
                s["flowFilesQueued"],
                c.scalar(
                    f'sum(nifi_amount_items_queued{{{sel},job="nifi-builtin",'
                    f'component_id="{s["id"]}"}})'
                ),
            )
        elif kind == "pg":
            c.check(
                f"PG {s['name']} 적체",
                s["flowFilesQueued"],
                c.scalar(f'nifi_pg_queued_flowfiles{{{sel},pg_id="{s["id"]}"}}'),
            )
        elif kind == "processor":
            c.check(
                f"Processor {s['name']} Running 여부",
                1 if s["runStatus"] == "Running" else 0,
                c.scalar(f'nifi_processor_running{{{sel},processor_id="{s["id"]}"}}'),
            )

    invalid = sum(1 for k, s in items if k == "processor" and s["runStatus"] == "Invalid")
    c.check("Invalid Processor 수", invalid, c.scalar(f"nifi:processors_invalid:count{{{sel}}}"))
    print(f"{c.failed} failed")
    sys.exit(1 if c.failed else 0)


if __name__ == "__main__":
    main()

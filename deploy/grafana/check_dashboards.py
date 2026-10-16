#!/usr/bin/env python3
"""NiFi 대시보드의 모든 패널 쿼리를 실행 중인 Grafana에서 돌려 봅니다.

Grafana의 /api/ds/query(패널이 쓰는 것과 같은 경로)를 쓰며, 템플릿 변수는 각 변수
쿼리의 첫 값으로 정합니다(All이면 ".*"). 패널마다 ok / EMPTY(시계열 없음) / ERROR를
보고합니다. ERROR가 있거나 --allow-empty에 없는 EMPTY 패널이 있으면 1로 종료합니다.

    python3 check_dashboards.py [--grafana http://localhost:13000] [--user admin:localtest]
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DASHBOARDS = Path(__file__).resolve().parent / "dashboards"


class Grafana:
    def __init__(self, url: str, user: str) -> None:
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(user.encode()).decode()

    def request(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": self.auth, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b"{}") | {"_status": e.code}

    def instant(self, expr: str) -> list[dict]:
        q = urllib.parse.quote(expr)
        body = self.request(f"/api/datasources/proxy/uid/prometheus/api/v1/query?query={q}")
        return body.get("data", {}).get("result", [])


def substitute(expr: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        expr = expr.replace(f"${name}", value)
    return expr


def resolve_variables(g: Grafana, dashboard: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for var in dashboard["templating"]["list"]:
        if var["type"] == "constant":  # 링크용 상수(provenance_url)이며 쿼리에는 쓰지 않습니다
            values[var["name"]] = var["query"]
            continue
        query = substitute(var["query"]["query"], values)
        if query.startswith("label_values("):
            metric, label = re.fullmatch(r"label_values\((.*), *(\w+)\)", query).groups()
            options = sorted({r["metric"].get(label, "") for r in g.instant(metric)} - {""})
        else:  # query_result(<expr>)와 value/text를 뽑는 정규식입니다
            inner = re.fullmatch(r"query_result\((.*)\)", query).group(1)
            regex = re.compile(var["regex"].strip("/").replace("(?<", "(?P<"))
            options = []
            for r in g.instant(inner):
                text = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(r["metric"].items())) + "}"
                m = regex.search(text)
                if m:
                    options.append(m.group("value"))
        if not options:
            raise SystemExit(f"{dashboard['uid']}: 변수 {var['name']}에 선택지가 없습니다")
        values[var["name"]] = var["allValue"] if var.get("includeAll") else options[0]
        print(f"  var {var['name']} = {values[var['name']]} (선택지 {len(options)}개)")
    return values


def check_panel(g: Grafana, panel: dict, values: dict[str, str]) -> tuple[str, str]:
    queries = []
    for t in panel.get("targets", []):
        q = dict(t)
        q["expr"] = substitute(t["expr"], values)
        q.setdefault("intervalMs", 15000)
        q.setdefault("maxDataPoints", 200)
        queries.append(q)
    body = g.request("/api/ds/query", {"from": "now-30m", "to": "now", "queries": queries})
    if "results" not in body:
        return "ERROR", str(body)[:200]
    rows = 0
    for ref, res in body["results"].items():
        if res.get("error"):
            return "ERROR", f"{ref}: {res['error'][:200]}"
        for frame in res.get("frames", []):
            values_ = frame.get("data", {}).get("values", [])
            rows += len(values_[0]) if values_ else 0
    return ("ok", f"{rows}행") if rows else ("EMPTY", "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grafana", default="http://localhost:13000", help="Grafana 주소")
    ap.add_argument("--user", default="admin:localtest", help="Grafana 사용자:비밀번호")
    ap.add_argument(
        "--allow-empty",
        nargs="*",
        default=[],
        help="값이 없어도 되는 패널 제목 (지금 보여 줄 데이터가 없는 패널)",
    )
    args = ap.parse_args()
    g = Grafana(args.grafana, args.user)

    errors = empty = 0
    for path in sorted(DASHBOARDS.glob("*.json")):
        dashboard = json.loads(path.read_text())
        print(f"{dashboard['uid']}")
        values = resolve_variables(g, dashboard)
        for panel in dashboard["panels"]:
            if panel["type"] in ("row", "text"):
                continue
            status, detail = check_panel(g, panel, values)
            if status == "EMPTY" and panel["title"] in args.allow_empty:
                status = "ok (빈 값 허용)"
            errors += status == "ERROR"
            empty += status == "EMPTY"
            print(f"  {status:5} {panel['title']} {detail}")
        for ann in dashboard["annotations"]["list"]:
            expr = substitute(ann["expr"], values)
            body = g.request(
                "/api/ds/query",
                {
                    "from": "now-1h",
                    "to": "now",
                    "queries": [{"refId": "A", "datasource": ann["datasource"], "expr": expr}],
                },
            )
            ok = "results" in body and not body["results"]["A"].get("error")
            errors += not ok
            print(f"  {'ok' if ok else 'ERROR'} annotation {ann['name']}")
    print(f"{errors} errors, {empty} empty")
    sys.exit(1 if errors or empty else 0)


if __name__ == "__main__":
    main()

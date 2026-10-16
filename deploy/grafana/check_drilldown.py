#!/usr/bin/env python3
"""표 셀의 data link를 실제 브라우저에서 클릭해 드릴다운이 맞는 화면으로 가는지 확인합니다.

headless Chromium을 DevTools 프로토콜(docs/diagrams/cdp.mjs, Node 22 이상)로 조작합니다.
경우마다 출발 대시보드를 열고, 표에서 지정한 셀을 클릭한 뒤 링크 메뉴에서 항목을
고릅니다. 이동한 주소의 대시보드 uid와 var-pg_id, 도착 화면의 표에 나와야 할 이름을
확인합니다. 로컬 스택(deploy/local)의 시험 Flow(/ingest, /ingest/errors)를 기준으로 합니다.
표 셀 data link 6개(프로세스 그룹 3, 프로세서 1, 큐 2)를 모두 확인합니다.

Provenance 링크 3개(프로세서 표, 장애 분석의 ERROR Bulletin·가장 느린 프로세서 그래프)는
새 탭으로 열리므로 클릭하지 않고 링크 주소를 읽습니다. 그래프는 점을 클릭해 뜨는 툴팁에서
읽습니다. 주소의 processor_id·at를 확인한 뒤 그 주소로 nifi-provenance-query를 직접 호출해
200 응답과 이벤트의 Processor를 확인합니다. 하나라도 실패하면 1로 종료합니다.

Grafana 11.3.0에서는 같은 대시보드로 가는 링크("하위 그룹으로")를 누르면 주소와 변수는
바뀌지만 패널이 다음 자동 새로고침(30초)까지 이전 그룹의 값을 보여 줍니다. 11.6.0과
12.0.0에서는 바로 바뀝니다. 그래서 Grafana 11.6 이상을 요구합니다.

    python3 check_drilldown.py [--grafana http://localhost:13000] [--user admin:localtest]
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CDP = Path(__file__).resolve().parents[2] / "docs" / "diagrams" / "cdp.mjs"

# (이름, 출발 uid, 출발 그룹 경로, 클릭할 셀 텍스트, 링크 제목,
#  도착 uid, 도착 그룹 경로, 도착 표에 있어야 할 텍스트)
CASES = [
    (
        "그룹 → 하위 그룹",
        "nifi-process-groups",
        "/",
        "/ingest",
        "하위 그룹으로",
        "nifi-process-groups",
        "/ingest",
        ["/ingest/errors"],
    ),
    (
        "그룹 → 프로세서",
        "nifi-process-groups",
        "/",
        "/ingest",
        "이 그룹의 프로세서",
        "nifi-processors",
        "/ingest",
        ["generate", "sink"],
    ),
    (
        "그룹 → 큐",
        "nifi-process-groups",
        "/",
        "/ingest",
        "이 그룹의 큐",
        "nifi-queues",
        "/ingest",
        ["generate", "sink"],
    ),
    (
        "프로세서 → 큐",
        "nifi-processors",
        "/ingest/errors",
        "log-error",
        "이 그룹의 큐",
        "nifi-queues",
        "/ingest/errors",
        ["generate-errors", "log-error"],
    ),
    (
        "큐(보내는 쪽) → 프로세서",
        "nifi-queues",
        "/ingest",
        "generate",
        "이 그룹의 프로세서",
        "nifi-processors",
        "/ingest",
        ["generate", "sink"],
    ),
    (
        "큐(받는 쪽) → 프로세서",
        "nifi-queues",
        "/ingest/errors",
        "log-error",
        "이 그룹의 프로세서",
        "nifi-processors",
        "/ingest/errors",
        ["generate-errors", "log-error"],
    ),
]

# (이름, 대시보드 uid, 그룹 경로 또는 None, 표 셀 텍스트 또는 그래프 패널 제목,
#  이벤트가 있어야 할 Processor 이름 또는 None)
PROVENANCE_CASES = [
    ("프로세서 표 → Provenance", "nifi-processors", "/ingest/errors", "log-error", "log-error"),
    (
        "ERROR Bulletin 그래프 → Provenance",
        "nifi-incident",
        None,
        "프로세서별 ERROR Bulletin",
        "log-error",
    ),
    ("가장 느린 프로세서 그래프 → Provenance", "nifi-incident", None, "가장 느린 프로세서", None),
]
PROVENANCE_TITLES = ("Provenance 조회 (끝 시각 기준 5분)", "Provenance 조회 (이 시점까지 5분)")

# 표 셀을 클릭해 뜨는 메뉴나, 그래프의 점을 클릭해 고정한 툴팁에서 Provenance 링크
# 주소를 읽습니다. 그래프는 점이 있는 위치를 찾을 때까지 여러 지점을 클릭합니다
PROVENANCE_JS = """(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const [kind, text, titles] = %s;
  const found = () => [...document.querySelectorAll('a')]
    .find((a) => titles.includes(a.textContent.trim()));
  if (kind === 'cell') {
    let target;
    for (let i = 0; i < 40 && !target; i++, await sleep(500))
      target = [...document.querySelectorAll('[role=cell] button')]
        .find((e) => e.textContent.trim() === text);
    if (!target) return JSON.stringify({error: 'cell not found: ' + text});
    target.click();
    await sleep(800);
  } else {
    let over;
    for (let i = 0; i < 40 && !over; i++, await sleep(500)) {
      const panel = [...document.querySelectorAll('section')]
        .find((e) => e.textContent.includes(text));
      over = panel && panel.querySelector('.u-over');
    }
    if (!over) return JSON.stringify({error: 'graph not found: ' + text});
    const r = over.getBoundingClientRect();
    for (const fx of [0.98, 0.9, 0.7, 0.5]) for (const fy of [0.1, 0.3, 0.5, 0.7, 0.9]) {
      if (found()) break;
      const opt = {bubbles: true, view: window,
                   clientX: r.left + r.width * fx, clientY: r.top + r.height * fy};
      for (const t of ['mouseenter', 'mousemove']) over.dispatchEvent(new MouseEvent(t, opt));
      await sleep(150);
      for (const t of ['mousedown', 'mouseup', 'click']) over.dispatchEvent(new MouseEvent(t, opt));
      await sleep(400);
    }
  }
  const a = found();
  if (!a) return JSON.stringify({error: 'provenance link not found'});
  return JSON.stringify({href: a.href, target: a.target});
})()"""

# 셀을 클릭하고, 링크가 여러 개면 뜨는 메뉴에서 제목으로 고른 뒤, 도착 화면의 표가
# 기대한 텍스트를 보일 때까지(최대 20초) 기다립니다
CLICK_JS = """(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const [cellText, title, expect] = %s;
  const cells = () => [...document.querySelectorAll('[role=cell]')];
  let target;
  for (let i = 0; i < 40 && !target; i++, await sleep(500))
    target = cells()
      .map((c) => c.querySelector('a,button'))
      .find((e) => e && e.textContent.trim() === cellText);
  if (!target) return JSON.stringify({error: 'cell not found: ' + cellText});
  const start = location.href;
  target.click();
  await sleep(800);
  if (location.href === start) {
    const item = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === title);
    if (!item) return JSON.stringify({error: 'menu item not found: ' + title});
    item.click();
  }
  let seen = [];
  for (let i = 0; i < 40; i++, await sleep(500)) {
    const texts = new Set(cells().map((c) => c.textContent.trim()));
    seen = expect.filter((t) => texts.has(t));
    if (location.href !== start && seen.length === expect.length) break;
  }
  return JSON.stringify({href: location.href, seen});
})()"""


def prom_query(grafana: str, auth: str, expr: str) -> list[dict]:
    url = f"{grafana}/api/datasources/proxy/uid/prometheus/api/v1/query?"
    url += urllib.parse.urlencode({"query": expr})
    req = urllib.request.Request(url, headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["data"]["result"]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--grafana", default="http://localhost:13000")
    ap.add_argument("--user", default="admin:localtest")
    ap.add_argument("--cluster", default="local")
    args = ap.parse_args()
    grafana = args.grafana.rstrip("/")
    auth = "Basic " + base64.b64encode(args.user.encode()).decode()

    pg_ids = {
        r["metric"]["pg_path"]: r["metric"]["pg_id"]
        for r in prom_query(grafana, auth, f'nifi_pg_info{{cluster="{args.cluster}"}}')
    }
    missing = {c[2] for c in CASES} | {c[6] for c in CASES}
    missing -= pg_ids.keys()
    if missing:
        print(f"Process Group 없음: {sorted(missing)} (deploy/local 시험 Flow가 필요합니다)")
        return 1

    shots = []
    for _, src_uid, src_path, cell, title, _, _, expect in CASES:
        shots.append(
            {
                "url": dashboard_url(grafana, src_uid, args.cluster, pg_ids[src_path]),
                "wait": 3000,
                "eval": [CLICK_JS % json.dumps([cell, title, expect], ensure_ascii=False)],
            }
        )
    for _, uid, path, text, _ in PROVENANCE_CASES:
        kind = "cell" if path else "graph"
        js = PROVENANCE_JS % json.dumps([kind, text, PROVENANCE_TITLES], ensure_ascii=False)
        shots.append(
            {
                "url": dashboard_url(grafana, uid, args.cluster, pg_ids[path] if path else None),
                "wait": 3000,
                "eval": [js],
            }
        )

    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
        jobs = {"width": 1600, "height": 1000, "scale": 1, "shots": shots}
        json.dump(jobs, f, ensure_ascii=False)
        f.flush()
        cmd = ["node", str(CDP), f.name]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith(("{", "eval error"))]
    if len(lines) != len(shots):
        print(out.stdout, out.stderr, sep="\n")
        print(f"결과 {len(lines)}개, 예상 {len(shots)}개")
        return 1
    results = [_parse(line) for line in lines]

    failed = 0
    for case, res in zip(CASES, results, strict=False):
        name, _, _, cell, title, dst_uid, dst_path, expect = case
        problems = []
        if "error" in res:
            problems.append(res["error"])
        else:
            parsed = urllib.parse.urlparse(res["href"])
            params = urllib.parse.parse_qs(parsed.query)
            if not parsed.path.startswith(f"/d/{dst_uid}/"):
                problems.append(f"대시보드 {parsed.path}")
            if params.get("var-pg_id") != [pg_ids[dst_path]]:
                problems.append(f"var-pg_id {params.get('var-pg_id')} (기대 {dst_path})")
            if lacking := [t for t in expect if t not in res["seen"]]:
                problems.append(f"표에 없음 {lacking}")
        failed += report(f"{name} ({cell} → {title})", problems)

    processors = {
        r["metric"]["processor_id"]: r["metric"]["name"]
        for r in prom_query(grafana, auth, f'nifi_processor_info{{cluster="{args.cluster}"}}')
    }
    for case, res in zip(PROVENANCE_CASES, results[len(CASES) :], strict=True):
        name, _, _, _, expect_name = case
        problems = (
            res.get("error")
            and [res["error"]]
            or check_provenance(res, args.cluster, processors, expect_name)
        )
        failed += report(name, problems)
    total = len(CASES) + len(PROVENANCE_CASES)
    print(f"{total - failed} passed, {failed} failed")
    return 1 if failed else 0


def dashboard_url(grafana: str, uid: str, cluster: str, pg_id: str | None) -> str:
    params = {"var-cluster": cluster, "from": "now-30m", "to": "now"}
    if pg_id:
        params["var-pg_id"] = pg_id
    return f"{grafana}/d/{uid}/{uid}?{urllib.parse.urlencode(params)}"


def _parse(line: str) -> dict:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"error": line}


def check_provenance(
    res: dict, cluster: str, processors: dict[str, str], expect_name: str | None
) -> list[str]:
    """링크 주소의 매개변수를 확인하고, 그 주소로 서비스를 호출해 결과를 확인합니다."""
    problems = []
    parsed = urllib.parse.urlparse(res["href"])
    params = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
    pid = params.get("processor_id", "")
    if res.get("target") != "_blank":
        problems.append("새 탭으로 열리지 않음")
    if parsed.path != "/provenance" or params.get("cluster") != cluster:
        problems.append(f"주소 {res['href']}")
    if pid not in processors:
        problems.append(f"processor_id {pid!r}가 nifi_processor_info에 없음")
    if expect_name and processors.get(pid) != expect_name:
        problems.append(f"Processor {processors.get(pid)!r} (기대 {expect_name})")
    if not params.get("at", "").isdigit():
        problems.append(f"at {params.get('at')!r}")
    if problems:
        return problems
    try:
        with urllib.request.urlopen(res["href"] + "&format=json", timeout=90) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, ValueError) as e:
        return [f"서비스 호출 실패: {e}"]
    events = body.get("events", [])
    if any(ev.get("componentId") != pid for ev in events):
        problems.append("다른 Processor의 이벤트가 섞임")
    if expect_name and not events:
        problems.append("이벤트 0건")
    print(f"  {processors[pid]}: 이벤트 {len(events)}건, {body['start']} ~ {body['end']}")
    return problems


def report(name: str, problems: list[str]) -> bool:
    print(f"{name}: " + ("ok" if not problems else "FAIL " + "; ".join(problems)))
    return bool(problems)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""로컬 스택에서 Grafana, Alertmanager, NiFi UI 화면을 캡처합니다.

    cd deploy/local && docker compose up -d && python3 seed.py   # 약 30분 동안 돌려 둡니다
    docker compose --profile screenshots up -d nifi-ui-proxy      # 인증서 없이 NiFi UI에 접근합니다
    python3 docs/diagrams/screenshots.py

DevTools 프로토콜(docs/diagrams/cdp.mjs, Node 22 이상)로 headless Chromium을 조작해
docs/images/screenshots/*.png를 씁니다. Grafana는 익명 조회를 허용해야 합니다(로컬
compose 파일은 허용합니다). 키오스크 모드, 라이트 테마, 최근 1시간으로 찍습니다. NiFi
화면은 관리자 클라이언트 인증서를 제시하는 nifi-ui-proxy를 거치며, 캔버스는 양쪽 패널을
접고 화면 맞춤한 상태로 찍습니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "images" / "screenshots"
DASHBOARDS = ROOT / "deploy" / "grafana" / "dashboards"
CDP = Path(__file__).resolve().parent / "cdp.mjs"
WIDTH = 1600
GRID_PX = 38  # 폭 1600px 기준 Grafana 그리드 한 행(30px)과 간격입니다
TOP_PX = 110  # 키오스크 모드의 변수 막대와 여백입니다

# NiFi 캔버스: 앞 페이지에서 내비게이션 패널을 접었을 수 있습니다(상태가 세션에 남습니다).
# 접힌 상태에서는 나침반 아이콘만 그려지므로 그것을 눌러 펼칩니다. 그다음 "화면 맞춤"
# (축소 버튼 다음 버튼)을 누르고 양쪽 패널을 접습니다(펼친 패널에는 fa-minus-square-o
# 토글이 표시됩니다).
NIFI_FIT = (
    "(async()=>{if(!document.querySelector('.navigation-control-expansion')){"
    "document.querySelector('.fa-compass')?.click();"
    "await new Promise(r=>setTimeout(r,800))}"
    "const b=[...document.querySelectorAll('button')];"
    "const i=b.findIndex(x=>x.querySelector('.fa-search-minus'));"
    "if(i<0)return 'no zoom controls';b[i+1].click();return 'fit'})()"
)
NIFI_COLLAPSE = (
    "(()=>{for(const c of ['.navigation-control-expansion','.operation-control-expansion']){"
    "const e=document.querySelector(c);if(e&&e.classList.contains('fa-minus-square-o'))e.click()}"
    "return 'collapsed'})()"
)


def child_group_id(nifi: str, name: str) -> str:
    with urllib.request.urlopen(f"{nifi}/nifi-api/flow/process-groups/root", timeout=30) as r:
        groups = json.load(r)["processGroupFlow"]["flow"]["processGroups"]
    return next(g["id"] for g in groups if g["component"]["name"] == name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grafana", default="http://localhost:13000")
    ap.add_argument("--alertmanager", default="http://localhost:19093")
    ap.add_argument("--nifi", default="http://localhost:18480", help="nifi-ui-proxy")
    ap.add_argument("--cluster", default="local")
    ap.add_argument("--skip-nifi", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    shots = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        d = json.loads(path.read_text())
        rows = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in d["panels"])
        shots.append(
            {
                "url": f"{args.grafana}/d/{d['uid']}/{d['uid']}?orgId=1&kiosk&theme=light"
                f"&from=now-1h&to=now&var-cluster={args.cluster}",
                "height": rows * GRID_PX + TOP_PX,
                "wait": 15000,
                "out": str(OUT / f"{d['uid']}.png"),
            }
        )
    shots.append(
        {
            "url": f"{args.alertmanager}/#/alerts",
            "height": 900,
            "wait": 5000,
            "out": str(OUT / "alertmanager.png"),
        }
    )
    if not args.skip_nifi:
        ingest = child_group_id(args.nifi, "ingest")
        canvas = {"wait": 10000, "eval": [NIFI_FIT, NIFI_COLLAPSE], "after": 1500, "height": 820}
        shots += [
            {"url": f"{args.nifi}/nifi/", **canvas, "out": str(OUT / "nifi-canvas.png")},
            {
                "url": f"{args.nifi}/nifi/#/process-groups/{ingest}",
                **canvas,
                "out": str(OUT / "nifi-ingest.png"),
            },
            {
                "url": f"{args.nifi}/nifi/#/summary",
                "wait": 8000,
                "height": 820,
                "out": str(OUT / "nifi-summary.png"),
            },  # fmt: skip
            {
                "url": f"{args.nifi}/nifi/#/bulletins",
                "wait": 8000,
                "height": 640,
                "out": str(OUT / "nifi-bulletins.png"),
            },  # fmt: skip
            {
                "url": f"{args.nifi}/nifi/#/cluster",
                "wait": 8000,
                "height": 440,
                "out": str(OUT / "nifi-cluster.png"),
            },  # fmt: skip
        ]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"width": WIDTH, "height": 900, "scale": 1.5, "shots": shots}, f)
    try:
        subprocess.run(["node", str(CDP), f.name], check=True, timeout=900)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.exit(f"screenshot run failed: {e}")
    finally:
        Path(f.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()

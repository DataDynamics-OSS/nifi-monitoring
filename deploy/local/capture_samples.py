#!/usr/bin/env python3
"""읽기 전용 모니터 계정으로 NiFi API 응답을 design/samples/에 저장합니다.

모든 요청에 CN=nifi-monitor 인증서를 쓰므로, 여기서 403이 나면 모니터 계정의
정책 목록이 부족하다는 뜻입니다.

    python3 capture_samples.py [--url https://localhost:18443] [--out ../../design/samples]

TLS 없는 NiFi(http:// 주소)는 인증서 없이 요청합니다. 단일 노드 NiFi는 /controller/cluster가
404이므로 이 샘플만 건너뜁니다.

다른 클러스터에서는 ca.pem과 <cert>.pem/<cert>.key를 한 디렉터리에 두고 --cert-dir로
넘깁니다(클라이언트 인증서 이름이 nifi-monitor가 아니면 --cert도 넘깁니다).
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CERTS = HERE / "certs"

# (파일 이름, 경로)입니다. .json은 보기 좋게 정렬하고, .txt는 그대로 저장합니다.
SAMPLES = [
    ("about.json", "/flow/about"),
    ("cluster.json", "/controller/cluster"),
    ("cluster_summary.json", "/flow/cluster/summary"),
    ("flow_status_recursive.json", "/flow/process-groups/root/status?recursive=true"),
    ("system_diagnostics_nodewise.json", "/system-diagnostics?nodewise=true"),
    ("bulletin_board.json", "/flow/bulletin-board?limit=20"),
    ("controller_config.json", "/controller/config"),
    ("controller_status.json", "/flow/status"),
    ("metrics_prometheus.txt", "/flow/metrics/prometheus"),
    ("metrics_prometheus_nifi_registry.txt", "/flow/metrics/prometheus?includedRegistries=NIFI"),
]
TOPOLOGY = "flow_process_groups.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="https://localhost:18443", help="NiFi 주소")
    ap.add_argument(
        "--out", default=str(HERE.parent.parent / "design" / "samples"), help="저장할 디렉터리"
    )
    ap.add_argument(
        "--cert-dir", default=str(CERTS), help="ca.pem과 클라이언트 인증서가 있는 디렉터리"
    )
    ap.add_argument(
        "--cert", default="nifi-monitor", help="--cert-dir 안의 클라이언트 인증서 이름(확장자 제외)"
    )
    args = ap.parse_args()

    # TLS 없는(HTTP) NiFi는 인증도 없으므로 인증서를 쓰지 않습니다.
    ctx = None
    if args.url.lower().startswith("https://"):
        certs = Path(args.cert_dir)
        ctx = ssl.create_default_context(cafile=str(certs / "ca.pem"))
        ctx.load_cert_chain(str(certs / f"{args.cert}.pem"), str(certs / f"{args.cert}.key"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    standalone = False

    def fetch(path: str) -> bytes | None:
        nonlocal standalone
        req = urllib.request.Request(args.url.rstrip("/") + "/nifi-api" + path)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            # 단일 노드 NiFi는 /controller/cluster에 404를 줍니다. 실패가 아니라 건너뜁니다.
            if e.code == 404 and path == "/controller/cluster":
                standalone = True
                print(f"skip {path}: 단일 노드(클러스터 아님)")
                return None
            print(f"FAIL {path}: HTTP {e.code} {e.read().decode()[:200]}")
            return None

    failed = 0
    for name, path in SAMPLES:
        raw = fetch(path)
        if raw is None:
            failed += 0 if (standalone and path == "/controller/cluster") else 1
            continue
        if name.endswith(".json"):
            text = json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n"
        else:
            text = raw.decode()
        (out / name).write_text(text)
        print(f"ok   {path} → {name} ({len(raw)} 바이트)")

    # topology 샘플: 루트에서 닿는 모든 GET /flow/process-groups/{id} 응답을, topology collector가
    # 순회하는 방식대로 요청한 경로 조각(첫 호출은 "root")을 키로 저장합니다.
    topology: dict[str, dict] = {}
    queue = ["root"]
    while queue:
        key = queue.pop(0)
        raw = fetch(f"/flow/process-groups/{key}")
        if raw is None:
            failed += 1
            continue
        body = json.loads(raw)
        topology[key] = body
        queue += [g["id"] for g in body["processGroupFlow"]["flow"]["processGroups"]]
    (out / TOPOLOGY).write_text(json.dumps(topology, indent=2, ensure_ascii=False) + "\n")
    print(f"ok   /flow/process-groups/{{id}} × {len(topology)}개 → {TOPOLOGY}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""로컬 NiFi 클러스터를 준비합니다: 읽기 전용 모니터 계정과 작은 테스트 플로우를 만듭니다.

여러 번 실행해도 결과가 같습니다. certs/의 관리자 클라이언트 인증서를 쓰며,
표준 라이브러리만 사용합니다.

    python3 seed.py [--url https://localhost:18443]

모니터 계정: CN=nifi-monitor에 /flow, /controller, /system과 루트
Process Group 읽기 권한을 줍니다. CN=prometheus(내장 메트릭 엔드포인트)에는 /flow 읽기
권한을 줍니다.

Provenance 조회 계정: CN=nifi-provenance에 /provenance 읽기(조회 실행),
루트 Process Group의 Provenance 보기 권한(이벤트), 루트 Process Group 읽기 권한(이벤트의
컴포넌트 이름)을 줍니다. 데이터 보기 권한은 주지 않습니다.

테스트 플로우(모든 collector와 큐·Processor·Bulletin 알림을 검증합니다):

    /ingest            GenerateFlowFile (1/s) ─► "to-sink" (Backpressure 100) ─► sink (Stopped)
    /ingest/errors     GenerateFlowFile (5초마다) ─► LogMessage (ERROR) → Bulletin
    /broken            연결 없는 GenerateFlowFile → Invalid
    /stall             GenerateFlowFile (10초마다) ─► "to-hourly" ─► hourly (Running, 1시간 1회)
    /ports             입력 포트 "in" ─► Funnel ─► 출력 포트 "out"
    /                  입력 포트 "s2s-in", nifi-1로 향하는 Remote Process Group (전송하지 않음)
    /disk              GenerateFlowFile (2 MB/s, 정지 상태) ─► "to-hold" ─► hold (Stopped)
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
ADMIN_IDENTITY = "CN=admin"
NODE_IDENTITIES = ("CN=nifi-1", "CN=nifi-2")
MONITOR_IDENTITY = "CN=nifi-monitor"
MONITOR_RESOURCES = ["/flow", "/controller", "/system"]
# Prometheus는 자체 인증서로 내장 /flow/metrics/prometheus 엔드포인트를 스크레이프합니다.
PROMETHEUS_IDENTITY = "CN=prometheus"
# provenance-query 서비스가 쓰는 계정입니다. 모니터 계정과 분리합니다.
PROVENANCE_IDENTITY = "CN=nifi-provenance"

GENERATE = "org.apache.nifi.processors.standard.GenerateFlowFile"
UPDATE_ATTRIBUTE = "org.apache.nifi.processors.attributes.UpdateAttribute"
LOG_MESSAGE = "org.apache.nifi.processors.standard.LogMessage"


class NiFi:
    def __init__(self, url: str) -> None:
        self.base = url.rstrip("/") + "/nifi-api"
        ctx = ssl.create_default_context(cafile=str(CERTS / "ca.pem"))
        ctx.load_cert_chain(str(CERTS / "admin.pem"), str(CERTS / "admin.key"))
        self.ctx = ctx

    def call(self, method: str, path: str, body: dict | None = None, ok404: bool = False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if ok404 and e.code == 404:
                return None
            sys.exit(f"{method} {path}: HTTP {e.code}: {e.read().decode()[:300]}")

    def get(self, path: str, ok404: bool = False):
        return self.call("GET", path, ok404=ok404)

    def post(self, path: str, component: dict) -> dict:
        return self.call("POST", path, {"revision": {"version": 0}, "component": component})


# -- 모니터 계정 ---------------------------------------------------------


def user_id(nifi: NiFi, identity: str) -> str:
    users = nifi.get("/tenants/users")["users"]
    user = next((u for u in users if u["component"]["identity"] == identity), None)
    if user is None:
        user = nifi.post("/tenants/users", {"identity": identity})
        print(f"사용자 {identity} 생성")
    return user["id"]


def ensure_admin(nifi: NiFi, root_id: str) -> None:
    # 새 클러스터 플로우에서는 초기 관리자에게도 루트 PG 정책이 없으므로, 관리자가
    # 테스트 플로우를 만들 수 있도록 부여합니다.
    admin = user_id(nifi, ADMIN_IDENTITY)
    for action in ("read", "write"):
        grant(nifi, action, f"/process-groups/{root_id}", admin)
        # 데이터 보기/수정 권한은 큐를 비울 때 필요합니다(scenarios.py growth). 클러스터에서는
        # 요청을 중계하는 노드도 proxy chain에 포함되므로 같은 권한이 필요합니다.
        for identity in (ADMIN_IDENTITY, *NODE_IDENTITIES):
            grant(nifi, action, f"/data/process-groups/{root_id}", user_id(nifi, identity))
    grant(nifi, "write", f"/operation/process-groups/{root_id}", admin)


def ensure_monitor(nifi: NiFi, root_id: str) -> None:
    monitor = user_id(nifi, MONITOR_IDENTITY)
    for resource in MONITOR_RESOURCES + [f"/process-groups/{root_id}"]:
        grant(nifi, "read", resource, monitor)
    # /flow 읽기 권한만으로 모든 컴포넌트의 내장 메트릭이 이름까지 노출됩니다
    # (2.6.0에서 확인했습니다: 루트 PG 읽기 권한을 빼도 결과가 같습니다).
    grant(nifi, "read", "/flow", user_id(nifi, PROMETHEUS_IDENTITY))


def ensure_provenance(nifi: NiFi, root_id: str) -> None:
    provenance = user_id(nifi, PROVENANCE_IDENTITY)
    grant(nifi, "read", "/provenance", provenance)
    # 2.6.0 클러스터에서 확인했습니다: 데이터 보기와 달리 노드 identity에는 이 권한이 없어도
    # 다른 노드의 이벤트까지 조회됩니다. 컴포넌트 읽기 권한이 없으면 이름 대신 id가 나옵니다.
    grant(nifi, "read", f"/provenance-data/process-groups/{root_id}", provenance)
    grant(nifi, "read", f"/process-groups/{root_id}", provenance)


def grant(nifi: NiFi, action: str, resource: str, user_id: str) -> None:
    policy = nifi.get(f"/policies/{action}{resource}", ok404=True)
    # GET은 실제 적용되는(상속됐을 수 있는) 정책을 반환하므로, 리소스가 정확히 같을 때만 수정합니다.
    if policy is None or policy["component"]["resource"] != resource:
        nifi.post(
            "/policies",
            {"action": action, "resource": resource, "users": [{"id": user_id}]},
        )
        print(f"정책 {action} {resource} 생성")
        return
    comp = policy["component"]
    if any(u["id"] == user_id for u in comp.get("users", [])):
        return
    comp["users"] = comp.get("users", []) + [{"id": user_id}]
    nifi.call(
        "PUT", f"/policies/{policy['id']}", {"revision": policy["revision"], "component": comp}
    )
    print(f"정책 {action} {resource} 수정")


# -- 테스트 플로우 ---------------------------------------------------------------


def pg(nifi: NiFi, parent: str, name: str, x: float, y: float = 0) -> str:
    return nifi.post(
        f"/process-groups/{parent}/process-groups", {"name": name, "position": {"x": x, "y": y}}
    )["id"]


def processor(
    nifi: NiFi,
    group: str,
    ptype: str,
    name: str,
    x: float,
    *,
    y: float = 0,
    period: str = "0 sec",
    props: dict | None = None,
    auto_terminate: list[str] | None = None,
) -> dict:
    comp = {
        "type": ptype,
        "name": name,
        "position": {"x": x, "y": y},
        "config": {
            "schedulingPeriod": period,
            "properties": props or {},
            "autoTerminatedRelationships": auto_terminate or [],
        },
    }
    return nifi.post(f"/process-groups/{group}/processors", comp)


def connect(
    nifi: NiFi, group: str, src: dict, dst: dict, name: str, threshold: int, size: str = "1 GB"
) -> None:
    nifi.post(
        f"/process-groups/{group}/connections",
        {
            "name": name,
            "source": {"id": src["id"], "groupId": group, "type": "PROCESSOR"},
            "destination": {"id": dst["id"], "groupId": group, "type": "PROCESSOR"},
            "selectedRelationships": ["success"],
            "backPressureObjectThreshold": threshold,
            "backPressureDataSizeThreshold": size,
        },
    )


def start(nifi: NiFi, proc: dict) -> None:
    cur = nifi.get(f"/processors/{proc['id']}")
    nifi.call(
        "PUT",
        f"/processors/{proc['id']}/run-status",
        {"revision": cur["revision"], "state": "RUNNING"},
    )


def property_key(nifi: NiFi, proc: dict, *candidates: str) -> str:
    """NiFi 2.x는 많은 속성 키를 표시 이름으로 바꿨으므로, 존재하는 키를 골라 반환합니다."""
    keys = nifi.get(f"/processors/{proc['id']}")["component"]["config"]["descriptors"]
    for c in candidates:
        if c in keys:
            return c
    sys.exit(f"{proc['component']['name']} 속성에 {candidates} 중 어느 것도 없습니다: {list(keys)}")


def ensure_flow(nifi: NiFi, root_id: str) -> None:
    groups = nifi.get(f"/process-groups/{root_id}/process-groups")["processGroups"]
    if any(g["component"]["name"] == "ingest" for g in groups):
        print("테스트 플로우가 이미 있습니다")
        return

    ingest = pg(nifi, root_id, "ingest", 0)
    gen = processor(
        nifi, ingest, GENERATE, "generate", 0, period="1 sec", props={"File Size": "1 KB"}
    )
    sink = processor(nifi, ingest, UPDATE_ATTRIBUTE, "sink", 0, y=320, auto_terminate=["success"])
    connect(nifi, ingest, gen, sink, "to-sink", 100)
    start(nifi, gen)  # sink는 Stopped로 두어 "to-sink"가 차게 합니다

    errors = pg(nifi, ingest, "errors", 480)
    egen = processor(nifi, errors, GENERATE, "generate-errors", 0, period="5 sec")
    log = processor(nifi, errors, LOG_MESSAGE, "log-error", 0, y=320, auto_terminate=["success"])
    level = property_key(nifi, log, "Log Level", "log-level")
    text = property_key(nifi, log, "Log Message", "log-message")
    cur = nifi.get(f"/processors/{log['id']}")
    nifi.call(
        "PUT",
        f"/processors/{log['id']}",
        {
            "revision": cur["revision"],
            "component": {
                "id": log["id"],
                "config": {"properties": {level: "error", text: "seeded test error"}},
            },
        },
    )
    connect(nifi, errors, egen, log, "to-log", 10000)
    start(nifi, egen)
    start(nifi, log)

    broken = pg(nifi, root_id, "broken", 480)
    processor(nifi, broken, GENERATE, "unconnected", 0)  # success가 연결되지 않아 Invalid가 됩니다
    print("테스트 플로우 생성")


def ensure_stall(nifi: NiFi, root_id: str) -> None:
    """하류가 Running인데 아무것도 소비하지 않는 큐를 만듭니다 (NiFiQueueStalled 검증용)."""
    groups = nifi.get(f"/process-groups/{root_id}/process-groups")["processGroups"]
    if any(g["component"]["name"] == "stall" for g in groups):
        return
    stall = pg(nifi, root_id, "stall", 960)
    gen = processor(nifi, stall, GENERATE, "generate-slow", 0, period="10 sec")
    # Running이지만 1시간에 한 번만 실행되므로 큐가 계속 쌓입니다.
    hourly = processor(
        nifi,
        stall,
        UPDATE_ATTRIBUTE,
        "hourly",
        0,
        y=320,
        period="1 hour",
        auto_terminate=["success"],
    )
    connect(nifi, stall, gen, hourly, "to-hourly", 10000)
    start(nifi, gen)
    start(nifi, hourly)
    print("stall 플로우 생성")


def ensure_ports(nifi: NiFi, root_id: str) -> None:
    """포트와 Remote Process Group을 만들어 상태 스냅샷을 샘플로 받을 수 있게 합니다."""
    groups = nifi.get(f"/process-groups/{root_id}/process-groups")["processGroups"]
    if any(g["component"]["name"] == "ports" for g in groups):
        return
    ports = pg(nifi, root_id, "ports", 0, 260)
    pin = nifi.post(
        f"/process-groups/{ports}/input-ports", {"name": "in", "position": {"x": 0, "y": 0}}
    )
    funnel = nifi.post(f"/process-groups/{ports}/funnels", {"position": {"x": 300, "y": 0}})
    pout = nifi.post(
        f"/process-groups/{ports}/output-ports", {"name": "out", "position": {"x": 600, "y": 0}}
    )
    for src, src_type, dst, dst_type in [
        (pin, "INPUT_PORT", funnel, "FUNNEL"),
        (funnel, "FUNNEL", pout, "OUTPUT_PORT"),
    ]:
        nifi.post(
            f"/process-groups/{ports}/connections",
            {
                "source": {"id": src["id"], "groupId": ports, "type": src_type},
                "destination": {"id": dst["id"], "groupId": ports, "type": dst_type},
            },
        )
    nifi.post(
        f"/process-groups/{root_id}/input-ports",
        {"name": "s2s-in", "position": {"x": 960, "y": 300}},
    )
    # 전송하지 않습니다. 상태 스냅샷만 필요합니다.
    nifi.post(
        f"/process-groups/{root_id}/remote-process-groups",
        {"targetUris": "https://nifi-1:8443/nifi", "position": {"x": 1240, "y": 260}},
    )
    print("ports 플로우 생성")


def ensure_disk(nifi: NiFi, root_id: str) -> None:
    """큰 FlowFile을 큐에 쌓아 nifi-2의 300 MB content tmpfs를 채웁니다 (scenarios disk).

    정지 상태로 만들고, scenarios.py가 시작과 정지를 맡습니다.
    """
    groups = nifi.get(f"/process-groups/{root_id}/process-groups")["processGroups"]
    if any(g["component"]["name"] == "disk" for g in groups):
        return
    disk = pg(nifi, root_id, "disk", 480, 260)
    gen = processor(
        nifi, disk, GENERATE, "generate-big", 0, period="1 sec", props={"File Size": "2 MB"}
    )
    hold = processor(nifi, disk, UPDATE_ATTRIBUTE, "hold", 0, y=320, auto_terminate=["success"])
    connect(nifi, disk, gen, hold, "to-hold", 100000, "100 GB")
    print("disk 플로우 생성")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--url", default="https://localhost:18443", help="NiFi 주소 (관리자 인증서로 접속)"
    )
    args = ap.parse_args()
    nifi = NiFi(args.url)
    root_id = nifi.get("/flow/process-groups/root")["processGroupFlow"]["id"]
    ensure_admin(nifi, root_id)
    ensure_flow(nifi, root_id)
    ensure_stall(nifi, root_id)
    ensure_ports(nifi, root_id)
    ensure_disk(nifi, root_id)
    ensure_monitor(nifi, root_id)
    ensure_provenance(nifi, root_id)


if __name__ == "__main__":
    main()

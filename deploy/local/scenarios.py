#!/usr/bin/env python3
"""로컬 스택에서 알림 시나리오를 테스트합니다 (체크리스트 5단계 "시나리오 테스트").

각 시나리오는 NiFi나 스택의 상태를 바꾼 뒤, Alertmanager에서 기대한 알림이 active로,
억제되어야 할 알림이 suppressed(inhibited)로 보일 때까지 기다리고 원래 상태로 되돌립니다.
`docker compose up -d && python3 seed.py` 뒤에 실행합니다. 알림의 `for:` 시간을 실제로
기다리므로 전체 실행에 1시간 넘게 걸립니다(growth·disk가 각각 약 20~25분).

    python3 scenarios.py [baseline node exporter permission growth disk ...]

시나리오:
  baseline    테스트 플로우 기본 상태입니다: Backpressure 발동(critical)이 같은 큐의 80%
              경고를 억제하고, Invalid Processor·ERROR Bulletin·정체 큐 알림이 발화합니다
  node        nifi-2를 중지합니다 → NiFiNodeDisconnected, 큐·Processor·Bulletin 알림은 억제됩니다
  exporter    exporter를 중지합니다 → NiFiExporterDown이 발화하고, NiFi 알림은 해소되지 않고
              억제됩니다(keep_firing_for)
  permission  모니터 계정의 /controller 읽기 권한을 회수합니다 → NiFiCollectorFailing(cluster),
              NiFi 알림은 억제되고, 권한을 복구하면 해소됩니다
  growth      큐를 비우고 임계치를 올린 뒤 더 빨리 생성합니다 →
              NiFiQueueGrowing과 NiFiQueueNearBackpressure가 발화한 다음,
              NiFiQueueBackpressureEngaged가 발화해 둘을 억제합니다
  disk        nifi-2의 300 MB content 저장소(tmpfs)를 2 MB FlowFile로 채웁니다 →
              NiFiRepositoryDiskCritical이 발화해 NiFiRepositoryDiskHigh를 억제하고,
              큐를 비우면 둘 다 해소됩니다
"""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CERTS = HERE / "certs"
NIFI = "https://localhost:18443/nifi-api"
AM = "http://localhost:19093/api/v2/alerts"


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class NiFi:
    def __init__(self) -> None:
        self.ctx = ssl.create_default_context(cafile=str(CERTS / "ca.pem"))
        self.ctx.load_cert_chain(str(CERTS / "admin.pem"), str(CERTS / "admin.key"))

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            NIFI + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}

    def find(self, kind: str, name: str) -> dict:
        """플로우 전체에서 이 이름을 가진 첫 Processor/Connection을 반환합니다."""
        queue = ["root"]
        while queue:
            flow = self.call("GET", f"/flow/process-groups/{queue.pop()}")["processGroupFlow"]
            for item in flow["flow"][kind]:
                if item.get("component", {}).get("name") == name:
                    return item
            queue += [g["id"] for g in flow["flow"]["processGroups"]]
        raise LookupError(f"{kind} {name!r}을(를) 찾을 수 없습니다")

    def set_run_state(self, proc_id: str, state: str) -> None:
        cur = self.call("GET", f"/processors/{proc_id}")
        self.call(
            "PUT",
            f"/processors/{proc_id}/run-status",
            {"revision": cur["revision"], "state": state},
        )

    def update(self, kind: str, item_id: str, component: dict) -> None:
        cur = self.call("GET", f"/{kind}/{item_id}")
        self.call(
            "PUT",
            f"/{kind}/{item_id}",
            {"revision": cur["revision"], "component": {"id": item_id, **component}},
        )

    def empty_queue(self, conn_id: str) -> None:
        req = self.call("POST", f"/flowfile-queues/{conn_id}/drop-requests")["dropRequest"]
        for _ in range(30):
            if self.call("GET", f"/flowfile-queues/{conn_id}/drop-requests/{req['id']}")[
                "dropRequest"
            ]["finished"]:
                break
            time.sleep(1)
        self.call("DELETE", f"/flowfile-queues/{conn_id}/drop-requests/{req['id']}")

    def set_policy_user(self, action: str, resource: str, identity: str, present: bool) -> None:
        users = self.call("GET", "/tenants/users")["users"]
        uid = next(u["id"] for u in users if u["component"]["identity"] == identity)
        policy = self.call("GET", f"/policies/{action}{resource}")
        comp = policy["component"]
        ids = [u["id"] for u in comp.get("users", []) if u["id"] != uid]
        if present:
            ids.append(uid)
        comp["users"] = [{"id": i} for i in ids]
        self.call(
            "PUT", f"/policies/{policy['id']}", {"revision": policy["revision"], "component": comp}
        )


def alerts() -> dict[str, list[dict]]:
    """Alertmanager의 알림을 alertname → {state, inhibitedBy, labels} 목록으로 반환합니다."""
    with urllib.request.urlopen(AM, timeout=10) as resp:
        data = json.load(resp)
    out: dict[str, list[dict]] = {}
    for a in data:
        out.setdefault(a["labels"]["alertname"], []).append(
            {
                "state": a["status"]["state"],
                "inhibited": bool(a["status"]["inhibitedBy"]),
                "labels": a["labels"],
            }
        )
    return out


def state(name: str, current: dict) -> str:
    """active | suppressed | absent 중 하나를 반환합니다 (여러 개면 active가 우선입니다)."""
    items = current.get(name, [])
    if not items:
        return "absent"
    return "active" if any(i["state"] == "active" for i in items) else "suppressed"


def wait_for(expect: dict[str, str], timeout: float, label: str) -> bool:
    """모든 alertname이 기대한 상태(active/suppressed/absent)가 될 때까지 기다립니다."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        current = alerts()
        got = {name: state(name, current) for name in expect}
        if got != last:
            log(f"  {label}: {got}")
            last = got
        if got == expect:
            return True
        time.sleep(15)
    log(f"  TIMEOUT {label}: 기대값 {expect}")
    return False


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=HERE, check=True, capture_output=True)


QUEUE_ALERTS = ["NiFiQueueBackpressureEngaged", "NiFiQueueNearBackpressure"]


def baseline(_: NiFi) -> bool:
    return wait_for(
        {
            "NiFiQueueBackpressureEngaged": "active",
            "NiFiQueueNearBackpressure": "suppressed",  # Engaged에 의해 억제됩니다
            "NiFiProcessorInvalid": "active",
            "NiFiBulletinErrors": "active",
            "NiFiQueueStalled": "active",
        },
        25 * 60,
        "baseline",
    )


def node(_: NiFi) -> bool:
    compose("stop", "nifi-2")
    try:
        ok = wait_for(
            {
                "NiFiNodeDisconnected": "active",
                "NiFiQueueBackpressureEngaged": "suppressed",
                "NiFiProcessorInvalid": "suppressed",
                "NiFiBulletinErrors": "suppressed",
            },
            8 * 60,
            "node stopped",
        )
    finally:
        compose("start", "nifi-2")
    return ok and wait_for({"NiFiNodeDisconnected": "absent"}, 10 * 60, "node restored")


def exporter(_: NiFi) -> bool:
    compose("stop", "nifi-exporter")
    try:
        ok = wait_for(
            {
                "NiFiExporterDown": "active",
                "NiFiQueueBackpressureEngaged": "suppressed",
                "NiFiProcessorInvalid": "suppressed",
            },
            6 * 60,
            "exporter stopped",
        )
    finally:
        compose("start", "nifi-exporter")
    return ok and wait_for({"NiFiExporterDown": "absent"}, 5 * 60, "exporter restored")


def permission(nifi: NiFi) -> bool:
    nifi.set_policy_user("read", "/controller", "CN=nifi-monitor", present=False)
    try:
        ok = wait_for(
            {
                "NiFiCollectorFailing": "active",
                "NiFiQueueBackpressureEngaged": "suppressed",
                "NiFiProcessorInvalid": "suppressed",
            },
            8 * 60,
            "permission revoked",
        )
    finally:
        nifi.set_policy_user("read", "/controller", "CN=nifi-monitor", present=True)
    return ok and wait_for({"NiFiCollectorFailing": "absent"}, 5 * 60, "permission restored")


def growth(nifi: NiFi) -> bool:
    gen = nifi.find("processors", "generate")
    conn = nifi.find("connections", "to-sink")
    try:
        nifi.set_run_state(gen["id"], "STOPPED")
        nifi.empty_queue(conn["id"])
        nifi.update("connections", conn["id"], {"backPressureObjectThreshold": 4000})
        nifi.update("processors", gen["id"], {"config": {"properties": {"Batch Size": "5"}}})
        # 큐 알림은 조건이 사라진 뒤에도 5분간 발화 상태를 유지합니다 (keep_firing_for)
        if not wait_for({n: "absent" for n in QUEUE_ALERTS}, 12 * 60, "queue emptied"):
            return False
        nifi.set_run_state(gen["id"], "RUNNING")  # 노드당 초당 FlowFile 5개입니다
        ok = wait_for(
            {"NiFiQueueGrowing": "active", "NiFiQueueNearBackpressure": "active"},
            20 * 60,
            "growing",
        )
        return ok and wait_for(
            {
                "NiFiQueueBackpressureEngaged": "active",
                "NiFiQueueNearBackpressure": "suppressed",
                "NiFiQueueGrowing": "suppressed",
            },
            20 * 60,
            "engaged",
        )
    finally:
        nifi.set_run_state(gen["id"], "STOPPED")
        nifi.update("connections", conn["id"], {"backPressureObjectThreshold": 100})
        nifi.update("processors", gen["id"], {"config": {"properties": {"Batch Size": "1"}}})
        nifi.set_run_state(gen["id"], "RUNNING")


def disk(nifi: NiFi) -> bool:
    """nifi-2의 300 MB content tmpfs를 채웁니다: Critical(92%)이 발화해 High(80%)를 억제합니다."""
    gen = nifi.find("processors", "generate-big")
    conn = nifi.find("connections", "to-hold")
    try:
        nifi.set_run_state(gen["id"], "RUNNING")
        ok = wait_for(
            {"NiFiRepositoryDiskCritical": "active", "NiFiRepositoryDiskHigh": "suppressed"},
            20 * 60,
            "filling",
        )
    finally:
        nifi.set_run_state(gen["id"], "STOPPED")
        nifi.empty_queue(conn["id"])
    return ok and wait_for(
        {"NiFiRepositoryDiskCritical": "absent", "NiFiRepositoryDiskHigh": "absent"},
        15 * 60,
        "drained",
    )


SCENARIOS = {
    "baseline": baseline,
    "node": node,
    "exporter": exporter,
    "permission": permission,
    "growth": growth,
    "disk": disk,
}


def main() -> None:
    names = sys.argv[1:] or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        sys.exit(f"알 수 없는 시나리오: {' '.join(unknown)}\n{__doc__}")
    nifi = NiFi()
    results = {}
    for name in names:
        log(f"시나리오 {name} 시작")
        results[name] = SCENARIOS[name](nifi)
        log(f"scenario {name}: {'PASS' if results[name] else 'FAIL'}")
    log("summary " + " ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in results.items()))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""수집한 NiFi API 응답 샘플에서 업무·환경 정보를 지워 공개 저장소에 넣을 수 있게 합니다.

    python3 mask_samples.py <수집 디렉터리> <출력 디렉터리> --host <원래 호스트>=<대체값> ...

capture_samples.py로 운영(CFM) 클러스터에서 받은 응답은 컴포넌트 이름, 주석, 라벨,
Processor 설정(SQL, URL, 헤더 등)을 담고 있습니다. 이 스크립트는 다음을 처리합니다.

- 이름·주석·라벨 값(`name`, `sourceName`, `destinationName`, `comments`, `label` 등)을
  같은 원문이면 같은 대체값(`name-001`)이 되도록 바꿉니다. 조인과 구조는 유지됩니다.
- Processor·Controller Service 설정의 속성, 속성 설명, 주석 데이터를 지웁니다.
- Bulletin 메시지를 지우고, `--host`로 준 호스트명·IP를 바꿉니다.
- 내장 메트릭(`metrics_prometheus*.txt`)은 컴포넌트 이름이 레이블에 있어 복사하지 않습니다.

마지막에 지운 원문이 출력에 남아 있는지 검사하고, 남아 있으면 1로 종료합니다.
JSON의 구조(키)와 id, 수치, 상태값은 바꾸지 않으므로 회귀 테스트에 그대로 씁니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NAME_KEYS = {
    "name",
    "sourceName",
    "destinationName",
    "comments",
    "label",
    "groupName",
    "sourceGroupName",
    "destinationGroupName",
    "parameterContextName",
    "message",
    "description",
}
# 사용자 정의 관계 이름(RouteOnAttribute 등)은 업무 이름을 담으므로 목록 안의 값도 바꿉니다
RELATIONSHIP_LIST_KEYS = {
    "selectedRelationships",
    "availableRelationships",
    "retriedRelationships",
    "autoTerminatedRelationships",
}
# 설정 중 업무 정보가 들어 있는 부분입니다(SQL, URL, 헤더 값, 속성 설명)
DROP_KEYS = {"properties", "descriptors", "annotationData", "sensitiveDynamicPropertyNames"}
# 이름이지만 NiFi가 정한 값이라 바꾸지 않는 것입니다(상태 표시에 쓰입니다)
KEEP_VALUES = {
    "success",
    "failure",
    "original",
    "retry",
    "no retry",
    "response",
    "unmatched",
    "matched",
    "split",
    "merged",
    "invalid",
}


class Masker:
    def __init__(self, hosts: dict[str, str]) -> None:
        self.hosts = hosts
        self.names: dict[str, str] = {}
        self.removed: set[str] = set()

    def name(self, value: str) -> str:
        if value.lower() in KEEP_VALUES or not value:
            return value
        if value not in self.names:
            self.names[value] = f"name-{len(self.names) + 1:03d}"
        self.removed.add(value)
        return self.names[value]

    def collect(self, obj) -> None:
        """지우는 설정 하위의 문자열을 기록합니다(남았는지 검사용)."""
        if isinstance(obj, dict):
            for v in obj.values():
                self.collect(v)
        elif isinstance(obj, list):
            for v in obj:
                self.collect(v)
        elif isinstance(obj, str) and len(obj) >= 6:
            self.removed.add(obj)

    def walk(self, obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in DROP_KEYS:
                    self.collect(v)
                    out[k] = {} if isinstance(v, dict) else [] if isinstance(v, list) else None
                elif k in NAME_KEYS and isinstance(v, str):
                    out[k] = self.name(v)
                elif k in RELATIONSHIP_LIST_KEYS and isinstance(v, list):
                    out[k] = [self.name(x) if isinstance(x, str) else x for x in v]
                else:
                    out[k] = self.walk(v)
            return out
        if isinstance(obj, list):
            return [self.walk(v) for v in obj]
        if isinstance(obj, str):
            for old, new in self.hosts.items():
                obj = obj.replace(old, new)
        return obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument(
        "--host", action="append", default=[], help="원래값=대체값 (호스트명, IP, 여러 번)"
    )
    args = ap.parse_args()
    hosts = dict(h.split("=", 1) for h in args.host)
    masker = Masker(hosts)
    args.out.mkdir(parents=True, exist_ok=True)

    written = []
    for src in sorted(args.src.glob("*.json")):
        body = masker.walk(json.loads(src.read_text(encoding="utf-8")))
        # flow_process_groups.json의 키는 PG id이므로 바꾸지 않습니다
        dst = args.out / src.name
        dst.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(dst)
        print(f"masked {src.name}")
    skipped = sorted(p.name for p in args.src.glob("*.txt"))
    if skipped:
        print(f"복사하지 않음(컴포넌트 이름이 레이블에 있음): {', '.join(skipped)}")

    # 지운 원문과 원래 호스트가 출력에 남았는지 확인합니다. 짧거나 흔한 값(상태값 등)은
    # 다른 필드에도 정상적으로 나오므로, 6자 이상이고 공백·특수문자가 있는 값 위주로 봅니다
    text = "\n".join(p.read_text(encoding="utf-8") for p in written)
    leaks = [h for h in hosts if h in text]
    suspicious = re.compile(r"[\s/:#{$=@]")
    for value in masker.removed:
        if len(value) >= 6 and (suspicious.search(value) or value in masker.names):
            if json.dumps(value, ensure_ascii=False)[1:-1] in text:
                leaks.append(value)
    print(f"이름 {len(masker.names)}개 대체, 원문 {len(masker.removed)}개 제거")
    if leaks:
        print("남은 원문:")
        for v in sorted(leaks)[:30]:
            print(f"  {v[:80]!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

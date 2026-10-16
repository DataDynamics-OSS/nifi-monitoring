#!/usr/bin/env python3
# ruff: noqa: E501  (그림에 들어가는 문구 줄은 내용이라, 줄을 나누면 오히려 읽기 어렵습니다)
"""README의 기술 그림을 docs/images/*.png로 렌더링합니다.

    python3 docs/diagrams/build.py            # chromium(headless)과 Noto Sans CJK KR이 필요합니다

각 그림은 아래의 작은 기본 도형으로 SVG를 그리고 HTML로 감싼 뒤, headless Chromium으로
2배율 스크린샷을 찍어 만듭니다. PNG를 직접 고치지 말고 여기를 고쳐 다시 실행합니다.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "images"
FONT = "'Noto Sans CJK KR', 'NanumSquare Neo', sans-serif"

# 그림에 쓰는 색상 팔레트입니다(글자, 보조 글자, 선, 그리고 (테두리, 채움) 색 쌍).
INK = "#1e293b"
MUTED = "#64748b"
LINE = "#94a3b8"
NAVY = ("#1e3a5f", "#e8eef6")
TEAL = ("#0f766e", "#e6f4f2")
ORANGE = ("#c2410c", "#fdf0e8")
PURPLE = ("#6d28d9", "#f1ecfd")
GRAY = ("#475569", "#f1f5f9")
GREEN = ("#15803d", "#eaf6ee")
RED = ("#b91c1c", "#fdecec")


class Canvas:
    def __init__(self, width: int, height: int, title: str, subtitle: str = "") -> None:
        self.w, self.h = width, height
        self.parts: list[str] = []
        self.text(40, 52, title, size=30, weight=700)
        if subtitle:
            self.text(40, 84, subtitle, size=16, color=MUTED)

    def text(
        self,
        x: float,
        y: float,
        s: str,
        *,
        size: int = 15,
        weight: int = 400,
        color: str = INK,
        anchor: str = "start",
    ) -> None:
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}">{html.escape(s)}</text>'
        )

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str = "",
        lines: list[str] | tuple[str, ...] = (),
        *,
        color: tuple[str, str] = NAVY,
        title_size: int = 18,
        size: int = 14,
        dashed: bool = False,
        center: bool = False,
        header: bool = True,
        cols: tuple[int, ...] = (0, 130, 190),
    ) -> None:
        stroke, fill = color
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.6"{dash}/>'
        )
        cx = x + w / 2
        ty = y + 30
        if title:
            if header:
                self.parts.append(
                    f'<rect x="{x}" y="{y}" width="{w}" height="42" rx="12" fill="{stroke}"/>'
                    f'<rect x="{x}" y="{y + 30}" width="{w}" height="12" fill="{stroke}"/>'
                )
                self.text(
                    cx if center else x + 16,
                    y + 28,
                    title,
                    size=title_size,
                    weight=700,
                    color="#ffffff",
                    anchor="middle" if center else "start",
                )
                ty = y + 66
            else:
                self.text(
                    cx if center else x + 16,
                    y + 30,
                    title,
                    size=title_size,
                    weight=700,
                    color=stroke,
                    anchor="middle" if center else "start",
                )
                ty = y + 56
        for i, line in enumerate(lines):
            bold = line.startswith("**")
            line = line.strip("*")
            # "a\tb\tc" → x + 16 + cols[k] 위치의 열로 나눕니다 (SVG는 공백을 합치기 때문입니다)
            for k, part in enumerate(line.split("\t")):
                self.text(
                    cx if center else x + 16 + cols[k],
                    ty + i * (size + 9),
                    part,
                    size=size,
                    weight=700 if bold or (k == 0 and "\t" in line) else 400,
                    color=INK if bold else "#334155",
                    anchor="middle" if center else "start",
                )

    def pill(self, x: float, y: float, w: float, s: str, color: tuple[str, str] = GRAY) -> None:
        stroke, fill = color
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="30" rx="15" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.2"/>'
        )
        self.text(x + w / 2, y + 20, s, size=13, weight=600, color=stroke, anchor="middle")

    def arrow(
        self,
        points: list[tuple[float, float]],
        label: str = "",
        *,
        color: str = LINE,
        dashed: bool = False,
        label_at: tuple[float, float] | None = None,
        label_anchor: str = "middle",
        width: float = 2.2,
    ) -> None:
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        marker = f"arrow-{color.strip('#')}"
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash} '
            f'marker-end="url(#{marker})"/>'
        )
        self._markers.add(color)
        if label:
            if label_at is None:
                (x1, y1), (x2, y2) = points[0], points[-1]
                label_at = ((x1 + x2) / 2, (y1 + y2) / 2 - 10)
            for i, part in enumerate(label.split("\n")):
                self.text(
                    label_at[0],
                    label_at[1] + i * 19,
                    part,
                    size=13,
                    color=MUTED,
                    anchor=label_anchor,
                )

    _markers: set[str] = set()

    def html(self) -> str:
        markers = "".join(
            f'<marker id="arrow-{c.strip("#")}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>'
            for c in sorted(self._markers)
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">'
            f'<defs>{markers}</defs><rect width="100%" height="100%" fill="#ffffff"/>'
            + "".join(self.parts)
            + "</svg>"
        )
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<style>html,body{margin:0;padding:0;background:#fff}</style></head>"
            f"<body>{svg}</body></html>"
        )


# -- 그림 ------------------------------------------------------------------------


def architecture() -> Canvas:
    c = Canvas(
        1600,
        920,
        "시스템 구성",
        "NiFi 2.6.0 클러스터의 상태를 읽기 전용으로 수집해 Prometheus · Alertmanager · Grafana로 전달",
    )
    # NiFi 클러스터와 노드 3개를 그립니다.
    c.box(40, 120, 400, 640, "NiFi 2.6.0 클러스터 (CFM 4.12)", color=GRAY, header=False)
    for i, node in enumerate(["nifi-1", "nifi-2", "nifi-3"]):
        y = 180 + i * 170
        c.box(
            70,
            y,
            340,
            140,
            node,
            [
                "REST API  /nifi-api",
                "내장 메트릭  /flow/metrics/prometheus",
                "Content · FlowFile · Provenance 저장소",
            ],
            color=NAVY,
            title_size=16,
            size=13,
        )
    c.text(
        240, 735, "ZooKeeper · HTTPS 기본 · 노드별 Bulletin", size=13, color=MUTED, anchor="middle"
    )

    # exporter 상자를 그립니다.
    c.box(
        560,
        170,
        420,
        360,
        "nifi-exporter (Python 3.11)",
        [
            "**Collector (백그라운드 스레드, 주기)**",
            "cluster\t15s\t노드 연결 · heartbeat",
            "flow\t30s\tPG · Processor · 큐 · 포트",
            "diagnostics\t30s\tJVM heap · GC · 저장소",
            "controller\t30s\tNiFi 스레드 풀",
            "bulletin\t30s\t노드별 커서로 건수 집계",
            "topology\t300s\t큐 연결 관계 · 임계치",
            "",
            "**스냅샷 저장소 → /metrics (basic auth)**",
            "실패한 Collector의 값은 노출하지 않음",
        ],
        color=TEAL,
        size=14,
    )
    c.arrow(
        [(440, 330), (560, 330)],
        "HTTP(S) 읽기\nmTLS · JWT\n또는 인증 없음",
        color=TEAL[0],
        label_at=(500, 270),
    )

    # Prometheus 상자를 그립니다.
    c.box(
        1080,
        170,
        240,
        190,
        "Prometheus",
        ["recording rule 31개", "alert rule 24개", "보존 15일 → 30일", "promtool 단위 테스트"],
        color=ORANGE,
        size=14,
    )
    c.arrow([(980, 300), (1080, 300)], "15s 스크레이프", color=ORANGE[0], label_at=(1030, 288))
    c.arrow(
        [(440, 640), (1030, 640), (1030, 330), (1080, 330)],
        "보조 경로: 노드별 내장 메트릭 (mTLS 또는 HTTP, allowlist)",
        color=LINE,
        dashed=True,
        label_at=(735, 628),
    )

    # Alertmanager와 수신처를 그립니다.
    c.box(
        1080,
        440,
        240,
        130,
        "Alertmanager",
        ["라우팅 · 억제(inhibit) 7종", "그룹 · 반복 주기"],
        color=RED,
        size=14,
    )
    c.arrow(
        [(1200, 360), (1200, 440)], "알림", color=RED[0], label_at=(1212, 405), label_anchor="start"
    )
    for i, (name, desc) in enumerate(
        [
            ("Slack", "warning · critical"),
            ("호출기", "critical"),
            ("플랫폼팀", "수집 장애"),
            ("HTTP 중계", "사내 API (relay)"),
        ]
    ):
        y = 440 + i * 80
        c.box(1390, y, 170, 62, name, [desc], color=GRAY, header=False, title_size=15, size=12)
        c.arrow([(1320, 505), (1390, y + 31)], color=LINE)

    # Grafana 상자를 그립니다.
    c.box(
        1390,
        170,
        170,
        250,
        "Grafana",
        ["개요", "프로세스 그룹", "프로세서", "큐", "장애 분석", "JVM·스레드"],
        color=PURPLE,
        size=14,
    )
    c.arrow([(1320, 300), (1390, 300)], "PromQL", color=PURPLE[0], label_at=(1355, 288))

    # 하단의 운영 지원 띠를 그립니다.
    c.box(
        40,
        800,
        1520,
        90,
        "운영 지원",
        [
            "docs/runbook.md 알림별 대응 절차   ·   deploy/local 로컬 검증 스택(NiFi 2노드 + 전체 모니터링)   ·   "
            "GitHub Actions CI"
        ],
        color=GRAY,
        header=False,
        size=15,
    )
    return c


def exporter() -> Canvas:
    c = Canvas(
        1600,
        910,
        "수집 구조 (nifi-exporter)",
        "REST API 7종으로 클러스터 전체 상태를 읽고, 컴포넌트 계층과 수치를 분리된 메트릭으로 노출",
    )
    rows = [
        (
            "cluster",
            "GET /controller/cluster",
            "nifi_cluster_*, nifi_node_*",
            "노드 상태 state-set, heartbeat, 단일 노드 자동 인식",
        ),
        (
            "flow",
            "GET /flow/process-groups/root/status?recursive=true",
            "nifi_pg_*, nifi_processor_*, nifi_connection_*, nifi_port_*, nifi_rpg_*",
            "단일 호출로 전체 트리, 5분 통계는 _5m gauge",
        ),
        (
            "diagnostics",
            "GET /system-diagnostics?nodewise=true",
            "nifi_jvm_*, nifi_repo_*, nifi_system_*",
            "노드별 heap(사용·확보·최대) · GC · 가동 시간",
        ),
        (
            "controller",
            "GET /controller/config, GET /flow/status",
            "nifi_controller_*_threads",
            "스레드 풀 크기와 활성 스레드",
        ),
        (
            "bulletin",
            "GET /flow/bulletin-board",
            "nifi_bulletins_total",
            "노드별 id 커서, 재시작 시 리셋 감지",
        ),
        (
            "topology",
            "GET /flow/process-groups/{id} (PG별)",
            "nifi_connection_endpoints_info, *_backpressure_*",
            "2.6.0 status에 없는 큐 연결 id 보충",
        ),
    ]
    c.text(60, 140, "Collector", size=15, weight=700, color=MUTED)
    c.text(250, 140, "NiFi REST API", size=15, weight=700, color=MUTED)
    c.text(760, 140, "노출 메트릭", size=15, weight=700, color=MUTED)
    c.text(1250, 140, "특징", size=15, weight=700, color=MUTED)
    for i, (name, ep, metrics, note) in enumerate(rows):
        y = 160 + i * 76
        c.pill(50, y + 12, 160, name, TEAL)
        c.box(240, y, 490, 56, color=NAVY, header=False)
        c.text(256, y + 34, ep, size=14)
        c.arrow([(730, y + 28), (750, y + 28)], color=LINE)
        c.box(750, y, 480, 56, color=TEAL, header=False)
        c.text(766, y + 34, metrics, size=13)
        c.text(1250, y + 34, note, size=14, color="#334155")

    y0 = 650
    c.box(
        50,
        y0,
        360,
        225,
        "NiFi 클라이언트",
        [
            "HTTPS(mTLS · JWT) 또는 HTTP(인증 없음)",
            "TLS CA 번들 · mTLS 클라이언트 인증서",
            "JWT exp 기반 만료 5분 전 재발급",
            "401 수신 시 1회 재로그인",
            "타임아웃 · 5xx 재시도(backoff)",
            "세마포어 동시성 제한",
            "응답 크기 nifi_exporter_api_response_bytes",
        ],
        color=NAVY,
        size=14,
    )
    c.box(
        470,
        y0,
        360,
        225,
        "Collector 실행",
        [
            "Collector마다 독립 스레드·주기",
            "실패하면 30초 뒤 다시 시도",
            "매 주기 메트릭 재구성",
            "→ 삭제된 컴포넌트 자동 제거",
            "실패 시 값 제거 + success=0",
            "→ '0'과 '미수집'을 구분",
            "주기 nifi_exporter_collector_interval_seconds",
        ],
        color=TEAL,
        size=14,
    )
    c.box(
        890,
        y0,
        660,
        225,
        "메트릭 설계 원칙",
        [
            "NiFi 5분 롤링 통계 → *_5m gauge  (rate() 적용 금지)",
            "누적 카운터만 *_total  (Bulletin 건수, API 호출 수)",
            "이름 · 경로 · 연결 관계는 *_info 메트릭에만 (값 1)",
            "→ PromQL group_left 조인으로 표시, 이름 변경에도 시계열 유지",
            "Backpressure 비율은 NiFi 계산값 percentUse* 그대로 (0 나눗셈 없음)",
            "클러스터 집계값만 노출, 노드별 분해는 내장 엔드포인트",
        ],
        color=ORANGE,
        size=14,
    )
    c.arrow([(410, y0 + 112), (470, y0 + 112)], color=LINE)
    c.arrow([(830, y0 + 112), (890, y0 + 112)], color=LINE)
    return c


def alerting() -> Canvas:
    c = Canvas(
        1600,
        980,
        "알림 체계",
        "원인 알림이 결과 알림을 억제해 한 장애에 한 번만 호출 · 수집 장애 시 잘못된 '해소' 통지 방지",
    )
    groups = [
        (
            "수집",
            RED,
            [
                "NiFiExporterDown",
                "NiFiExporterDuplicate",
                "NiFiCollectorFailing",
                "NiFiCollectorStale",
                "NiFiExporterFlowResponseLarge",
            ],
        ),
        (
            "클러스터",
            NAVY,
            ["NiFiNodeDisconnected", "NiFiNodeHeartbeatStale", "NiFiClusterQuorumLost"],
        ),
        (
            "자원",
            PURPLE,
            [
                "NiFiHeapHigh / Critical",
                "NiFiGCTimeHigh",
                "NiFiThreadPoolSaturated",
                "NiFiRepositoryDiskHigh / Critical",
            ],
        ),
        (
            "큐",
            ORANGE,
            [
                "NiFiQueueNearBackpressure",
                "NiFiQueueBackpressureEngaged",
                "NiFiQueueGrowing",
                "NiFiQueueStalled",
            ],
        ),
        (
            "Processor · Bulletin",
            TEAL,
            [
                "NiFiProcessorInvalid",
                "NiFiProcessorTerminatedThreads",
                "NiFiProcessorSlowTasks",
                "NiFiBulletinErrors",
            ],
        ),
    ]
    for i, (name, color, alerts) in enumerate(groups):
        x = 40 + i * 308
        c.box(x, 120, 290, 190, name, alerts, color=color, size=13)

    # 억제 관계를 그립니다.
    c.text(40, 395, "억제(inhibit) 관계", size=20, weight=700)
    tiers = [
        ("ExporterDown · CollectorFailing", RED, "같은 클러스터의 NiFi 알림 전부"),
        ("ClusterQuorumLost", NAVY, "NodeDisconnected · HeartbeatStale"),
        ("NodeDisconnected", NAVY, "큐 · Processor · Bulletin 알림"),
        ("QueueBackpressureEngaged", ORANGE, "같은 큐의 NearBackpressure · Growing · Stalled"),
        ("HeapCritical · RepositoryDiskCritical", PURPLE, "같은 노드의 High · GC 경고"),
    ]
    for i, (src, color, dst) in enumerate(tiers):
        y = 420 + i * 66
        c.box(40, y, 380, 50, color=color, header=False)
        c.text(56, y + 32, src, size=15, weight=700, color=color[0])
        c.arrow([(420, y + 25), (520, y + 25)], "억제", color=color[0], label_at=(470, y + 16))
        c.box(520, y, 470, 50, color=GRAY, header=False)
        c.text(536, y + 32, dst, size=14)

    # 라우팅 상자를 그립니다.
    c.box(
        1060,
        395,
        500,
        305,
        "라우팅 (Alertmanager)",
        [
            "component=exporter\t→ 플랫폼팀 (1시간 반복)",
            "severity=critical\t→ 호출기 + Slack",
            "severity=warning\t→ Slack",
            "",
            "group_by: alertname · cluster · pg_id",
            "알림 본문에 이름 표시: *_info 조인",
            "(예: Gen → Put (success) 큐 Backpressure 발동)",
        ],
        color=GRAY,
        size=14,
        cols=(0, 185),
    )

    # keep_firing_for 타임라인을 그립니다.
    y = 790
    c.text(40, y, "keep_firing_for 5m — 수집이 끊겨도 '해소'로 오인하지 않음", size=20, weight=700)
    c.box(40, y + 20, 1520, 140, color=GRAY, header=False)
    base, scale = 150, 180
    marks = [
        (0, "exporter 중지\n시계열 즉시 stale"),
        (2, "ExporterDown 발화\n→ NiFi 알림 억제"),
        (5, "keep_firing_for 종료\n(억제 중이라 통지 없음)"),
    ]
    c.arrow([(base, y + 70), (base + 6 * scale, y + 70)], color=LINE)
    for m, label in marks:
        x = base + m * scale
        c.parts.append(f'<circle cx="{x}" cy="{y + 70}" r="7" fill="{RED[0]}"/>')
        c.text(x, y + 52, f"{m}분", size=13, weight=700, color=RED[0], anchor="middle")
        for j, part in enumerate(label.split("\n")):
            c.text(x, y + 100 + j * 19, part, size=13, color="#334155", anchor="middle")
    c.text(
        base + 6 * scale + 40,
        y + 64,
        "keep_firing_for가 없으면",
        size=14,
        weight=700,
        color=RED[0],
    )
    c.text(base + 6 * scale + 40, y + 88, "0분에 'RESOLVED'가 통지됨", size=13, color="#334155")
    c.text(base + 6 * scale + 40, y + 110, "(로컬 시나리오에서 발견해 수정)", size=13, color=MUTED)
    return c


def dashboards() -> Canvas:
    c = Canvas(
        1600,
        750,
        "대시보드와 병목 추적 흐름",
        "Grafana 대시보드 6종 · 상단에 수집기 상태 · 표의 링크로 클러스터 → 그룹 → 컴포넌트까지 이동",
    )
    c.box(
        40,
        130,
        330,
        250,
        "개요",
        [
            "수집기 상태 · 연결된 노드",
            "Invalid 프로세서 · 80% 초과 큐",
            "Backpressure 발동 · ERROR Bulletin",
            "노드 표: 상태 · heartbeat · heap · 스레드 풀",
            "heap · 저장소 게이지",
            "발화 중인 알림",
        ],
        color=NAVY,
        size=14,
    )
    c.box(
        440,
        130,
        330,
        250,
        "프로세스 그룹",
        [
            "선택 그룹 + 하위 그룹 표",
            "경로 · 적체 · Δ10분 · 스레드",
            "유입/유출 5분 · 상태별 프로세서 수",
            "경로 클릭 → 하위로 드릴다운",
            "적체 · 처리량 추이",
        ],
        color=TEAL,
        size=14,
    )
    c.box(
        840,
        130,
        330,
        110,
        "큐",
        ["사용률 순 정렬 · Δ5분/Δ10분", "임계치 · 받는 쪽 실행 중"],
        color=ORANGE,
        size=14,
    )
    c.box(
        840,
        270,
        330,
        110,
        "프로세서",
        ["상태 · 스레드 · 평균 Task 시간", "ERROR Bulletin 5분"],
        color=PURPLE,
        size=14,
    )
    c.box(
        1240,
        130,
        320,
        110,
        "장애 분석",
        ["알림 발화 시점 · 프로세서별 ERROR", "빨리 쌓이는 큐 · 느린 프로세서"],
        color=RED,
        size=14,
    )
    c.box(
        1240,
        270,
        320,
        110,
        "JVM·스레드",
        ["스레드 풀 사용률 · 활성 스레드", "Heap 사용·확보·최대 · GC"],
        color=GREEN,
        size=14,
    )
    c.arrow([(370, 255), (440, 255)], color=LINE)
    c.arrow([(770, 185), (840, 185)], color=LINE)
    c.arrow([(770, 325), (840, 325)], color=LINE)
    c.arrow([(1005, 240), (1005, 270)], color=LINE)
    c.arrow([(1170, 185), (1240, 185)], color=LINE)
    # 느린 프로세서가 많으면 스레드 풀 포화를 의심하므로 프로세서 → JVM·스레드로 잇습니다.
    c.arrow([(1170, 325), (1240, 325)], color=LINE)

    c.text(40, 445, "병목 추적 절차 (설계 9장)", size=20, weight=700)
    steps = [
        ("1", "큐 증가 추세", "QueueGrowing · Δ10분 정렬"),
        ("2", "source / destination 식별", "연결 id (topology)"),
        ("3", "destination 상태 비교", "스레드 · task 시간 · Bulletin"),
        ("4", "Backpressure 확산 확인", "상위 PG 적체 · 발동 알림"),
        ("5", "Provenance 확인", "NiFi UI (2차: 조회 서비스)"),
    ]
    for i, (n, title, desc) in enumerate(steps):
        x = 40 + i * 308
        c.box(x, 475, 280, 120, color=GRAY, header=False)
        c.parts.append(f'<circle cx="{x + 34}" cy="{510}" r="18" fill="{NAVY[0]}"/>')
        c.text(x + 34, 516, n, size=16, weight=700, color="#fff", anchor="middle")
        c.text(x + 62, 516, title, size=16, weight=700)
        c.text(x + 20, 565, desc, size=14, color="#334155")
        if i < len(steps) - 1:
            c.arrow([(x + 280, 535), (x + 308, 535)], color=LINE)
    c.box(
        40,
        635,
        1520,
        80,
        "대시보드는 코드로 관리",
        [
            "build_dashboards.py가 JSON 생성 · UI 수정은 저장 안 됨(allowUiUpdates: false) · check_dashboards.py가 실제 Grafana에서 모든 패널 쿼리 실행 · CI가 생성 결과 최신 여부 확인"
        ],
        color=GRAY,
        header=False,
        size=14,
    )
    return c


def verification() -> Canvas:
    c = Canvas(
        1600,
        780,
        "검증 체계",
        "코드 단위 테스트부터 실제 NiFi 2.6.0 클러스터의 장애 시나리오까지 단계별로 확인",
    )
    layers = [
        (
            "단위 테스트",
            NAVY,
            "exporter 79건 (pytest)",
            "설정 · 인증 · 클라이언트 · Collector · 실패 처리 · 실제 mTLS 핸드셰이크 · Bulletin 노드별 동작",
        ),
        (
            "실제 응답 회귀",
            TEAL,
            "design/samples (NiFi 2.6.0)",
            "클러스터·단일 노드 실제 응답으로 모든 컴포넌트가 메트릭이 되는지, topology 조인이 맞는지 확인",
        ),
        (
            "규칙 테스트",
            ORANGE,
            "promtool alert 10 · recording 6",
            "발화 시점 · 레이블 · 문구 · keep_firing_for · 수집 지연 · 중복 exporter",
        ),
        (
            "로컬 2.6.0 스택",
            PURPLE,
            "NiFi 2노드 + 무인증 단일 노드",
            "compare.py: NiFi API vs Prometheus 33항목 일치  ·  check_dashboards.py: 패널 61개",
        ),
        (
            "장애 시나리오",
            RED,
            "scenarios.py 6종 통과",
            "큐 적체 · 노드 중지 · exporter 중지 · 권한 회수 · Invalid/Bulletin/정체 · 디스크 가득 참",
        ),
        (
            "CI",
            GREEN,
            "GitHub Actions 4 jobs",
            "ruff · pytest · docker build · promtool · amtool · 대시보드 생성 결과 확인",
        ),
    ]
    for i, (name, color, what, detail) in enumerate(layers):
        y = 120 + i * 106
        indent = i * 24
        c.box(40 + indent, y, 1520 - 2 * indent, 88, color=color, header=False)
        c.text(64 + indent, y + 38, name, size=19, weight=700, color=color[0])
        c.text(64 + indent, y + 66, what, size=14, weight=600, color="#334155")
        c.text(480, y + 52, detail, size=15)
    return c


DIAGRAMS = {
    "architecture": architecture,
    "exporter": exporter,
    "alerting": alerting,
    "dashboards": dashboards,
    "verification": verification,
}


def chromium() -> str:
    for name in ("chromium", "chromium-browser", "google-chrome"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("chromium not found")


def main() -> None:
    names = sys.argv[1:] or list(DIAGRAMS)
    browser = chromium()
    OUT.mkdir(parents=True, exist_ok=True)
    # snap으로 설치한 Chromium은 $HOME 아래만 읽을 수 있어서, 거기서 렌더링한 뒤 복사해 옵니다
    with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
        for name in names:
            canvas = DIAGRAMS[name]()
            page = Path(tmp) / f"{name}.html"
            png = Path(tmp) / f"{name}.png"
            page.write_text(canvas.html(), encoding="utf-8")
            subprocess.run(
                [
                    browser,
                    "--headless",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--force-device-scale-factor=2",
                    f"--window-size={canvas.w},{canvas.h}",
                    f"--screenshot={png}",
                    page.as_uri(),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            shutil.copy(png, OUT / f"{name}.png")
            print(f"wrote docs/images/{name}.png ({canvas.w}x{canvas.h} @2x)")


if __name__ == "__main__":
    main()

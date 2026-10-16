#!/usr/bin/env python3
"""NiFi Grafana 대시보드를 provisioning JSON으로 생성합니다.

    python3 build_dashboards.py          # dashboards/*.json을 씁니다
    python3 build_dashboards.py --check  # dashboards/가 최신이 아니면 1로 종료합니다

Provenance 링크는 nifi-provenance-query 서비스 주소를 씁니다. 기본값은 로컬 스택의
http://localhost:19104이고, 운영 주소로 만들려면 NIFI_PROVENANCE_URL을 지정합니다.

대시보드는 코드입니다. Grafana UI에서 JSON을 고치지 말고 이 파일을 고쳐 다시
생성합니다. 패널은 exporter 메트릭과 deploy/prometheus/rules/nifi-recording.yml의
recording rule을 읽습니다. 표는 instant 쿼리를 컴포넌트 id(connection_id,
processor_id, pg_id)로 조인한 것입니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}
C = 'cluster="$cluster"'
PG = f'{C}, pg_id=~"$pg_id"'

UIDS = {
    "overview": "nifi-overview",
    "pg": "nifi-process-groups",
    "processor": "nifi-processors",
    "queue": "nifi-queues",
    "incident": "nifi-incident",
    "jvm": "nifi-jvm",
}


# 브라우저가 직접 여는 주소이므로 Grafana 서버가 아니라 사용자 기준으로 닿는 주소입니다
PROVENANCE_URL = os.environ.get("NIFI_PROVENANCE_URL", "http://localhost:19104").rstrip("/")


def link(uid: str, **params: str) -> str:
    query = "&".join(f"var-{k}={v}" for k, v in params.items())
    return f"/d/{uid}/{uid}?{query}&${{__url_time_range}}"


def provenance_link(title: str, processor_id: str, at: str) -> dict:
    """nifi-provenance-query로 [at - 5분, at]의 Provenance를 새 탭에서 조회합니다."""
    return {
        "title": title,
        "url": "${provenance_url:raw}/provenance?cluster=${cluster}"
        f"&processor_id={processor_id}&at={at}",
        "targetBlank": True,
    }


# 대시보드 변수로 두어 링크마다 주소를 반복하지 않습니다(화면에는 보이지 않습니다)
PROVENANCE_VAR = {
    "name": "provenance_url",
    "label": "Provenance 조회 서비스",
    "type": "constant",
    "hide": 2,
    "query": PROVENANCE_URL,
}


# -- 기본 구성 요소 -------------------------------------------------------------


class Layout:
    """패널을 왼쪽에서 오른쪽으로 놓고, 24열을 넘으면 다음 줄로 넘깁니다."""

    def __init__(self) -> None:
        self.x = self.y = self.row_h = 0
        self.next_id = 1
        self.panels: list[dict] = []

    def add(self, panel: dict, w: int, h: int) -> None:
        if self.x + w > 24:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        panel["id"] = self.next_id
        panel["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.next_id += 1
        self.x += w
        self.row_h = max(self.row_h, h)
        self.panels.append(panel)

    def row(self, title: str) -> None:
        if self.x:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        self.add({"type": "row", "title": title, "collapsed": False, "panels": []}, 24, 1)
        self.x, self.y, self.row_h = 0, self.y + 1, 0


def target(expr: str, ref: str = "A", legend: str = "", instant: bool = False) -> dict:
    t = {"datasource": DS, "refId": ref, "expr": expr, "legendFormat": legend or "__auto"}
    if instant:
        t.update(instant=True, range=False, format="table")
    else:
        t.update(range=True)
    return t


def thresholds(*steps: tuple[float | None, str]) -> dict:
    return {
        "mode": "absolute",
        "steps": [{"value": v, "color": c} for v, c in steps],
    }


GREEN_RED = thresholds((None, "green"), (1, "red"))


def stat(
    title: str,
    expr: str,
    *,
    unit: str = "none",
    steps: dict | None = None,
    mappings: list | None = None,
    legend: str = "",
    links: list | None = None,
    description: str = "",
) -> dict:
    return {
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": DS,
        "targets": [target(expr, legend=legend, instant=False)],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": steps or thresholds((None, "green")),
                "mappings": mappings or [],
                "links": links or [],
                "noValue": "no data",
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value_and_name" if legend else "value",
            "justifyMode": "auto",
            "orientation": "auto",
        },
    }


def timeseries(
    title: str,
    targets: list[dict],
    *,
    unit: str = "none",
    description: str = "",
    axis: tuple[float, float] | None = None,
    links: list | None = None,
) -> dict:
    defaults: dict = {"unit": unit, "custom": {"lineWidth": 1, "fillOpacity": 10}}
    if links:
        defaults["links"] = links
    if axis:
        # 값이 모두 0일 때 Grafana가 축을 엉뚱하게 잡지 않도록 범위를 고정합니다.
        defaults["min"], defaults["max"] = axis
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": DS,
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def bargauge(title: str, expr: str, legend: str, *, unit: str, steps: dict) -> dict:
    return {
        "type": "bargauge",
        "title": title,
        "datasource": DS,
        "targets": [target(expr, legend=legend)],
        "fieldConfig": {
            "defaults": {"unit": unit, "min": 0, "max": 1, "thresholds": steps},
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "horizontal",
            "displayMode": "gradient",
            "showUnfilled": True,
        },
    }


def table(
    title: str,
    key: str,
    columns: list[tuple[str, str, dict]],
    *,
    join: str = "outer",
    sort: tuple[str, bool] | None = None,
    description: str = "",
    order: list[str] | None = None,
    hidden: tuple[str, ...] = ("pg_id",),
) -> dict:
    """`key`로 조인한 instant 쿼리 표를 만듭니다.

    columns는 (열 제목, expr, 필드 설정)입니다. 첫 열의 쿼리가 레이블 열(이름, 경로)을
    담고, 나머지 쿼리는 `key`와 값만 남깁니다. 설정에 "labels": [...]가 있으면 그
    쿼리의 해당 레이블 열을 유지합니다.
    """
    targets, rename, overrides, keep = [], {}, [], {key}
    for i, (header, expr, cfg) in enumerate(columns):
        ref = chr(ord("A") + i)
        targets.append(target(expr, ref, instant=True))
        if cfg.get("labels"):
            keep.update(cfg["labels"])
            for label, shown in cfg.get("rename", {}).items():
                rename[label] = shown
        if cfg.get("value", True):
            rename[f"Value #{ref}"] = header
            keep.add(f"Value #{ref}")
            props = []
            if cfg.get("unit"):
                props.append({"id": "unit", "value": cfg["unit"]})
            if cfg.get("decimals") is not None:
                props.append({"id": "decimals", "value": cfg["decimals"]})
            if cfg.get("steps"):
                props.append({"id": "thresholds", "value": cfg["steps"]})
                props.append({"id": "custom.cellOptions", "value": {"type": "color-text"}})
            if cfg.get("gauge"):
                props.append(
                    {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic"}}
                )
                props += [{"id": "min", "value": 0}, {"id": "max", "value": cfg["gauge"]}]
            if props:
                overrides.append(
                    {"matcher": {"id": "byName", "options": header}, "properties": props}
                )
        for label, links in cfg.get("links", {}).items():
            overrides.append(
                {
                    "matcher": {"id": "byName", "options": rename.get(label, label)},
                    "properties": [{"id": "links", "value": links}],
                }
            )
        for label, mappings in cfg.get("mappings", {}).items():
            overrides.append(
                {
                    "matcher": {"id": "byName", "options": rename.get(label, label)},
                    "properties": [
                        {"id": "mappings", "value": mappings},
                        {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                    ],
                }
            )
    pattern = "^(" + "|".join(sorted(k.replace("#", "\\#") for k in keep)) + ")$"
    transformations = [
        {"id": "joinByField", "options": {"byField": key, "mode": join}},
        {"id": "filterFieldsByName", "options": {"include": {"pattern": pattern}}},
        {
            "id": "organize",
            "options": {
                "renameByName": rename,
                "excludeByName": {},
                # 열 순서는 표시 이름으로 받습니다. Grafana는 이를 이름 변경 전의
                # 원래 필드명(renameByName 이전)으로 찾습니다
                "indexByName": {
                    {shown: field for field, shown in rename.items()}.get(name, name): i
                    for i, name in enumerate(order or [])
                },
            },
        },
    ]
    if sort:
        transformations.append(
            {"id": "sortBy", "options": {"sort": [{"field": sort[0], "desc": sort[1]}]}}
        )
    return {
        "type": "table",
        "title": title,
        "description": description,
        "datasource": DS,
        "targets": targets,
        "transformations": transformations,
        "fieldConfig": {
            "defaults": {"custom": {"align": "auto", "filterable": True}},
            "overrides": overrides
            + [
                # id는 data link용으로 프레임에 남기되 화면에는 표시하지 않습니다
                {
                    "matcher": {"id": "byName", "options": name},
                    "properties": [{"id": "custom.hidden", "value": True}],
                }
                for name in (key, *hidden)
            ],
        },
        "options": {"showHeader": True, "cellHeight": "sm"},
    }


def text(title: str, content: str) -> dict:
    return {"type": "text", "title": title, "options": {"mode": "markdown", "content": content}}


# -- 공통 요소 ------------------------------------------------------------------


def with_address(metric: str) -> str:
    """노드 address 레이블을 붙입니다(범례용). 단독 NiFi는 node_id로 대신합니다."""
    return (
        f"{metric} * on (cluster, node_id) group_left (address) nifi_node_info{{{C}}}"
        f' or on (cluster, node_id) label_replace({metric}, "address", "$1", "node_id", "(.*)")'
    )


STATUS_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "Running": {"color": "green", "index": 0},
            "Stopped": {"color": "yellow", "index": 1},
            "Invalid": {"color": "red", "index": 2},
            "Disabled": {"color": "gray", "index": 3},
            "Validating": {"color": "blue", "index": 4},
            "CONNECTED": {"color": "green", "index": 5},
            "DISCONNECTED": {"color": "red", "index": 6},
            "CONNECTING": {"color": "yellow", "index": 7},
            "DISCONNECTING": {"color": "orange", "index": 8},
            "OFFLOADING": {"color": "orange", "index": 9},
            "OFFLOADED": {"color": "orange", "index": 10},
        },
    }
]
OK_FAIL = [
    {
        "type": "value",
        "options": {
            "1": {"text": "정상", "color": "green", "index": 0},
            "0": {"text": "실패", "color": "red", "index": 1},
        },
    }
]


def health_row(lay: Layout) -> None:
    """모든 대시보드 상단의 collector 상태입니다. "0"과 "미수집"을 구분합니다."""
    lay.add(
        stat(
            "수집기 상태",
            f"min by (collector) (nifi_exporter_collector_success{{{C}}})",
            legend="{{collector}}",
            mappings=OK_FAIL,
            steps=thresholds((None, "red"), (1, "green")),
            description="nifi_exporter_collector_success입니다. 실패이면 그 수집기의 메트릭이 "
            "노출되지 않으므로, 아래에서 비어 있는 값은 0이 아니라 '미수집'입니다.",
        ),
        16,
        3,
    )
    lay.add(
        stat(
            "Exporter 스크레이프",
            f'min(up{{job="nifi-exporter", {C}}})',
            mappings=OK_FAIL,
            steps=thresholds((None, "red"), (1, "green")),
        ),
        4,
        3,
    )
    lay.add(
        stat(
            "수집 지연",
            # 마지막 성공 이후 경과를 collector 주기 단위로 나타냅니다(topology는 5분마다
            # 돌아서 초 단위면 늘 늦어 보입니다). NiFiCollectorStale은 3배에서 발화합니다
            f"max((time() - nifi_exporter_collector_last_success_timestamp_seconds{{{C}}})"
            f" / nifi_exporter_collector_interval_seconds{{{C}}})",
            unit="suffix:×",
            steps=thresholds((None, "green"), (2, "orange"), (3, "red")),
            description="가장 늦은 수집기의 마지막 성공 후 경과 시간을 수집 주기로 나눈 "
            "배수입니다. 2 미만이 정상이며, 3에서 NiFiCollectorStale이 발화합니다.",
        ),
        4,
        3,
    )


def var_query(name: str, label: str, query: str, regex: str, *, all_: bool = True) -> dict:
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "query": {"query": query, "refId": f"var-{name}"},
        "definition": query,
        "regex": regex,
        "refresh": 2,
        "sort": 1,
        "includeAll": all_,
        "allValue": ".*",
        "multi": False,
        "current": {},
    }


def variables(*extra: dict) -> dict:
    cluster = var_query(
        "cluster", "클러스터", "label_values(nifi_pg_info, cluster)", "", all_=False
    )
    pg = var_query(
        "pg_id",
        "프로세스 그룹",
        f"query_result(nifi_pg_info{{{C}}})",
        '/pg_id="(?<value>[^"]+)".*pg_path="(?<text>[^"]+)"/',
    )
    return {"list": [cluster, pg, *extra]}


def dashboard(key: str, title: str, lay: Layout, templating: dict, annotations=None) -> dict:
    links = [
        {
            "type": "dashboards",
            "tags": ["nifi"],
            "asDropdown": False,
            "includeVars": True,
            "keepTime": True,
            "title": "NiFi 대시보드",
        }
    ]
    return {
        "uid": UIDS[key],
        "title": title,
        "tags": ["nifi"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "refresh": "30s",
        "time": {"from": "now-3h", "to": "now"},
        "templating": templating,
        "annotations": {"list": annotations or []},
        "links": links,
        "panels": lay.panels,
    }


# -- 대시보드 -------------------------------------------------------------------


def overview() -> dict:
    lay = Layout()
    health_row(lay)
    lay.row("클러스터")
    for title, expr, steps, link_to in [
        (
            "연결된 노드",
            f"nifi_cluster_nodes_connected{{{C}}}",
            thresholds((None, "green")),
            None,
        ),
        (
            "연결 안 된 노드",
            f"nifi_cluster_nodes_total{{{C}}} - nifi_cluster_nodes_connected{{{C}}}",
            GREEN_RED,
            None,
        ),
        ("Invalid 프로세서", f"nifi:processors_invalid:count{{{C}}}", GREEN_RED, "processor"),
        (
            "80% 초과 큐",
            f"nifi:queues_near_backpressure:count{{{C}}}",
            thresholds((None, "green"), (1, "orange")),
            "queue",
        ),
        (
            "Backpressure 발동 큐",
            f"nifi:queues_backpressure_engaged:count{{{C}}}",
            GREEN_RED,
            "queue",
        ),
        (
            "ERROR Bulletin (5분)",
            f"nifi:bulletins_error:increase5m:sum{{{C}}}",
            thresholds((None, "green"), (1, "orange"), (10, "red")),
            "incident",
        ),
    ]:
        links = (
            [{"title": "열기", "url": link(UIDS[link_to], cluster="${cluster}")}] if link_to else []
        )
        lay.add(stat(title, expr, steps=steps, links=links), 4, 4)

    node_cols = [
        (
            "노드",
            f"max by (node_id, address, api_port, roles) (nifi_node_info{{{C}}})",
            {
                "value": False,
                "labels": ["address", "api_port", "roles"],
                "rename": {"address": "주소", "api_port": "포트", "roles": "역할"},
            },
        ),
        (
            "상태",
            f"max by (node_id, status) (nifi_node_status{{{C}}} == 1)",
            {
                "value": False,
                "labels": ["status"],
                "rename": {"status": "상태"},
                "mappings": {"status": STATUS_MAPPINGS},
            },
        ),
        (
            "Heartbeat 경과",
            f"max by (node_id) (nifi_node_heartbeat_age_seconds{{{C}}})",
            {
                "unit": "s",
                "decimals": 0,
                "steps": thresholds((None, "green"), (30, "orange"), (60, "red")),
            },
        ),
        ("활성 스레드", f"max by (node_id) (nifi_node_active_threads{{{C}}})", {}),
        ("적체", f"max by (node_id) (nifi_node_queued_flowfiles{{{C}}})", {"unit": "short"}),
        ("적체 바이트", f"max by (node_id) (nifi_node_queued_bytes{{{C}}})", {"unit": "bytes"}),
        (
            "Heap",
            f"max by (node_id) (nifi_jvm_heap_utilization{{{C}}})",
            {"unit": "percentunit", "gauge": 1},
        ),
        (
            "가장 높은 저장소",
            f"max by (node_id) (nifi:repo_utilization:max{{{C}}})",
            {"unit": "percentunit", "gauge": 1},
        ),
        (
            "스레드 풀",
            f"max by (node_id) (nifi:thread_pool_utilization{{{C}}})",
            {"unit": "percentunit", "gauge": 1},
        ),
        (
            "가동 시간",
            f"max by (node_id) (nifi_jvm_uptime_seconds{{{C}}})",
            {"unit": "s", "decimals": 0},
        ),
    ]
    lay.add(
        table(
            "노드",
            "node_id",
            node_cols,
            order=["주소", "포트", "상태", "역할", "Heartbeat 경과"],
        ),
        24,
        6,
    )

    heap = f"nifi_jvm_heap_utilization{{{C}}}"
    lay.add(
        bargauge(
            "Heap 사용률",
            with_address(heap),
            "{{address}}",
            unit="percentunit",
            steps=thresholds((None, "green"), (0.85, "orange"), (0.95, "red")),
        ),
        12,
        6,
    )
    repo = f"nifi_repo_utilization{{{C}}}"
    lay.add(
        bargauge(
            "저장소 사용률",
            with_address(repo),
            "{{address}} {{repo}} {{repo_id}}",
            unit="percentunit",
            steps=thresholds((None, "green"), (0.8, "orange"), (0.92, "red")),
        ),
        12,
        6,
    )

    lay.row("플로우")
    lay.add(
        timeseries(
            "적체 FlowFile (클러스터)",
            [target(f"nifi:queued_flowfiles:sum{{{C}}}", legend="FlowFile")],
            unit="short",
        ),
        8,
        7,
    )
    lay.add(
        timeseries(
            "적체 바이트 (클러스터)",
            [target(f"nifi:queued_bytes:sum{{{C}}}", legend="바이트")],
            unit="bytes",
        ),
        8,
        7,
    )
    lay.add(
        timeseries(
            "ERROR Bulletin (5분)",
            [target(f"nifi:bulletins_error:increase5m:sum{{{C}}}", legend="ERROR")],
            unit="short",
        ),
        8,
        7,
    )
    alerts = {
        "type": "table",
        "title": "발화 중인 알림",
        "datasource": DS,
        "targets": [target(f'ALERTS{{alertstate="firing", {C}}}', instant=True)],
        "transformations": [
            {
                "id": "filterFieldsByName",
                "options": {
                    "include": {
                        "pattern": "^(alertname|severity|component|node_id|connection_id|"
                        "processor_id|collector|pg_id)$"
                    }
                },
            }
        ],
        "fieldConfig": {
            "defaults": {"custom": {"filterable": True}},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "severity"},
                    "properties": [
                        {
                            "id": "mappings",
                            "value": [
                                {
                                    "type": "value",
                                    "options": {
                                        "critical": {"color": "red", "index": 0},
                                        "warning": {"color": "orange", "index": 1},
                                    },
                                }
                            ],
                        },
                        {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                    ],
                }
            ],
        },
        "options": {"showHeader": True, "cellHeight": "sm"},
    }
    lay.add(alerts, 24, 7)
    return dashboard("overview", "NiFi / 개요", lay, variables())


def process_groups() -> dict:
    lay = Layout()
    health_row(lay)
    sel = f'{C}, pg_id=~"$pg_id"'
    to_pg = [
        {
            "title": "하위 그룹으로",
            "url": link(UIDS["pg"], cluster="${cluster}", pg_id="${__data.fields.pg_id}"),
        }
    ]
    to_proc = [
        {
            "title": "이 그룹의 프로세서",
            "url": link(UIDS["processor"], cluster="${cluster}", pg_id="${__data.fields.pg_id}"),
        },
        {
            "title": "이 그룹의 큐",
            "url": link(UIDS["queue"], cluster="${cluster}", pg_id="${__data.fields.pg_id}"),
        },
    ]
    cols = [
        (
            "경로",
            # 선택한 그룹과 그 직속 하위 그룹입니다
            f"max by (pg_id, pg_path, depth) (nifi_pg_info{{{sel}}}"
            f' or nifi_pg_info{{{C}, parent_id=~"$pg_id"}})',
            {
                "value": False,
                "labels": ["pg_path", "depth"],
                "rename": {"pg_path": "경로", "depth": "깊이"},
                "links": {"pg_path": to_pg + to_proc},
            },
        ),
        ("적체", f"max by (pg_id) (nifi_pg_queued_flowfiles{{{C}}})", {"unit": "short"}),
        ("적체 바이트", f"max by (pg_id) (nifi_pg_queued_bytes{{{C}}})", {"unit": "bytes"}),
        (
            "적체 Δ10분",
            f"max by (pg_id) (nifi:pg_queued_flowfiles:delta10m{{{C}}})",
            {"unit": "short", "decimals": 0},
        ),
        ("스레드", f"max by (pg_id) (nifi_pg_active_threads{{{C}}})", {}),
        ("유입 5분", f"max by (pg_id) (nifi_pg_flowfiles_in_5m{{{C}}})", {"unit": "short"}),
        ("유출 5분", f"max by (pg_id) (nifi_pg_flowfiles_out_5m{{{C}}})", {"unit": "short"}),
        ("처리 시간 5분", f"max by (pg_id) (nifi_pg_processing_seconds_5m{{{C}}})", {"unit": "s"}),
        ("실행 중", f'max by (pg_id) (nifi_pg_processors{{{C}, status="Running"}})', {}),
        ("정지", f'max by (pg_id) (nifi_pg_processors{{{C}, status="Stopped"}})', {}),
        (
            "Invalid",
            f'max by (pg_id) (nifi_pg_processors{{{C}, status="Invalid"}})',
            {"steps": GREEN_RED},
        ),
    ]
    lay.add(
        table(
            "프로세스 그룹 (선택 그룹 + 하위 그룹)",
            "pg_id",
            cols,
            join="inner",
            sort=("적체", True),
            order=["경로", "깊이"],
            description="경로를 클릭하면 하위 그룹이나 그 그룹의 프로세서·큐 화면으로 이동합니다.",
        ),
        24,
        10,
    )
    lay.add(
        timeseries(
            "적체 FlowFile",
            [target(f"nifi:pg_queued_flowfiles:named{{{sel}}}", legend="{{pg_path}}")],
            unit="short",
        ),
        12,
        8,
    )
    path = " * on (cluster, pg_id) group_left (pg_path) nifi_pg_info"
    lay.add(
        timeseries(
            "FlowFile 유입 / 유출 (5분 구간)",
            [
                target(
                    f"nifi_pg_flowfiles_in_5m{{{sel}}}{path}",
                    "A",
                    "유입 {{pg_path}}",
                ),
                target(
                    f"nifi_pg_flowfiles_out_5m{{{sel}}}{path}",
                    "B",
                    "유출 {{pg_path}}",
                ),
            ],
            unit="short",
        ),
        12,
        8,
    )
    return dashboard("pg", "NiFi / 프로세스 그룹", lay, variables())


def processors() -> dict:
    lay = Layout()
    health_row(lay)
    sel = PG
    fill = f"max by (processor_id) (0 * nifi_processor_running{{{sel}}})"
    to_queue = [
        {
            "title": "이 그룹의 큐",
            "url": link(UIDS["queue"], cluster="${cluster}", pg_id="${__data.fields.pg_id}"),
        },
        provenance_link(
            "Provenance 조회 (끝 시각 기준 5분)", "${__data.fields.processor_id}", "${__to}"
        ),
    ]
    cols = [
        (
            "이름",
            "max by (processor_id, pg_id, name, type, execution_node) "
            f"(nifi_processor_info{{{sel}}})",
            {
                "value": False,
                "labels": ["name", "type", "execution_node", "pg_id"],
                "rename": {"name": "이름", "type": "유형", "execution_node": "실행 노드"},
                "links": {"name": to_queue},
            },
        ),
        (
            "상태",
            f"max by (processor_id, status) (nifi_processor_run_status{{{sel}}} == 1)",
            {
                "value": False,
                "labels": ["status"],
                "rename": {"status": "상태"},
                "mappings": {"status": STATUS_MAPPINGS},
            },
        ),
        ("스레드", f"max by (processor_id) (nifi_processor_active_threads{{{sel}}})", {}),
        (
            "강제 종료",
            f"max by (processor_id) (nifi_processor_terminated_threads{{{sel}}})",
            {"steps": GREEN_RED},
        ),
        (
            "Task 5분",
            f"max by (processor_id) (nifi_processor_tasks_5m{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "평균 Task",
            "max by (processor_id) "
            f"(nifi:processor_task_duration_avg_seconds_5m{{{sel}}}) or {fill}",
            {"unit": "s"},
        ),
        (
            "유입 5분",
            f"max by (processor_id) (nifi_processor_flowfiles_in_5m{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "유출 5분",
            f"max by (processor_id) (nifi_processor_flowfiles_out_5m{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "읽기 5분",
            f"max by (processor_id) (nifi_processor_bytes_read_5m{{{sel}}})",
            {"unit": "bytes"},
        ),
        (
            "쓰기 5분",
            f"max by (processor_id) (nifi_processor_bytes_written_5m{{{sel}}})",
            {"unit": "bytes"},
        ),
        (
            # 선택한 Processor의 Bulletin이며, 없으면 0입니다
            "ERROR Bulletin 5분",
            "max by (processor_id) (label_replace("
            f'nifi:bulletins_error:increase5m{{{C}}}, "processor_id", "$1", "source_id", "(.*)"))'
            f" and on (processor_id) {fill} or {fill}",
            {"decimals": 0, "steps": thresholds((None, "green"), (1, "orange"), (10, "red"))},
        ),
    ]
    lay.add(
        table(
            "프로세서",
            "processor_id",
            cols,
            sort=("ERROR Bulletin 5분", True),
            order=["이름", "유형", "상태", "실행 노드"],
            description="프로세스 그룹 변수로 거릅니다(직속 프로세서만).",
        ),
        24,
        11,
    )
    proc = var_query(
        "processor_id",
        "프로세서",
        f"query_result(nifi_processor_info{{{sel}}})",
        # 레이블은 알파벳순으로 렌더링되므로 name이 processor_id보다 앞에 옵니다
        '/\\bname="(?<text>[^"]+)".*\\bprocessor_id="(?<value>[^"]+)"/',
    )
    psel = f'{C}, processor_id=~"$processor_id"'
    named = f" * on (cluster, processor_id) group_left (name) nifi_processor_info{{{C}}}"
    lay.add(
        timeseries(
            "Task (5분 구간)",
            [target(f"nifi_processor_tasks_5m{{{psel}}}{named}", legend="{{name}}")],
            unit="short",
        ),
        8,
        8,
    )
    lay.add(
        timeseries(
            "평균 Task 시간",
            [
                target(
                    f"nifi:processor_task_duration_avg_seconds_5m{{{psel}}}{named}",
                    legend="{{name}}",
                )
            ],
            unit="s",
        ),
        8,
        8,
    )
    lay.add(
        timeseries(
            "활성 스레드",
            [target(f"nifi_processor_active_threads{{{psel}}}{named}", legend="{{name}}")],
            unit="short",
        ),
        8,
        8,
    )
    return dashboard("processor", "NiFi / 프로세서", lay, variables(proc, PROVENANCE_VAR))


def queues() -> dict:
    lay = Layout()
    health_row(lay)
    sel = PG
    to_proc = [
        {
            "title": "이 그룹의 프로세서",
            "url": link(UIDS["processor"], cluster="${cluster}", pg_id="${__data.fields.pg_id}"),
        }
    ]
    cols = [
        (
            "이름",
            "max by (connection_id, pg_id, name, source_name, destination_name) "
            f"(nifi_connection_info{{{sel}}})",
            {
                "value": False,
                "labels": ["source_name", "destination_name", "name", "pg_id"],
                "rename": {
                    "source_name": "보내는 쪽",
                    "destination_name": "받는 쪽",
                    "name": "이름",
                },
                "links": {"source_name": to_proc, "destination_name": to_proc},
            },
        ),
        (
            "사용률",
            f"max by (connection_id) (nifi:connection_percent_used:max{{{sel}}})",
            {"unit": "percent", "gauge": 100},
        ),
        (
            "적체",
            f"max by (connection_id) (nifi_connection_queued_flowfiles{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "적체 바이트",
            f"max by (connection_id) (nifi_connection_queued_bytes{{{sel}}})",
            {"unit": "bytes"},
        ),
        (
            "Δ5분",
            f"max by (connection_id) (nifi:connection_queued_flowfiles:delta5m{{{sel}}})",
            {"unit": "short", "decimals": 0},
        ),
        (
            "Δ10분",
            f"max by (connection_id) (nifi:connection_queued_flowfiles:delta10m{{{sel}}})",
            {
                "unit": "short",
                "decimals": 0,
                "steps": thresholds((None, "green"), (1000, "orange")),
            },
        ),
        (
            "유입 5분",
            f"max by (connection_id) (nifi_connection_flowfiles_in_5m{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "유출 5분",
            f"max by (connection_id) (nifi_connection_flowfiles_out_5m{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "임계치 (개수)",
            f"max by (connection_id) (nifi_connection_backpressure_object_threshold{{{sel}}})",
            {"unit": "short"},
        ),
        (
            "임계치 (바이트)",
            f"max by (connection_id) (nifi_connection_backpressure_bytes_threshold{{{sel}}})",
            {"unit": "bytes"},
        ),
        (
            "받는 쪽 실행 중",
            f"max by (connection_id) (nifi:connection_destination_running{{{sel}}})",
            {"steps": thresholds((None, "orange"), (1, "green"))},
        ),
    ]
    lay.add(
        table(
            "큐",
            "connection_id",
            cols,
            sort=("사용률", True),
            order=["보내는 쪽", "받는 쪽", "이름"],
            description="Backpressure 사용률 순으로 정렬합니다. 받는 쪽이 프로세서가 아니면 "
            "'받는 쪽 실행 중'은 비어 있습니다.",
        ),
        24,
        11,
    )
    conn = var_query(
        "connection_id",
        "큐",
        f"query_result(nifi_connection_info{{{sel}}})",
        '/connection_id="(?<value>[^"]+)".*\\bname="(?<text>[^"]*)"/',
    )
    csel = f'{C}, connection_id=~"$connection_id"'
    named = (
        f" * on (cluster, connection_id) group_left (name, source_name, destination_name) "
        f"nifi_connection_info{{{C}}}"
    )
    legend = "{{source_name}} → {{destination_name}} ({{name}})"
    lay.add(
        timeseries(
            "적체 FlowFile",
            [target(f"nifi_connection_queued_flowfiles{{{csel}}}{named}", legend=legend)],
            unit="short",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "Backpressure 사용률",
            [target(f"nifi:connection_percent_used:max{{{csel}}}{named}", legend=legend)],
            unit="percent",
        ),
        12,
        8,
    )
    return dashboard("queue", "NiFi / 큐", lay, variables(conn))


def incident() -> dict:
    lay = Layout()
    health_row(lay)
    proc_name = (
        " * on (cluster, source_id) group_left (name) label_replace("
        f'nifi_processor_info{{{C}}}, "source_id", "$1", "processor_id", "(.*)")'
    )
    conn_name = (
        " * on (cluster, connection_id) group_left (name, source_name, destination_name) "
        f"nifi_connection_info{{{C}}}"
    )
    legend_q = "{{source_name}} → {{destination_name}} ({{name}})"
    lay.add(
        timeseries(
            "프로세서별 ERROR Bulletin (5분)",
            [
                target(
                    f"topk(10, nifi:bulletins_error:increase5m{{{C}}}{proc_name})",
                    legend="{{name}}",
                )
            ],
            unit="short",
            description="점을 클릭하면 그 시점까지 5분 동안의 Provenance를 조회합니다.",
            links=[
                provenance_link(
                    "Provenance 조회 (이 시점까지 5분)",
                    "${__field.labels.source_id}",
                    "${__value.time}",
                )
            ],
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "가장 빨리 쌓이는 큐 (Δ10분)",
            [
                target(
                    f"topk(10, nifi:connection_queued_flowfiles:delta10m{{{C}}}{conn_name})",
                    legend=legend_q,
                )
            ],
            unit="short",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "Backpressure 사용률 (상위 10)",
            [
                target(
                    f"topk(10, nifi:connection_percent_used:max{{{C}}}{conn_name})", legend=legend_q
                )
            ],
            unit="percent",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "가장 느린 프로세서 (평균 Task)",
            [
                target(
                    f"topk(10, nifi:processor_task_duration_avg_seconds_5m{{{C}}}"
                    f" * on (cluster, processor_id) group_left (name) nifi_processor_info{{{C}}})",
                    legend="{{name}}",
                )
            ],
            unit="s",
            description="점을 클릭하면 그 시점까지 5분 동안의 Provenance를 조회합니다.",
            links=[
                provenance_link(
                    "Provenance 조회 (이 시점까지 5분)",
                    "${__field.labels.processor_id}",
                    "${__value.time}",
                )
            ],
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "연결된 노드",
            [
                target(f"nifi_cluster_nodes_connected{{{C}}}", "A", "연결됨"),
                target(f"nifi_cluster_nodes_total{{{C}}}", "B", "전체"),
            ],
            unit="short",
        ),
        8,
        7,
    )
    lay.add(
        timeseries(
            "Heap 사용률",
            [target(with_address(f"nifi_jvm_heap_utilization{{{C}}}"), legend="{{address}}")],
            unit="percentunit",
        ),
        8,
        7,
    )
    lay.add(
        timeseries(
            "GC 시간 비율",
            [target(with_address(f"nifi:jvm_gc_time_ratio:rate5m{{{C}}}"), legend="{{address}}")],
            unit="percentunit",
        ),
        8,
        7,
    )
    lay.add(
        text(
            "Provenance",
            "**프로세서별 ERROR Bulletin**과 **가장 느린 프로세서** 그래프의 점을 클릭하면 "
            "그 프로세서의 Provenance를 그 시점까지 5분 범위로 새 탭에서 조회합니다"
            f"(nifi-provenance-query, `{PROVENANCE_URL}`). 이벤트 종류·시각·노드·FlowFile "
            "UUID만 보여 주고 속성과 내용은 보여 주지 않습니다. 더 넓은 범위나 내용은 NiFi UI의 "
            "*Data Provenance*에서 Component ID로 검색합니다.",
        ),
        24,
        3,
    )
    annotations = [
        {
            "name": "알림",
            "datasource": DS,
            "enable": True,
            "iconColor": "red",
            # 알림이 발화하기 시작한 순간만 표시합니다. 지금 firing이지만 2분 전에는 아니던
            # 시계열입니다(그냥 ALERTS를 쓰면 발화 구간 전체가 칠해집니다)
            "expr": f'ALERTS{{alertstate="firing", {C}}}'
            f' unless ALERTS{{alertstate="firing", {C}}} offset 2m',
            "step": "60s",
            "titleFormat": "{{alertname}}",
            "textFormat": "{{severity}} {{connection_id}}{{processor_id}}{{node_id}}",
            "useValueForTime": False,
        }
    ]
    return dashboard("incident", "NiFi / 장애 분석", lay, variables(PROVENANCE_VAR), annotations)


def jvm() -> dict:
    """JVM heap·GC와 NiFi 스레드 풀을 노드별로 봅니다."""
    lay = Layout()
    health_row(lay)
    lay.row("스레드")
    for title, expr, unit, steps in [
        (
            "스레드 풀 크기",
            f"max(nifi_controller_max_timer_driven_threads{{{C}}})",
            "none",
            thresholds((None, "blue")),
        ),
        (
            "활성 스레드 (전체 노드)",
            f"sum(nifi_controller_active_threads{{{C}}})",
            "none",
            thresholds((None, "green")),
        ),
        (
            "강제 종료 스레드",
            f"sum(nifi_controller_terminated_threads{{{C}}})",
            "none",
            GREEN_RED,
        ),
        (
            "최대 스레드 풀 사용률",
            f"max(nifi:thread_pool_utilization{{{C}}})",
            "percentunit",
            thresholds((None, "green"), (0.7, "orange"), (0.9, "red")),
        ),
    ]:
        lay.add(stat(title, expr, unit=unit, steps=steps), 6, 4)
    pool = f"nifi:thread_pool_utilization{{{C}}}"
    lay.add(
        timeseries(
            "스레드 풀 사용률 (노드별)",
            [target(with_address(pool), legend="{{address}}")],
            unit="percentunit",
            axis=(0, 1),
            description="활성 timer-driven 스레드 / 스레드 풀 크기(maxTimerDrivenThreadCount). "
            "90% 이상이 10분 지속되면 NiFiThreadPoolSaturated가 발화합니다.",
        ),
        12,
        8,
    )
    # 단일 노드에는 노드별 활성 스레드가 없으므로 전체 값으로 대신합니다
    active = (
        f"nifi_node_active_threads{{{C}}} or label_replace(nifi_controller_active_threads{{{C}}}"
        f', "node_id", "standalone", "", "") and on (cluster) (nifi_cluster_clustered{{{C}}} == 0)'
    )
    lay.add(
        timeseries(
            "활성 스레드와 스레드 풀 크기",
            [
                target(with_address(f"({active})"), "A", "{{address}} 활성"),
                target(
                    f"max(nifi_controller_max_timer_driven_threads{{{C}}})", "B", "스레드 풀 크기"
                ),
            ],
            unit="short",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "JVM 스레드 수",
            [
                target(with_address(f"nifi_jvm_threads{{{C}}}"), "A", "{{address}} 전체"),
                target(with_address(f"nifi_jvm_daemon_threads{{{C}}}"), "B", "{{address}} daemon"),
            ],
            unit="short",
            description="JVM 전체 스레드입니다(NiFi 스레드 풀 외 Jetty·클러스터 통신 등 포함). "
            "계속 늘기만 하면 스레드 누수를 의심합니다.",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "JVM 가동 시간",
            [target(with_address(f"nifi_jvm_uptime_seconds{{{C}}}"), legend="{{address}}")],
            unit="s",
            description="0 가까이 떨어지면 노드가 재시작된 것입니다.",
        ),
        12,
        8,
    )

    lay.row("Heap · GC")
    heap_used = f"nifi_jvm_heap_used_bytes{{{C}}}"
    lay.add(
        timeseries(
            "Heap 사용량",
            [
                target(with_address(heap_used), "A", "{{address}} 사용"),
                target(
                    with_address(f"nifi_jvm_heap_committed_bytes{{{C}}}"), "B", "{{address}} 확보"
                ),
                target(with_address(f"nifi_jvm_heap_max_bytes{{{C}}}"), "C", "{{address}} 최대"),
            ],
            unit="bytes",
            description="사용: 살아 있는 객체 크기. 확보(committed): JVM이 OS에서 잡아 둔 크기. "
            "최대: -Xmx. 사용량이 GC 직후에도 최대에 가까우면 heap이 부족한 것입니다.",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "Heap 사용률",
            [target(with_address(f"nifi_jvm_heap_utilization{{{C}}}"), legend="{{address}}")],
            unit="percentunit",
            description="85% 이상 10분이면 NiFiHeapHigh, 95% 이상 3분이면 NiFiHeapCritical입니다.",
        ),
        12,
        8,
    )
    lay.add(
        timeseries(
            "Non-heap 사용량",
            [
                target(
                    with_address(f"nifi_jvm_nonheap_used_bytes{{{C}}}"), "A", "{{address}} 사용"
                ),
                target(
                    with_address(f"nifi_jvm_nonheap_committed_bytes{{{C}}}"),
                    "B",
                    "{{address}} 확보",
                ),
            ],
            unit="bytes",
        ),
        8,
        8,
    )
    lay.add(
        timeseries(
            "GC 시간 비율",
            [target(with_address(f"nifi:jvm_gc_time_ratio:rate5m{{{C}}}"), legend="{{address}}")],
            unit="percentunit",
            description="최근 5분 중 GC에 쓴 시간의 비율입니다. "
            "20% 이상 10분이면 NiFiGCTimeHigh입니다.",
        ),
        8,
        8,
    )
    lay.add(
        timeseries(
            "GC 횟수 (분당)",
            [
                target(
                    with_address(
                        f"sum by (cluster, node_id, collector) "
                        f"(rate(nifi_jvm_gc_collections_total{{{C}}}[5m])) * 60"
                    ),
                    legend="{{address}} {{collector}}",
                )
            ],
            unit="short",
        ),
        8,
        8,
    )
    return dashboard("jvm", "NiFi / JVM·스레드", lay, variables())


BUILDERS = {
    "overview": overview,
    "process-groups": process_groups,
    "processors": processors,
    "queues": queues,
    "incident": incident,
    "jvm": jvm,
}


def render() -> dict[str, str]:
    return {
        f"nifi-{name}.json": json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
        for name, build in BUILDERS.items()
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="dashboards/가 최신이 아니면 실패합니다")
    args = ap.parse_args()
    files = render()
    if args.check:
        stale = [
            n for n, c in files.items() if not (OUT / n).is_file() or (OUT / n).read_text() != c
        ]
        if stale:
            sys.exit(f"대시보드가 최신이 아닙니다 (build_dashboards.py를 실행하세요): {stale}")
        print("대시보드가 최신입니다")
        return
    OUT.mkdir(exist_ok=True)
    for name, content in files.items():
        (OUT / name).write_text(content)
        print(f"dashboards/{name}를 썼습니다")


if __name__ == "__main__":
    main()

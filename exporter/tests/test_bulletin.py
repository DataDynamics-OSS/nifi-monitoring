"""NiFi 2.6.0 클러스터처럼 동작하는 가짜 board로 Bulletin collector를 시험합니다.

2.6.0에서 확인한 동작입니다: id는 노드별 시퀀스이고, ``after``/``limit``은 노드별로
적용되며, 결과는 노드 안에서 오름차순이고, 재시작한 노드는 0부터 다시 시작합니다.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from werkzeug.wrappers import Response

from nifi_exporter.collectors import BulletinCollector
from nifi_exporter.collectors import bulletin as bulletin_module
from nifi_exporter.scheduler import CollectorRunner

from .conftest import sample


class FakeBoard:
    def __init__(self) -> None:
        self.nodes: dict[str, list[dict]] = {}
        self.requests: list[dict] = []

    def add(self, node: str, bid: int, level="ERROR", source="proc-put", pg="pg-ingest"):
        self.nodes.setdefault(node, []).append(
            {
                "id": bid,
                "nodeAddress": node,
                "groupId": pg,
                "sourceId": source,
                "canRead": True,
                "bulletin": {
                    "id": bid,
                    "nodeAddress": node,
                    "category": "Log Message",
                    "groupId": pg,
                    "sourceId": source,
                    "sourceName": source,
                    "sourceType": "PROCESSOR",
                    "level": level,
                    "message": f"bulletin {bid}",
                    "timestamp": "01:00:00 UTC",
                },
            }
        )

    def restart(self, node: str) -> None:
        self.nodes[node] = []

    def handler(self, req):
        after = req.args.get("after")
        limit = int(req.args.get("limit", 100))
        self.requests.append({"after": after, "limit": limit})
        out = []
        for entries in self.nodes.values():
            picked = [e for e in sorted(entries, key=lambda e: e["id"])]
            if after is not None:
                picked = [e for e in picked if e["id"] > int(after)]
            out += picked[:limit]
        body = {"bulletinBoard": {"bulletins": out, "generated": "01:00:00 UTC"}}
        return Response(json.dumps(body), content_type="application/json")


def setup(httpserver, client, harness, limit=1000, log_messages=False):
    board = FakeBoard()
    httpserver.expect_request("/nifi-api/flow/bulletin-board").respond_with_handler(board.handler)
    col = BulletinCollector(client, "test", limit=limit, log_messages=log_messages)
    registry, store, sm = harness
    return board, col, CollectorRunner(col, 30, store, sm), registry


def errors(registry, source="proc-put", pg="pg-ingest", level="ERROR"):
    return sample(
        registry,
        "nifi_bulletins_total",
        cluster="test",
        level=level,
        pg_id=pg,
        source_id=source,
        source_type="PROCESSOR",
    )


def test_first_run_primes_without_counting(httpserver, client, harness):
    board, col, runner, reg = setup(httpserver, client, harness)
    board.add("nifi-1:8443", 10)
    board.add("nifi-2:8443", 50)
    assert runner.run_once()
    assert col.cursors == {"nifi-1:8443": 10, "nifi-2:8443": 50}
    assert errors(reg) is None


def test_per_node_cursors_count_each_bulletin_once(httpserver, client, harness):
    board, col, runner, reg = setup(httpserver, client, harness)
    board.add("nifi-1:8443", 10)
    board.add("nifi-2:8443", 50)
    assert runner.run_once()
    # nifi-1의 새 id는 nifi-2의 커서보다 작습니다. 전역 커서 하나로는 놓치게 됩니다
    board.add("nifi-1:8443", 11)
    board.add("nifi-1:8443", 12)
    board.add("nifi-2:8443", 51)
    t0 = time.time()
    assert runner.run_once()
    assert errors(reg) == 3
    assert (
        sample(
            reg,
            "nifi_bulletin_last_timestamp_seconds",
            cluster="test",
            level="ERROR",
            source_id="proc-put",
        )
        >= t0
    )
    # 새 항목이 없습니다. 카운터는 유지되고 중복 집계되지 않습니다
    assert runner.run_once()
    assert errors(reg) == 3
    assert col.cursors == {"nifi-1:8443": 12, "nifi-2:8443": 51}


def test_levels_and_sources_are_separate_series(httpserver, client, harness):
    board, _, runner, reg = setup(httpserver, client, harness)
    assert runner.run_once()
    board.add("nifi-1:8443", 1)
    board.add("nifi-1:8443", 2, level="WARNING", source="proc-gen", pg="root-id")
    assert runner.run_once()
    assert errors(reg) == 1
    assert errors(reg, source="proc-gen", pg="root-id", level="WARNING") == 1


def test_node_restart_resets_its_cursor(httpserver, client, harness):
    board, col, runner, reg = setup(httpserver, client, harness)
    board.add("nifi-1:8443", 500)
    assert runner.run_once()
    board.restart("nifi-1:8443")
    board.add("nifi-1:8443", 0)
    board.add("nifi-1:8443", 1)
    assert runner.run_once()
    assert errors(reg) == 2
    assert col.cursors == {"nifi-1:8443": 1}


def test_new_node_after_start_is_counted(httpserver, client, harness):
    board, _, runner, reg = setup(httpserver, client, harness)
    board.add("nifi-1:8443", 5)
    assert runner.run_once()
    board.add("nifi-3:8443", 0)
    assert runner.run_once()
    assert errors(reg) == 1


def test_truncated_node_is_paged(httpserver, client, harness):
    board, col, runner, reg = setup(httpserver, client, harness, limit=3)
    assert runner.run_once()  # 빈 board로 커서를 설정합니다
    for bid in range(1, 8):  # nifi-1에 7건이 새로 생기고, limit는 노드당 3입니다
        board.add("nifi-1:8443", bid)
    board.add("nifi-2:8443", 1)
    assert runner.run_once()
    assert errors(reg) == 8
    assert col.cursors == {"nifi-1:8443": 7, "nifi-2:8443": 1}
    afters = [r["after"] for r in board.requests[1:]]
    assert afters == [None, "3", "6"]


def test_standalone_without_node_address(httpserver, client, harness):
    board, col, runner, reg = setup(httpserver, client, harness)
    board.add("", 3)
    assert runner.run_once()
    board.add("", 4)
    assert runner.run_once()
    assert errors(reg) == 1
    assert col.cursors == {"": 4}


def test_messages_are_logged_not_labelled(httpserver, client, harness, caplog):
    board, _, runner, reg = setup(httpserver, client, harness, log_messages=True)
    assert runner.run_once()
    board.add("nifi-1:8443", 1)
    with caplog.at_level("INFO", logger="nifi_exporter.bulletin"):
        assert runner.run_once()
    assert [r.getMessage() for r in caplog.records if r.name == "nifi_exporter.bulletin"] == [
        "bulletin 1"
    ]
    labels = {
        k
        for m in reg.collect()
        for s in m.samples
        if s.name == "nifi_bulletins_total"
        for k in s.labels
    }
    assert "message" not in labels


def test_window_counts_first_batch_and_expires_without_losing_total(
    httpserver, client, harness, monkeypatch
):
    ticks = {"now": 1000.0}
    monkeypatch.setattr(
        bulletin_module,
        "time",
        # 벽시계가 뒤로 가도 만료는 경과 시간 기준입니다.
        SimpleNamespace(time=lambda: 10_000 - ticks["now"], monotonic=lambda: ticks["now"]),
    )
    board, _, runner, reg = setup(httpserver, client, harness)
    board.add("n1", 0)  # 시작 전에 있던 Bulletin은 최근 건수에도 넣지 않습니다.
    assert runner.run_once()
    for node in ("n1", "n2", "n3"):
        for bid in range(1, 6):
            board.add(node, bid)
    ticks["now"] = 1030
    assert runner.run_once()

    def recent():
        return sample(
            reg,
            "nifi_bulletins_observed_5m",
            cluster="test",
            level="ERROR",
            pg_id="pg-ingest",
            source_id="proc-put",
            source_type="PROCESSOR",
        )

    assert recent() == 15
    assert errors(reg) == 15
    ticks["now"] = 1090
    board.add("n1", 6)
    assert runner.run_once()
    assert recent() == 16
    ticks["now"] = 1329
    assert runner.run_once()
    assert recent() == 16  # 같은 Bulletin을 다시 받아도 중복 집계하지 않습니다.
    ticks["now"] = 1330
    assert runner.run_once()
    assert recent() == 1
    ticks["now"] = 1390
    assert runner.run_once()
    assert recent() == 0
    assert errors(reg) == 16


def test_window_recovers_after_collection_failure(httpserver, client, harness, monkeypatch):
    ticks = {"now": 1000.0}
    monkeypatch.setattr(
        bulletin_module,
        "time",
        SimpleNamespace(time=lambda: ticks["now"], monotonic=lambda: ticks["now"]),
    )
    board, _, runner, reg = setup(httpserver, client, harness)
    assert runner.run_once()
    board.add("n1", 1)
    assert runner.run_once()
    httpserver.clear()
    httpserver.expect_request("/nifi-api/flow/bulletin-board").respond_with_data("", status=403)
    assert not runner.run_once()
    assert errors(reg) is None
    ticks["now"] = 1400
    httpserver.clear()
    httpserver.expect_request("/nifi-api/flow/bulletin-board").respond_with_handler(board.handler)
    board.add("n1", 2)
    assert runner.run_once()
    assert errors(reg) == 2
    assert (
        sample(
            reg,
            "nifi_bulletins_observed_5m",
            cluster="test",
            level="ERROR",
            pg_id="pg-ingest",
            source_id="proc-put",
            source_type="PROCESSOR",
        )
        == 1
    )

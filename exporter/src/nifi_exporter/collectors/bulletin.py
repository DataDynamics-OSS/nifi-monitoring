"""``GET /flow/bulletin-board`` → level/source별 Bulletin 카운터입니다.

NiFi는 Bulletin을 메모리에만(약 5분, 컴포넌트당 최대 5건) 보관하므로, collector는
마지막으로 본 id를 기억해 각 Bulletin을 한 번만 셉니다. 클러스터에서는 다음과
같습니다(NiFi 2.6.0에서 확인했습니다).

- Bulletin id는 노드마다 별도 시퀀스이고, ``after``/``limit``도 노드별로 적용됩니다.
  결과는 노드 안에서 id 오름차순입니다.
- 재시작한 노드는 시퀀스를 0부터 다시 시작합니다.

그래서 커서를 노드(``nodeAddress``)별로 둡니다. 매 주기 ``after`` 없이 board를
가져오며(board가 작아 부담이 적습니다), 이를 통해 재시작한 노드도 드러납니다(최신
id가 커서보다 작아집니다). ``limit``만큼 돌려준 노드는 더 가지고 있을 수 있으므로
``after=<그 노드의 최신 id>``로 다음 페이지를 가져옵니다.

첫 주기에는 커서만 설정하므로, 재시작해도 오래된 Bulletin을 다시 세지 않습니다.
새 source의 첫 수집분도 집계하도록 최근 5분 관측 건수를 별도 gauge로 내보냅니다.
누적 카운터의 첫 샘플에는 이전 0이 없어 increase()로는 그 수집분을 셀 수 없습니다.
메시지 본문은 절대 레이블로 쓰지 않으며, ``log_messages=True``이면 대신 구조화된
로그 줄로 남깁니다.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from prometheus_client.core import Metric

from .base import BaseCollector

log = logging.getLogger(__name__)
bulletin_log = logging.getLogger("nifi_exporter.bulletin")

CountKey = tuple[str, str, str, str]  # level, pg_id, source_id, source_type 순서입니다
LastKey = tuple[str, str]  # level, source_id 순서입니다
MAX_PAGES = 5


class BulletinCollector(BaseCollector):
    name = "bulletin"

    def __init__(
        self, client, cluster_name: str, limit: int = 1000, log_messages: bool = False
    ) -> None:
        super().__init__(client, cluster_name)
        self._limit = max(1, limit)
        self._log_messages = log_messages
        self._primed = False
        self._cursors: dict[str, int] = {}  # nodeAddress(단독은 "") → 마지막으로 본 id입니다
        self._counts: dict[CountKey, int] = defaultdict(int)
        self._last_seen: dict[LastKey, float] = {}
        # 개별 메시지 대신 수집 주기별 집계를 보관합니다. 시간 범위는 monotonic으로
        # 측정해 서버 시각 보정이 5분 윈도우를 늘리거나 줄이지 않게 합니다.
        self._recent: deque[tuple[float, dict[CountKey, int]]] = deque()
        self._window_counts: dict[CountKey, int] = defaultdict(int)

    @property
    def cursors(self) -> dict[str, int]:
        return dict(self._cursors)

    def collect(self) -> list[Metric]:
        by_node = self._fetch_all()
        now = time.time()
        window_now = time.monotonic()
        batch: dict[CountKey, int] = defaultdict(int)

        new = 0
        for node, entries in by_node.items():
            ids = sorted(entries)
            cursor = self._cursors.get(node)
            if not self._primed:
                self._cursors[node] = ids[-1]
                continue
            if cursor is None:
                cursor = -1  # 처음 보는 노드이므로 가진 것이 모두 새 Bulletin입니다
            elif ids[-1] < cursor:
                log.info("node bulletin ids restarted", extra={"node": node, "cursor": cursor})
                cursor = -1
            for bid in ids:
                if bid > cursor:
                    key = self._count(bid, node, entries[bid], now)
                    batch[key] += 1
                    new += 1
            self._cursors[node] = max(ids[-1], cursor)

        if not self._primed:
            self._primed = True
            log.info(
                "bulletin cursors primed",
                extra={"cursors": dict(self._cursors), "skipped": sum(map(len, by_node.values()))},
            )
        elif new:
            log.debug("bulletins counted", extra={"new": new})
        if batch:
            self._recent.append((window_now, batch))
            for key, count in batch.items():
                self._window_counts[key] += count
        while self._recent and self._recent[0][0] <= window_now - 300:
            _, expired = self._recent.popleft()
            for key, count in expired.items():
                self._window_counts[key] -= count
                if not self._window_counts[key]:
                    del self._window_counts[key]
        return self._families()

    # -- 조회 ----------------------------------------------------------

    def _fetch_all(self) -> dict[str, dict[int, dict]]:
        """현재 보관 중인 Bulletin 전부를 {node: {id: entry}}로 반환합니다.

        잘린 노드는 페이지로 더 가져옵니다.
        """
        by_node: dict[str, dict[int, dict]] = defaultdict(dict)
        after: int | None = None
        for _ in range(MAX_PAGES):
            page: dict[str, int] = defaultdict(int)  # 이 응답에서 노드별 항목 수입니다
            for entry in self._fetch(after):
                bid = entry.get("id")
                if bid is None:
                    continue
                b = entry.get("bulletin") or {}
                node = str(entry.get("nodeAddress") or b.get("nodeAddress") or "")
                by_node[node][int(bid)] = entry
                page[node] += 1
            truncated = [n for n, count in page.items() if count >= self._limit]
            if not truncated:
                return by_node
            # 가장 뒤처진 잘린 노드를 기준으로 다음 페이지를 가져옵니다. 다른 노드가
            # 이미 가진 항목을 다시 돌려줘도 dict가 중복을 없앱니다.
            after = min(max(by_node[n]) for n in truncated)
        log.warning(
            "bulletin board still truncated after paging; some bulletins not counted",
            extra={"pages": MAX_PAGES, "limit": self._limit},
        )
        return by_node

    def _fetch(self, after: int | None) -> list[dict]:
        params: dict[str, object] = {"limit": self._limit}
        if after is not None:
            params["after"] = after
        body = self.client.get_json(
            "/flow/bulletin-board", params=params, endpoint="bulletin_board"
        )
        return (body.get("bulletinBoard") or {}).get("bulletins") or []

    # -- 집계 ----------------------------------------------------------

    def _count(self, bid: int, node: str, entry: dict, now: float) -> CountKey:
        b = entry.get("bulletin") or {}
        level = str(b.get("level") or "UNKNOWN").upper()
        pg_id = str(b.get("groupId") or "")
        source_id = str(b.get("sourceId") or "")
        source_type = str(b.get("sourceType") or "")
        key = (level, pg_id, source_id, source_type)
        self._counts[key] += 1
        self._last_seen[(level, source_id)] = now
        if self._log_messages:
            bulletin_log.info(
                b.get("message") or "",
                extra={
                    "bulletin_id": bid,
                    "level": level,
                    "category": b.get("category"),
                    "pg_id": pg_id,
                    "source_id": source_id,
                    "source_name": b.get("sourceName"),
                    "source_type": source_type,
                    "node_address": node,
                    "nifi_timestamp": b.get("timestamp"),
                },
            )
        return key

    def _families(self) -> list[Metric]:
        ms = self.new_set()
        total = ms.counter(
            "nifi_bulletins",
            "Bulletins observed since exporter start, by level and source. A lower bound: "
            "NiFi keeps at most 5 bulletins per component for about 5 minutes.",
            ["level", "pg_id", "source_id", "source_type"],
        )
        recent = ms.gauge(
            "nifi_bulletins_observed_5m",
            "Bulletins first observed in the last 5 minutes, by level and source, "
            "as of the last successful collection. Includes the first batch for new sources. "
            "A lower bound due to NiFi bulletin retention.",
            ["level", "pg_id", "source_id", "source_type"],
        )
        last = ms.gauge(
            "nifi_bulletin_last_timestamp_seconds",
            "Unix time the exporter last observed a bulletin for this level/source.",
            ["level", "source_id"],
        )
        for key, n in self._counts.items():
            total.add(list(key), n)
            recent.add(list(key), self._window_counts.get(key, 0))
        for key, ts in self._last_seen.items():
            last.add(list(key), ts)
        return ms.families()

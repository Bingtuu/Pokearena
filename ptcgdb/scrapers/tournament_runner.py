"""赛事采集运行器（task 027 第二段，FR-9.1/9.5）。

链路：series-list → 各系列 list → 每场 detail + rank-individual（第 1 页，
top_n 默认 64 与 top64 对齐）+ deck-static-by-tour → 每卡组 deck/detail，
全部落 raw（append-only：raw 文件存在且 hash 有效即跳过，零请求断点续传；
force=True 重抓）。三清单 + scrape_runs 复用 runner.finish_run。

熔断（CircuitOpenError）立即中止本轮，已抓产物保留，status=aborted。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ptcgdb.scrapers import mikmoe
from ptcgdb.scrapers.http import CircuitOpenError
from ptcgdb.scrapers.mikmoe import MikMoeApiError
from ptcgdb.scrapers.mikmoe_tournament import (
    DEFAULT_PAGE_SIZE,
    MikMoeTournamentScraper,
    deck_detail_path,
    deck_static_path,
    rank_individual_path,
    series_list_path,
    tournament_detail_path,
    tournament_list_path,
)
from ptcgdb.scrapers.raw_store import is_valid_raw, read_raw, write_raw
from ptcgdb.scrapers.runner import (
    RunResult,
    RunStats,
    _new_run_id,
    finish_run,
)


class TournamentScrapeRunner:
    """赛事链路抓取组织；scraper 鸭子类型注入（测试用 fixture 假 scraper）。"""

    def __init__(
        self,
        raw_dir: Path,
        scraper: MikMoeTournamentScraper,
        db_path: Path | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.scraper = scraper
        self.db_path = Path(db_path) if db_path else None

    def scrape(
        self,
        *,
        series_id: str | None = None,
        max_tournaments: int | None = None,
        top_n: int = 64,
        force: bool = False,
    ) -> RunResult:
        """抓赛事链路。series_id 限定单个系列；max_tournaments 截断处理场数。"""
        run_id, started_at = _new_run_id()
        stats = RunStats()
        state = _State(stats, force)
        try:
            series_entries = self._scrape_series_pages(state, force=force)
            for series in series_entries:
                sid = series.get("id") or series.get("seriesId")  # 实测主键字段为 id
                if sid is None:
                    stats.question.append(
                        {"id": None, "endpoint": "/api/v3/tournament/series-list",
                         "reason": "系列条目缺 id 字段"}
                    )
                    continue
                if series_id is not None and str(sid) != str(series_id):
                    continue
                self._scrape_series(int(sid), state, max_tournaments, top_n, force=force)
        except CircuitOpenError:
            stats.aborted = True

        self._reconcile_missing(state)
        return finish_run(self.raw_dir, self.db_path, run_id, started_at, stats)

    # ---- 系列层 ----

    def _scrape_series_pages(self, state: _State, *, force: bool) -> list[dict[str, Any]]:
        """series-list 翻页落盘，返回全部系列条目。"""
        entries: list[dict[str, Any]] = []
        page = 1
        while True:
            path = series_list_path(self.raw_dir, page)
            payload = self._ensure(
                path,
                f"series-list/page-{page}",
                lambda page=page: self.scraper.fetch_series_list(page, DEFAULT_PAGE_SIZE),
                state,
                force=force,
            )
            if payload is None:
                break
            items = _list_entries(payload)
            entries.extend(items)
            if len(items) < DEFAULT_PAGE_SIZE:
                break
            page += 1
        return entries

    def _scrape_series(
        self,
        sid: int,
        state: _State,
        max_tournaments: int | None,
        top_n: int,
        *,
        force: bool,
    ) -> None:
        page = 1
        processed = 0
        while True:
            path = tournament_list_path(self.raw_dir, str(sid), page)
            payload = self._ensure(
                path,
                f"tournament-list/{sid}/page-{page}",
                lambda page=page: self.scraper.fetch_tournament_list(
                    sid, page, DEFAULT_PAGE_SIZE
                ),
                state,
                force=force,
            )
            if payload is None:
                break
            items = _list_entries(payload)
            for item in items:
                if max_tournaments is not None and state.tournaments_done >= max_tournaments:
                    return
                tid = item.get("id") or item.get("tournamentId")  # 实测主键字段为 id
                if tid is None:
                    state.stats.question.append(
                        {"id": f"series-{sid}", "endpoint": "/api/v3/tournament/list",
                         "reason": "赛事条目缺 id 字段"}
                    )
                    continue
                state.tournaments_done += 1
                processed += 1
                self._scrape_tournament(int(tid), state, top_n, force=force)
            if len(items) < DEFAULT_PAGE_SIZE or processed == 0:
                break
            page += 1

    # ---- 赛事层 ----

    def _scrape_tournament(
        self, tid: int, state: _State, top_n: int, *, force: bool
    ) -> None:
        state.expected.append(
            ("tournament", str(tid), tournament_detail_path(self.raw_dir, str(tid)))
        )
        self._ensure(
            tournament_detail_path(self.raw_dir, str(tid)),
            f"tournament/{tid}",
            lambda: self.scraper.fetch_tournament_detail(tid),
            state,
            force=force,
        )
        state.expected.append(
            ("rank", str(tid), rank_individual_path(self.raw_dir, str(tid), 1))
        )
        rank_payload = self._ensure(
            rank_individual_path(self.raw_dir, str(tid), 1),
            f"rank/{tid}/page-1",
            lambda: self.scraper.fetch_rank_individual(tid, 1, top_n),
            state,
            force=force,
        )
        state.expected.append(("static", str(tid), deck_static_path(self.raw_dir, str(tid))))
        self._ensure(
            deck_static_path(self.raw_dir, str(tid)),
            f"deck-static/{tid}",
            lambda: self.scraper.fetch_deck_static_by_tour(tid),
            state,
            force=force,
        )
        for deck_id in _deck_ids(rank_payload or {}):
            state.expected.append(
                ("deck", str(deck_id), deck_detail_path(self.raw_dir, str(deck_id)))
            )
            self._ensure(
                deck_detail_path(self.raw_dir, str(deck_id)),
                f"deck/{deck_id}",
                lambda deck_id=deck_id: self.scraper.fetch_deck_detail(deck_id),
                state,
                force=force,
            )

    # ---- 单文件抓取（断点续传）----

    def _ensure(
        self,
        path: Path,
        label: str,
        fetch: Callable[[], dict[str, Any]],
        state: _State,
        *,
        force: bool,
    ) -> dict[str, Any] | None:
        """保证 path 的 raw 可用；存在且 hash 有效即跳过（零请求）。返回响应包装。"""
        if not force and is_valid_raw(path):
            state.stats.scraped.append({"id": label, "path": str(path), "action": "skipped"})
            return read_raw(path)
        try:
            payload = fetch()
        except MikMoeApiError as exc:
            state.stats.question.append(
                {"id": label, "endpoint": exc.endpoint, "reason": str(exc)}
            )
            return None
        write_raw(path, payload, source=mikmoe.SOURCE, force=force)
        state.stats.scraped.append({"id": label, "path": str(path), "action": "fetched"})
        return payload

    # ---- 对账 ----

    def _reconcile_missing(self, state: _State) -> None:
        """本轮应抓而 raw 缺失/无效的条目进 missing。"""
        seen: set[Path] = set()
        for _kind, label, path in state.expected:
            if path in seen:
                continue
            seen.add(path)
            if not is_valid_raw(path):
                state.stats.missing.append(
                    {"id": str(label), "reason": "未抓到或 hash 无效"}
                )


class _State:
    """一轮运行的可变状态（统计 + 断点续传上下文）。"""

    def __init__(self, stats: RunStats, force: bool) -> None:
        self.stats = stats
        self.force = force
        self.tournaments_done = 0
        self.expected: list[tuple[str, str, Path]] = []


def _list_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """清单端点 data 形态 {list: [...]}（兼容裸数组），与卡牌 runner 同口径。"""
    data = payload.get("data")
    if isinstance(data, dict):
        entries = data.get("list") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    return [e for e in entries if isinstance(e, dict)]


def _deck_ids(rank_payload: dict[str, Any]) -> list[int]:
    """rank-individual 响应 → 卡组 id 列表（int，去重保序；采集器 id 参数只接受 int）。"""
    ids: list[int] = []
    for entry in _list_entries(rank_payload):
        for deck in entry.get("decks") or []:
            if deck.get("deckId") is not None:
                deck_id = int(deck["deckId"])
                if deck_id not in ids:
                    ids.append(deck_id)
    return ids

"""Limitless 主站 HTML 采集运行器（task 028 扩展：官方线下大赛人工收录通道）。

链路：赛季索引翻页（?time={season}，单赛季实测 ≤100 场单页抓全）→ 对齐窗口过滤
→ classify_site_tournament 归类（主站名称形态变体）→ accepted 赛事抓 standings
→ 去重后的 decklist_id 逐个抓卡组页，全部落 raw（解析后 JSON 快照，append-only：
raw 文件存在且 hash 有效即跳过，零请求断点续传；force=True 重抓）。三清单 +
scrape_runs 复用 runner.finish_run。

与 API 通道（limitless_runner.py）的口径差异：
- 翻页终止：索引按赛季单页抓全（实测无翻页 UI）；某页恰好返回 INDEX_PAGE_SIZE
  （100，show 上限）时才尝试 ?page=N+1（未实测参数，best-effort），"无新
  tournament_id" 即停兜底（参数被忽略返回重复页也能正确终止）；
- 主站无 pairings/record，accepted 只抓 standings + 卡组页；
- 同一 decklist 可被多名选手共用（实测 NAIC 一表 5 人同表），run 内去重 +
  raw 路径天然跨场次断点复用。

取舍决策逐场记入 stats.scraped（action="accepted"/"rejected"，附 name/tier/
reason/players/date）；窗口外赛事只计数不记细节。stats.total = accepted 场数。
熔断（CircuitOpenError）立即中止本轮，已抓产物保留，status=aborted。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from ptcgdb.normalize.envs import alignment_window
from ptcgdb.scrapers.http import CircuitOpenError
from ptcgdb.scrapers.limitless_site import (
    INDEX_PAGE_SIZE,
    SOURCE,
    LimitlessSiteApiError,
    LimitlessSiteScraper,
    classify_site_tournament,
    decklist_path,
    index_path,
    seasons_for_window,
    standings_path,
)
from ptcgdb.scrapers.raw_store import is_valid_raw, read_raw, write_raw
from ptcgdb.scrapers.runner import (
    RunResult,
    RunStats,
    _new_run_id,
    finish_run,
)

_MAX_INDEX_PAGES = 5  # 翻页保险上限（实测单赛季单页；page 参数未实测，防死循环）


class LimitlessSiteScrapeRunner:
    """主站 HTML 链路抓取组织；scraper 鸭子类型注入（测试用假 scraper）。"""

    def __init__(
        self,
        raw_dir: Path,
        scraper: LimitlessSiteScraper,
        db_path: Path | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.scraper = scraper
        self.db_path = Path(db_path) if db_path else None

    def scrape(
        self,
        date_from: date | str | None = None,
        date_to: date | str | None = None,
        *,
        seasons: list[str] | None = None,
        max_tournaments: int | None = None,
        force: bool = False,
    ) -> RunResult:
        """抓对齐窗口内的主站收录赛事。显式 date_from/date_to 优先，缺省 = alignment_window()。

        seasons 显式指定赛季标签列表（如 ["2425", "2526"]），缺省 = 覆盖窗口的赛季。
        max_tournaments 截断 accepted 场数（调试/小样用）。
        """
        run_id, started_at = _new_run_id()
        stats = RunStats()
        default_from, default_to = alignment_window()
        window_from = _to_date(date_from) or default_from
        window_to = _to_date(date_to) or default_to
        season_list = list(seasons) if seasons else seasons_for_window(window_from, window_to)
        state = _State(stats, window_from, window_to, max_tournaments)
        try:
            for season in season_list:
                self._scrape_season(season, state, force=force)
                if state.limit_reached:
                    break
        except CircuitOpenError:
            stats.aborted = True

        self._reconcile_missing(state)
        return finish_run(self.raw_dir, self.db_path, run_id, started_at, stats)

    # ---- 赛季索引翻页 ----

    def _scrape_season(self, season: str, state: _State, *, force: bool) -> None:
        """单赛季索引翻页：< show 上限即停；恰好满页才试 ?page=N+1；无新 id 即停。"""
        for page in range(1, _MAX_INDEX_PAGES + 1):
            doc = self._ensure(
                index_path(self.raw_dir, season, page),
                f"index/{season}/page-{page}",
                lambda season=season, page=page: {
                    "season": season,
                    "page": page,
                    "entries": self.scraper.fetch_index_page(season, page),
                },
                state,
                force=force,
            )
            if doc is None:
                break
            entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict)]
            fresh = [e for e in entries if e.get("tournament_id") not in state.seen_tournaments]
            for entry in entries:
                tid = entry.get("tournament_id")
                if tid in state.seen_tournaments:
                    continue
                if isinstance(tid, str):
                    state.seen_tournaments.add(tid)
                self._process_entry(entry, state, force=force)
            if len(entries) < INDEX_PAGE_SIZE or not fresh:
                break  # 未满页 = 赛季抓全；满页但无新 id = page 参数被忽略（兜底终止）

    # ---- 单场赛事 ----

    def _process_entry(self, entry: dict[str, Any], state: _State, *, force: bool) -> None:
        tid = entry.get("tournament_id")
        day = _parse_day(entry.get("date"))
        if not isinstance(tid, str) or day is None:
            state.stats.question.append(
                {"id": str(tid), "endpoint": "/tournaments",
                 "reason": "索引条目缺 tournament_id/date 字段或日期不可解析"}
            )
            return
        if state.limit_reached:
            return
        if day < state.window_from or day > state.window_to:
            state.out_of_window += 1  # 窗口外：只计数，不记取舍细节
            return
        name = entry.get("name")
        players = entry.get("players")
        tier, reason = classify_site_tournament(name, players, entry.get("country"))
        accepted = tier is not None
        # 取舍决策逐场记录（验收：采集报告列明每场赛事归类与取舍）
        state.stats.scraped.append(
            {"id": tid, "action": "accepted" if accepted else "rejected",
             "name": name, "tier": tier, "reason": reason,
             "players": players, "date": day.isoformat()}
        )
        if not accepted:
            return
        state.stats.total += 1
        state.accepted += 1
        if state.max_tournaments is not None and state.accepted >= state.max_tournaments:
            state.limit_reached = True
        state.expected.append(("standings", tid, standings_path(self.raw_dir, tid)))
        standings_doc = self._ensure(
            standings_path(self.raw_dir, tid),
            f"standings/{tid}",
            lambda tid=tid: self.scraper.fetch_standings(tid),
            state,
            force=force,
        )
        for did in _decklist_ids(standings_doc):
            state.expected.append(("decklist", did, decklist_path(self.raw_dir, did)))
            self._ensure(
                decklist_path(self.raw_dir, did),
                f"decks/list/{did}",
                lambda did=did: self.scraper.fetch_decklist(did),
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
        """保证 path 的 raw 可用；存在且 hash 有效即跳过（零请求）。返回 raw 文档。

        主站落盘口径 = 解析后 JSON 快照（payload 直接为 dict，不包 "data"）。
        """
        if not force and is_valid_raw(path):
            state.stats.scraped.append({"id": label, "path": str(path), "action": "skipped"})
            return read_raw(path)
        try:
            payload = fetch()
        except LimitlessSiteApiError as exc:
            state.stats.question.append(
                {"id": label, "endpoint": exc.endpoint, "reason": str(exc)}
            )
            return None
        write_raw(path, payload, source=SOURCE, force=force)
        state.stats.scraped.append({"id": label, "path": str(path), "action": "fetched"})
        return read_raw(path)

    # ---- 对账 ----

    def _reconcile_missing(self, state: _State) -> None:
        """本轮 accepted 赛事的 standings/decklist 应有未有（缺失/hash 无效）进 missing。"""
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
    """一轮运行的可变状态（统计 + 窗口 + 断点续传上下文）。"""

    def __init__(
        self,
        stats: RunStats,
        window_from: date,
        window_to: date,
        max_tournaments: int | None,
    ) -> None:
        self.stats = stats
        self.window_from = window_from
        self.window_to = window_to
        self.max_tournaments = max_tournaments
        self.accepted = 0
        self.out_of_window = 0
        self.limit_reached = False
        self.seen_tournaments: set[str] = set()
        self.expected: list[tuple[str, str, Path]] = []


def _to_date(value: date | str | None) -> date | None:
    """CLI 传 YYYY-MM-DD 字符串，runner 内部统一为 date。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_day(raw: Any) -> date | None:
    """索引 date 字段（ISO "2026-06-10"，解析器已归一）→ date。"""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _decklist_ids(standings_doc: dict[str, Any] | None) -> list[str]:
    """standings raw 文档 → 去重保序的 decklist_id 列表（同表多人共用只抓一次；
    未交表选手 decklist_id=None 跳过）。"""
    if not standings_doc:
        return []
    rows = standings_doc.get("standings")
    if not isinstance(rows, list):
        return []
    seen: set[str] = set()
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        did = row.get("decklist_id")
        if isinstance(did, str) and did not in seen:
            seen.add(did)
            ids.append(did)
    return ids

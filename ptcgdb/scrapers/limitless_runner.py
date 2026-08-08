"""Limitless 赛事采集运行器（task 028，FR-9.1a M9-3 EN 对齐窗口接入）。

链路：tournaments 清单翻页（日期降序）→ 对齐窗口过滤 → classify_tournament 归类
→ accepted 赛事抓 standings + pairings，全部落 raw（append-only：raw 文件存在且
hash 有效即跳过，零请求断点续传；force=True 重抓）。三清单 + scrape_runs 复用
runner.finish_run。

取舍决策逐场记入 stats.scraped（action="accepted"/"rejected"，附 name/tier/
reason/players/date）——采集报告须列明每场赛事归类与取舍；窗口外赛事只计数不记
细节。stats.total = accepted 场数。

熔断（CircuitOpenError）立即中止本轮，已抓产物保留，status=aborted。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from ptcgdb.normalize.envs import alignment_window
from ptcgdb.scrapers.http import CircuitOpenError
from ptcgdb.scrapers.limitless import (
    ENDPOINT_TOURNAMENTS,
    SOURCE,
    LimitlessApiError,
    LimitlessScraper,
    classify_tournament,
    pairings_path,
    standings_path,
    tournament_list_path,
)
from ptcgdb.scrapers.raw_store import is_valid_raw, read_raw, write_raw
from ptcgdb.scrapers.runner import (
    RunResult,
    RunStats,
    _new_run_id,
    finish_run,
)


class LimitlessScrapeRunner:
    """Limitless 赛事链路抓取组织；scraper 鸭子类型注入（测试用假 scraper）。"""

    def __init__(
        self,
        raw_dir: Path,
        scraper: LimitlessScraper,
        db_path: Path | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.scraper = scraper
        self.db_path = Path(db_path) if db_path else None

    def scrape(
        self,
        *,
        date_from: date | str | None = None,
        date_to: date | str | None = None,
        max_tournaments: int | None = None,
        force: bool = False,
    ) -> RunResult:
        """抓对齐窗口内的 EN 赛事。显式 date_from/date_to 优先，缺省 = alignment_window()。

        max_tournaments 截断 accepted 场数（调试/小样用）。
        """
        run_id, started_at = _new_run_id()
        stats = RunStats()
        default_from, default_to = alignment_window()
        window_from = _to_date(date_from) or default_from
        window_to = _to_date(date_to) or default_to
        state = _State(stats, window_from, window_to, max_tournaments)
        try:
            self._scrape_pages(state, force=force)
        except CircuitOpenError:
            stats.aborted = True

        self._reconcile_missing(state)
        return finish_run(self.raw_dir, self.db_path, run_id, started_at, stats)

    # ---- 清单翻页 ----

    def _scrape_pages(self, state: _State, *, force: bool) -> None:
        """清单按日期降序翻页：空页 → 停；页内最旧赛事早于窗口 → 处理完本页后停。"""
        page = 1
        while True:
            path = tournament_list_path(self.raw_dir, page)
            doc = self._ensure(
                path,
                f"tournaments/page-{page}",
                lambda page=page: self.scraper.fetch_tournaments_page(page),
                state,
                force=force,
            )
            if doc is None:
                break
            items = _list_entries(doc)
            if not items:
                break
            oldest = self._process_page(items, state, force=force)
            if state.limit_reached:
                break
            if oldest is not None and oldest < state.window_from:
                break  # 列表日期降序：本页之后全部早于窗口
            page += 1

    def _process_page(
        self, items: list[dict[str, Any]], state: _State, *, force: bool
    ) -> date | None:
        """处理一页赛事条目，返回本页最旧赛事日期（翻页终止判据）。"""
        oldest: date | None = None
        for item in items:
            day = _parse_day(item.get("date"))
            tid = item.get("id")
            if day is None or not isinstance(tid, str):
                state.stats.question.append(
                    {"id": str(tid), "endpoint": ENDPOINT_TOURNAMENTS,
                     "reason": "赛事条目缺 id/date 字段或日期不可解析"}
                )
                continue
            if oldest is None or day < oldest:
                oldest = day
            if state.limit_reached:
                continue
            if day < state.window_from or day > state.window_to:
                state.out_of_window += 1  # 窗口外：只计数，不记取舍细节
                continue
            self._process_tournament(tid, item, day, state, force=force)
        return oldest

    # ---- 单场赛事 ----

    def _process_tournament(
        self,
        tid: str,
        item: dict[str, Any],
        day: date,
        state: _State,
        *,
        force: bool,
    ) -> None:
        name = item.get("name")
        players = item.get("players")
        tier, reason = classify_tournament(name, players)
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
        for kind, path in (
            ("standings", standings_path(self.raw_dir, tid)),
            ("pairings", pairings_path(self.raw_dir, tid)),
        ):
            state.expected.append((kind, tid, path))
        self._ensure(
            standings_path(self.raw_dir, tid),
            f"standings/{tid}",
            lambda: self.scraper.fetch_standings(tid),
            state,
            force=force,
        )
        self._ensure(
            pairings_path(self.raw_dir, tid),
            f"pairings/{tid}",
            lambda: self.scraper.fetch_pairings(tid),
            state,
            force=force,
        )

    # ---- 单文件抓取（断点续传）----

    def _ensure(
        self,
        path: Path,
        label: str,
        fetch: Callable[[], list[dict[str, Any]]],
        state: _State,
        *,
        force: bool,
    ) -> dict[str, Any] | None:
        """保证 path 的 raw 可用；存在且 hash 有效即跳过（零请求）。返回 raw 文档。

        Limitless 响应为裸数组，落盘前包装为 {"data": [...]}（write_raw 要求映射）。
        """
        if not force and is_valid_raw(path):
            state.stats.scraped.append({"id": label, "path": str(path), "action": "skipped"})
            return read_raw(path)
        try:
            items = fetch()
        except LimitlessApiError as exc:
            state.stats.question.append(
                {"id": label, "endpoint": exc.endpoint, "reason": str(exc)}
            )
            return None
        write_raw(path, {"data": items}, source=SOURCE, force=force)
        state.stats.scraped.append({"id": label, "path": str(path), "action": "fetched"})
        return read_raw(path)

    # ---- 对账 ----

    def _reconcile_missing(self, state: _State) -> None:
        """本轮 accepted 赛事的 standings/pairings 应有未有（缺失/hash 无效）进 missing。"""
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
        self.expected: list[tuple[str, str, Path]] = []


def _to_date(value: date | str | None) -> date | None:
    """CLI 传 YYYY-MM-DD 字符串，runner 内部统一为 date。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_day(raw: Any) -> date | None:
    """Limitless date 字段（UTC ISO，如 "2026-08-08T02:10:00.000Z"）→ 日期部分。"""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _list_entries(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """raw 文档 {"data": [...]} → 赛事条目列表（裸数组落盘时的包装）。"""
    entries = doc.get("data")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]

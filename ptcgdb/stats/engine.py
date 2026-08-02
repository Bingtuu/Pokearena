"""stats 执行层（PRD FR-9.6/FR-9.7，task 029）：canonical SQL 的参数组装与执行。

公式只在 `ptcgdb/stats/sql/*.sql`（单一事实源）；本模块只做：
窗口解析（--window-days → date_from/date_to）、命名参数绑定、layer auto 探测、
结果包装为 frozen CardStat / CardDrilldown、meta 回显（as_of/窗口/口径/词表 hash）。

CLI、SDK（SQLite 与 JSONL 双后端）共用本模块——JSONL 后端把导出件灌入内存
SQLite 并建同名视图后，跑的是同一批 canonical SQL 文件。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ptcgdb.schemas.models import CardDrilldown, CardStat

SQL_DIR = Path(__file__).parent / "sql"

DEFAULT_SCOPE = ("pokemon", "supporter", "stadium")


@dataclass(frozen=True)
class StatsParams:
    """三指标公共参数（默认值 = PRD FR-9.7 默认口径：master、排除 qual/team）。"""

    as_of: str
    date_from: str
    date_to: str
    scope: tuple[str, ...] = DEFAULT_SCOPE
    division: str | None = "master"
    tiers: tuple[str, ...] | None = None
    include_qual: bool = False
    include_team: bool = False
    usage_basis: str = "decks"  # decks / copies
    min_n: int = 5
    mirror: str = "exclude"  # 无 pairings 表（task 028 后置），仅回显口径标签
    k_a: float = 20.0
    k_b: float = 10.0


def resolve_window(
    as_of: str | None,
    date_from: str | None,
    date_to: str | None,
    window_days: int | None,
    **kwargs: Any,
) -> StatsParams:
    """CLI/SDK 窗口参数 → StatsParams。

    优先级：显式 date_from/date_to > window_days（相对 as_of 回推）> 默认 90 天滚动窗。
    as_of 缺省 = 今天。
    """
    as_of = as_of or date.today().isoformat()
    if date_to is None:
        date_to = as_of
    if date_from is None:
        days = window_days if window_days is not None else 90
        date_from = (date.fromisoformat(date_to) - timedelta(days=days)).isoformat()
    return StatsParams(as_of=as_of, date_from=date_from, date_to=date_to, **kwargs)


def _connect(db: str | Path | sqlite3.Connection) -> tuple[sqlite3.Connection, bool]:
    """接受 db 路径或已有连接（JSONL 内存库）；返回 (conn, 是否由本函数打开)。"""
    if isinstance(db, sqlite3.Connection):
        return db, False
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    return conn, True


def _binds(params: StatsParams) -> dict[str, Any]:
    return {
        "as_of": params.as_of,
        "date_from": params.date_from,
        "date_to": params.date_to,
        "scope": ",".join(params.scope),
        "division": params.division,
        "tiers": ",".join(params.tiers) if params.tiers else None,
        "include_qual": 1 if params.include_qual else 0,
        "include_team": 1 if params.include_team else 0,
        "usage_basis": params.usage_basis,
        "k_a": params.k_a,
        "k_b": params.k_b,
    }


def _load_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _base_meta(
    conn: sqlite3.Connection, params: StatsParams, *, require_topcut: bool = False
) -> dict[str, Any]:
    """meta 回显（FR-9.6）。n_tournaments = 该指标实际参与的赛事数：
    B 层（require_topcut=True）不计 topcut_slots 为 NULL 的赛事（与 canonical SQL 一致）。"""
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    n_tournaments = conn.execute(
        "SELECT count(*) FROM v_tournament_weights "
        "WHERE date BETWEEN ? AND ? "
        "AND (? IS NULL OR division = ?) "
        "AND (? = 1 OR is_qual = 0) AND (? = 1 OR is_team = 0) "
        "AND (? IS NULL OR INSTR(',' || ? || ',', ',' || tier || ',') > 0) "
        "AND static_weight IS NOT NULL "
        "AND (? = 0 OR topcut_slots IS NOT NULL)",
        (
            params.date_from,
            params.date_to,
            params.division,
            params.division,
            1 if params.include_qual else 0,
            1 if params.include_team else 0,
            ",".join(params.tiers) if params.tiers else None,
            ",".join(params.tiers) if params.tiers else None,
            1 if require_topcut else 0,
        ),
    ).fetchone()[0]
    return {
        "as_of": params.as_of,
        "date_from": params.date_from,
        "date_to": params.date_to,
        "scope": list(params.scope),
        "division": params.division,
        "tiers": list(params.tiers) if params.tiers else None,
        "include_qual": params.include_qual,
        "include_team": params.include_team,
        "min_n": params.min_n,
        "n_tournaments": n_tournaments,
        "name_group_rules_hash": meta.get("name_group_rules_hash"),
        "tournament_tiers_hash": meta.get("tournament_tiers_hash"),
    }


def _to_card_stats(
    rows: list[tuple], params: StatsParams, *, basis: str = "", layer: str = ""
) -> list[CardStat]:
    return [
        CardStat(
            group_key=r[0],
            display_name=r[1],
            value=r[2],
            n=r[3],
            basis=basis,
            layer=layer,
            low_confidence=r[3] < params.min_n,
        )
        for r in rows
    ]


def usage(
    db: str | Path | sqlite3.Connection, params: StatsParams
) -> tuple[list[CardStat], dict[str, Any]]:
    """WUR 加权出场率（canonical: wur.sql）。"""
    conn, owned = _connect(db)
    try:
        rows = conn.execute(_load_sql("wur.sql"), _binds(params)).fetchall()
        meta = _base_meta(conn, params)
    finally:
        if owned:
            conn.close()
    meta["usage_basis"] = params.usage_basis
    return _to_card_stats(rows, params, basis=params.usage_basis), meta


def _resolve_layer(conn: sqlite3.Connection, params: StatsParams, layer: str) -> str:
    """layer='auto'：窗口内存在 record 逐局战绩 → A 层，否则 B 层。"""
    if layer in ("a", "b"):
        return layer
    if layer != "auto":
        raise ValueError(f"layer 必须是 auto/a/b：{layer!r}")
    row = conn.execute(
        "SELECT 1 FROM deck_appearances a "
        "JOIN decks d ON d.deck_id = a.deck_id AND d.mapping_status = 'full' "
        "JOIN v_tournament_weights t ON t.tournament_id = a.tournament_id "
        "WHERE a.record_wins IS NOT NULL "
        "AND t.date BETWEEN ? AND ? "
        "AND (? IS NULL OR t.division = ?) "
        "AND (? = 1 OR t.is_qual = 0) AND (? = 1 OR t.is_team = 0) "
        "AND (? IS NULL OR INSTR(',' || ? || ',', ',' || t.tier || ',') > 0) "
        "AND t.static_weight IS NOT NULL LIMIT 1",
        (
            params.date_from,
            params.date_to,
            params.division,
            params.division,
            1 if params.include_qual else 0,
            1 if params.include_team else 0,
            ",".join(params.tiers) if params.tiers else None,
            ",".join(params.tiers) if params.tiers else None,
        ),
    ).fetchone()
    return "a" if row else "b"


def winrate(
    db: str | Path | sqlite3.Connection, params: StatsParams, layer: str = "auto"
) -> tuple[list[CardStat], dict[str, Any]]:
    """WR 胜率（canonical: winrate_a.sql / winrate_b.sql；layer 可 auto）。"""
    conn, owned = _connect(db)
    try:
        resolved = _resolve_layer(conn, params, layer)
        rows = conn.execute(
            _load_sql(f"winrate_{resolved}.sql"), _binds(params)
        ).fetchall()
        meta = _base_meta(conn, params, require_topcut=(resolved == "b"))
    finally:
        if owned:
            conn.close()
    meta["layer"] = resolved
    meta["mirror"] = params.mirror  # 无 pairings 表，参数仅回显（task 028 后置）
    if resolved == "b" and rows:
        meta["q0"] = rows[0][4]  # q0 常数列（每行同值）
    return _to_card_stats(rows, params, layer=resolved), meta


def wws(
    db: str | Path | sqlite3.Connection, params: StatsParams, layer: str = "auto"
) -> tuple[list[CardStat], dict[str, Any]]:
    """WWS 加权胜率（canonical: wws.sql；贝叶斯收缩 :k_a/:k_b）。"""
    conn, owned = _connect(db)
    try:
        resolved = _resolve_layer(conn, params, layer)
        rows = conn.execute(
            _load_sql("wws.sql"), {**_binds(params), "layer": resolved}
        ).fetchall()
        meta = _base_meta(conn, params, require_topcut=(resolved == "b"))
    finally:
        if owned:
            conn.close()
    meta["layer"] = resolved
    meta["k_a"] = params.k_a
    meta["k_b"] = params.k_b
    return _to_card_stats(rows, params, layer=resolved), meta


def card_drilldown(
    db: str | Path | sqlite3.Connection, group_key: str, params: StatsParams
) -> tuple[list[CardDrilldown], dict[str, Any]]:
    """单卡逐赛事钻取（canonical: card_drilldown.sql）。"""
    conn, owned = _connect(db)
    try:
        rows = conn.execute(
            _load_sql("card_drilldown.sql"), {**_binds(params), "group_key": group_key}
        ).fetchall()
        meta = _base_meta(conn, params)
    finally:
        if owned:
            conn.close()
    meta["group_key"] = group_key
    return [
        CardDrilldown(
            tournament_id=r[0],
            tournament_name=r[1],
            date=r[2],
            tier=r[3],
            n_decks=r[4],
            weighted_carry=r[5],
            topcut_decks=r[6],
            best_rank=r[7],
        )
        for r in rows
    ], meta

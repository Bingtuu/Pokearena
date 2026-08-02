"""stats / query CLI（PRD FR-9.7，task 029）。

`ptcgdb stats` 子命令组：overview（裸调用兼容）/ usage / winrate / wws / card；
`ptcgdb query`：只读 ad-hoc SQL（mode=ro，仅 SELECT/WITH）。
输出统一三格式：table（人读，meta 以 # 行回显）/ json（全精度 + meta）/ csv（数据行）。
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any

import typer

from ptcgdb.schemas.models import CardStat
from ptcgdb.stats.caliber import write_caliber_hashes
from ptcgdb.stats.engine import (
    StatsParams,
    card_drilldown,
    resolve_window,
    usage,
    winrate,
    wws,
)

DEFAULT_DB_PATH = Path("data/ptcg-cn.db")

stats_app = typer.Typer(help="赛事统计（FR-9.7）：usage / winrate / wws / card / overview")

DbPathOpt = Annotated[Path, typer.Option("--db-path", help="数据库路径")]
FmtOpt = Annotated[str, typer.Option("--format", help="输出格式 table|json|csv")]
AsOfOpt = Annotated[str | None, typer.Option("--as-of", help="查询时点（时间衰减基准）")]
FromOpt = Annotated[str | None, typer.Option("--from", help="窗口起点（含）")]
ToOpt = Annotated[str | None, typer.Option("--to", help="窗口终点（含，缺省=as-of）")]
WindowDaysOpt = Annotated[int | None, typer.Option("--window-days", help="滚动窗口天数")]
ScopeOpt = Annotated[
    str, typer.Option("--scope", help="统计范围（逗号分隔 pokemon,supporter,stadium）")
]
TierOpt = Annotated[str | None, typer.Option("--tier", help="tier 过滤（逗号分隔）")]
DivisionOpt = Annotated[str, typer.Option("--division", help="组别（空串=全部）")]
MinNOpt = Annotated[int, typer.Option("--min-n", help="low_confidence 样本量阈值")]
IncludeQualOpt = Annotated[bool, typer.Option("--include-qual", help="计入预赛场次")]
IncludeTeamOpt = Annotated[bool, typer.Option("--include-team", help="计入团队赛场次")]


def _params(
    as_of: str | None,
    date_from: str | None,
    date_to: str | None,
    window_days: int | None,
    scope: str,
    tier: str | None,
    division: str,
    min_n: int,
    include_qual: bool,
    include_team: bool,
    **kwargs: Any,
) -> StatsParams:
    return resolve_window(
        as_of,
        date_from,
        date_to,
        window_days,
        scope=tuple(s.strip() for s in scope.split(",") if s.strip()),
        division=division or None,
        tiers=tuple(t.strip() for t in tier.split(",") if t.strip()) if tier else None,
        min_n=min_n,
        include_qual=include_qual,
        include_team=include_team,
        **kwargs,
    )


def _emit(meta: dict[str, Any], rows: list[dict[str, Any]], fmt: str) -> None:
    if fmt == "json":
        typer.echo(json.dumps({"meta": meta, "data": rows}, ensure_ascii=False, indent=2))
    elif fmt == "csv":
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        typer.echo(buf.getvalue().rstrip("\n"))
    else:  # table
        for k, v in meta.items():
            typer.echo(f"# {k}: {v}")
        if not rows:
            typer.echo("(no rows)")
            return
        cols = list(rows[0].keys())
        widths = [max(len(c), *(len(str(r[c])) for r in rows)) for c in cols]
        typer.echo("  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)))
        for r in rows:
            typer.echo(
                "  ".join(
                    (f"{v:.4f}" if isinstance(v, float) else str(v)).ljust(w)
                    for v, w in zip((r[c] for c in cols), widths, strict=True)
                )
            )


def _emit_stats(meta: dict[str, Any], stats: list[CardStat], fmt: str) -> None:
    _emit(meta, [s.model_dump(mode="json") for s in stats], fmt)


def _overview(db_path: Path) -> None:
    """原对账行为：各赛制标记/卡类型卡数 + 系列 expected vs 实际。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        total = conn.execute(
            "SELECT count(*) FROM cards WHERE status='active'"
        ).fetchone()[0]
        by_type = conn.execute(
            "SELECT card_type, count(*) FROM cards WHERE status='active' "
            "GROUP BY card_type ORDER BY 2 DESC"
        ).fetchall()
        by_mark = conn.execute(
            "SELECT regulation_mark, count(*) FROM cards WHERE status='active' "
            "GROUP BY regulation_mark ORDER BY 1"
        ).fetchall()
        mismatch = conn.execute(
            "SELECT s.set_id, s.expected_count, count(c.card_id) FROM sets s "
            "LEFT JOIN cards c ON c.set_id = s.set_id AND c.status = 'active' "
            "GROUP BY s.set_id "
            "HAVING s.expected_count IS NOT NULL AND s.expected_count != count(c.card_id)"
        ).fetchall()
        tours = conn.execute("SELECT count(*) FROM tournaments").fetchone()[0]
        decks = conn.execute("SELECT count(*) FROM decks").fetchone()[0]
        appearances = conn.execute("SELECT count(*) FROM deck_appearances").fetchone()[0]
    finally:
        conn.close()
    typer.echo(f"cards: {total} active（" + ", ".join(f"{t}={n}" for t, n in by_type) + "）")
    typer.echo("regulation_mark: " + ", ".join(f"{m}={n}" for m, n in by_mark))
    typer.echo(f"sets expected 对账：{len(mismatch)} 个不一致")
    for sid, exp, act in mismatch:
        typer.echo(f"  ✗ {sid}: expected={exp} actual={act}")
    typer.echo(f"tournaments: {tours}  decks: {decks}  appearances: {appearances}")


@stats_app.callback(invoke_without_command=True)
def _stats_main(ctx: typer.Context, db_path: DbPathOpt = DEFAULT_DB_PATH) -> None:
    """裸 `ptcgdb stats` = overview（兼容旧对账行为）。"""
    if ctx.invoked_subcommand is None:
        _overview(db_path)


@stats_app.command()
def overview(db_path: DbPathOpt = DEFAULT_DB_PATH) -> None:
    """各赛制标记/卡类型卡数对账（原 stats 行为）。"""
    _overview(db_path)


@stats_app.command("usage")
def usage_cmd(
    as_of: AsOfOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    window_days: WindowDaysOpt = None,
    scope: ScopeOpt = "pokemon,supporter,stadium",
    tier: TierOpt = None,
    division: DivisionOpt = "master",
    usage_basis: Annotated[str, typer.Option("--usage-basis", help="decks|copies")] = "decks",
    min_n: MinNOpt = 5,
    include_qual: IncludeQualOpt = False,
    include_team: IncludeTeamOpt = False,
    fmt: FmtOpt = "table",
    db_path: DbPathOpt = DEFAULT_DB_PATH,
) -> None:
    """加权出场率 WUR（canonical: wur.sql）。"""
    params = _params(
        as_of, date_from, date_to, window_days, scope, tier, division, min_n,
        include_qual, include_team, usage_basis=usage_basis,
    )
    stats, meta = usage(db_path, params)
    _emit_stats(meta, stats, fmt)


@stats_app.command("winrate")
def winrate_cmd(
    as_of: AsOfOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    window_days: WindowDaysOpt = None,
    scope: ScopeOpt = "pokemon,supporter,stadium",
    tier: TierOpt = None,
    division: DivisionOpt = "master",
    layer: Annotated[str, typer.Option("--layer", help="auto|a|b")] = "auto",
    mirror: Annotated[
        str, typer.Option("--mirror", help="exclude|include（口径标签）")
    ] = "exclude",
    min_n: MinNOpt = 5,
    include_qual: IncludeQualOpt = False,
    include_team: IncludeTeamOpt = False,
    fmt: FmtOpt = "table",
    db_path: DbPathOpt = DEFAULT_DB_PATH,
) -> None:
    """胜率 WR（canonical: winrate_a/b.sql；A 层真实战绩 / B 层 top-cut 转化代理）。"""
    params = _params(
        as_of, date_from, date_to, window_days, scope, tier, division, min_n,
        include_qual, include_team, mirror=mirror,
    )
    stats, meta = winrate(db_path, params, layer=layer)
    _emit_stats(meta, stats, fmt)


@stats_app.command("wws")
def wws_cmd(
    as_of: AsOfOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    window_days: WindowDaysOpt = None,
    scope: ScopeOpt = "pokemon,supporter,stadium",
    tier: TierOpt = None,
    division: DivisionOpt = "master",
    layer: Annotated[str, typer.Option("--layer", help="auto|a|b")] = "auto",
    k_a: Annotated[float, typer.Option("--k-a", help="A 层等效局数收缩")] = 20.0,
    k_b: Annotated[float, typer.Option("--k-b", help="B 层等效卡组收缩")] = 10.0,
    min_n: MinNOpt = 5,
    include_qual: IncludeQualOpt = False,
    include_team: IncludeTeamOpt = False,
    fmt: FmtOpt = "table",
    db_path: DbPathOpt = DEFAULT_DB_PATH,
) -> None:
    """加权胜率 WWS = WUR × 贝叶斯收缩胜率（canonical: wws.sql）。"""
    params = _params(
        as_of, date_from, date_to, window_days, scope, tier, division, min_n,
        include_qual, include_team, k_a=k_a, k_b=k_b,
    )
    stats, meta = wws(db_path, params, layer=layer)
    _emit_stats(meta, stats, fmt)


@stats_app.command("card")
def card_cmd(
    name: Annotated[str, typer.Argument(help="卡名（name_group 归组 key）")],
    as_of: AsOfOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    window_days: WindowDaysOpt = None,
    scope: ScopeOpt = "pokemon,supporter,stadium",
    tier: TierOpt = None,
    division: DivisionOpt = "master",
    include_qual: IncludeQualOpt = False,
    include_team: IncludeTeamOpt = False,
    fmt: FmtOpt = "table",
    db_path: DbPathOpt = DEFAULT_DB_PATH,
) -> None:
    """单卡逐赛事钻取（canonical: card_drilldown.sql）。"""
    params = _params(
        as_of, date_from, date_to, window_days, scope, tier, division, 5,
        include_qual, include_team,
    )
    rows, meta = card_drilldown(db_path, name, params)
    _emit(meta, [r.model_dump(mode="json") for r in rows], fmt)


def _check_readonly_sql(sql: str) -> str:
    """仅放行单条 SELECT/WITH；其余（含 ATTACH/多语句）拒绝。"""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise typer.BadParameter("空 SQL")
    # 跳过前导注释取首关键字
    text = stripped
    while text.startswith("--") or text.startswith("/*"):
        if text.startswith("--"):
            nl = text.find("\n")
            text = text[nl + 1 :].lstrip() if nl >= 0 else ""
        else:
            end = text.find("*/")
            if end < 0:
                raise typer.BadParameter("未闭合注释")
            text = text[end + 2 :].lstrip()
    first = text.split(None, 1)[0].upper() if text else ""
    if first not in ("SELECT", "WITH"):
        raise typer.BadParameter(f"ptcgdb query 只读：仅放行 SELECT/WITH（得到 {first!r}）")
    if ";" in stripped:
        raise typer.BadParameter("ptcgdb query 只执行单条语句")
    return stripped


def query_cmd(
    sql: Annotated[str, typer.Argument(help="SELECT/WITH 语句")],
    fmt: FmtOpt = "table",
    limit: Annotated[int, typer.Option("--limit", help="最多返回行数")] = 500,
    db_path: DbPathOpt = DEFAULT_DB_PATH,
) -> None:
    """只读 ad-hoc SQL（FR-9.7）：mode=ro 打开，仅 SELECT/WITH，默认 LIMIT 500。"""
    checked = _check_readonly_sql(sql)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(checked)
        cols = [d[0] for d in cur.description]
        fetched = cur.fetchmany(limit + 1)
    finally:
        conn.close()
    truncated = len(fetched) > limit
    rows = [dict(zip(cols, r, strict=True)) for r in fetched[:limit]]
    _emit({"truncated": truncated, "limit": limit}, rows, fmt)


def init_db_with_caliber(db_path: Path) -> int:
    """init-db 实现：迁移 + 口径 hash 入 meta（FR-9.6），返回 user_version。"""
    from ptcgdb.migrations import apply_migrations

    version = apply_migrations(db_path)
    write_caliber_hashes(db_path)
    return version

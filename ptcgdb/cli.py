"""ptcgdb 命令行入口（typer）。"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ptcgdb.export.exporter import export_all
from ptcgdb.legal import legal_at, seed_snapshots
from ptcgdb.legal.versions import apply_snapshot
from ptcgdb.legal.versions import rollback as rollback_db
from ptcgdb.normalize import ingest_set
from ptcgdb.normalize.ingest_tourneys import ingest_tourneys
from ptcgdb.orm import Card, Set
from ptcgdb.scrapers import CircuitOpenError, HttpClient, MikMoeScraper, ScrapeRunner
from ptcgdb.scrapers.http import RateLimiter
from ptcgdb.scrapers.limitless import BASE_URL as LIMITLESS_BASE_URL
from ptcgdb.scrapers.limitless import DEFAULT_INTERVAL as LIMITLESS_INTERVAL
from ptcgdb.scrapers.limitless import LimitlessScraper
from ptcgdb.scrapers.limitless_runner import LimitlessScrapeRunner
from ptcgdb.scrapers.mikmoe import BASE_URL
from ptcgdb.scrapers.mikmoe_tournament import MikMoeTournamentScraper
from ptcgdb.scrapers.tournament_runner import TournamentScrapeRunner
from ptcgdb.stats.cli import init_db_with_caliber, query_cmd, stats_app
from ptcgdb.validate import run_validations, write_report

app = typer.Typer(help="简中 PTCG 标准环境卡牌数据库 CLI")
scrape_app = typer.Typer(help="数据采集（mik.moe 主源，限速 ≤1 次/2 秒）")
monitor_app = typer.Typer(help="监控管线（L0 新卡增量 / L1 赛制变更）")
app.add_typer(scrape_app, name="scrape")
app.add_typer(monitor_app, name="monitor")
app.add_typer(stats_app, name="stats")
app.command("query", help="只读 ad-hoc SQL（mode=ro，仅 SELECT/WITH，FR-9.7）")(query_cmd)

DEFAULT_DB_PATH = Path("data/ptcg-cn.db")
DEFAULT_RAW_DIR = Path("data/raw")


def _db_not_found_exit(db_path: Path) -> typer.Exit:
    typer.echo(f"错误：数据库不存在或无法打开：{db_path}", err=True)
    typer.echo("请先运行 ptcgdb init-db 初始化数据库", err=True)
    return typer.Exit(code=2)


@app.command("init-db")
def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """建库/迁移：执行全部未应用的迁移 + 口径 hash 入 meta（FR-9.6）。"""
    version = init_db_with_caliber(db_path)
    typer.echo(f"OK: {db_path} (user_version={version})")


@app.command()
def ingest(
    set_id: str = typer.Option(..., "--set", help="要入库的系列（setId，如 CSM1aC）"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """入库：raw → sets/cards（status=draft）。raw 层只读，重跑幂等。"""
    result = ingest_set(raw_dir, set_id, db_path)
    typer.echo(
        f"set={result.set_id} ingested={result.card_count} "
        f"skipped={len(result.skipped)} questions={len(result.questions)}"
    )
    for q in result.questions.items:
        typer.echo(f"  ? {q['card_id'] or '-'} {q['field']}: {q['value']!r} — {q['note']}")
    if result.skipped:
        typer.echo(f"有卡片未入库：{result.skipped}", err=True)
        raise typer.Exit(code=1)


@app.command()
def validate(
    set_id: str | None = typer.Option(None, "--set", help="只校验指定系列（setId）"),
    report: Annotated[
        Path | None, typer.Option("--report", help="报告输出路径，缺省自动生成")
    ] = None,
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """校验：跑 FR-2.3 六条规则并落 Markdown 报告；任一规则失败退出码非零。"""
    try:
        results = run_validations(db_path, set_id=set_id, raw_dir=raw_dir)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if report is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report = Path("reports") / f"validation-{ts}.md"
    write_report(results, report, db_path=db_path, raw_dir=raw_dir)
    for r in results:
        mark = "✓" if r.passed else "✗"
        typer.echo(f"{mark} {r.rule}: checked={r.checked} failures={len(r.failures)}")
    typer.echo(f"报告：{report}")
    if not all(r.passed for r in results):
        typer.echo("存在失败规则，已阻断", err=True)
        raise typer.Exit(code=1)


@app.command()
def activate(
    set_id: str | None = typer.Option(
        None, "--set", help="只激活指定系列（setId）；缺省逐系列处理全部"
    ),
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """激活：逐系列跑校验，全过才把该系列 cards.status draft→active；不过的保持 draft。"""
    engine = create_engine(f"sqlite:///{db_path}")
    blocked = False
    with Session(engine) as session:
        if set_id:
            if session.get(Set, set_id) is None:
                typer.echo(f"系列不存在: {set_id}", err=True)
                raise typer.Exit(code=1)
            set_ids = [set_id]
        else:
            set_ids = list(session.scalars(select(Set.set_id)))
        for sid in set_ids:
            results = run_validations(db_path, set_id=sid, raw_dir=raw_dir)
            bad = [r for r in results if not r.passed]
            if bad:
                blocked = True
                typer.echo(f"set={sid} 校验未过，保持 draft：")
                for r in bad:
                    typer.echo(f"  ✗ {r.rule}: {len(r.failures)} 项失败")
                    for f in r.failures[:5]:
                        target = f.get("card_id") or f.get("set_id") or f.get("card_ids")
                        typer.echo(f"    - {target} {f.get('field') or ''}: {f['note']}")
                continue
            updated = session.execute(
                update(Card)
                .where(Card.set_id == sid, Card.status == "draft")
                .values(status="active")
            ).rowcount
            session.commit()
            typer.echo(f"set={sid} 校验全过，activated={updated}")
    engine.dispose()
    if blocked:
        raise typer.Exit(code=1)


@app.command()
def search() -> None:
    """检索卡牌（未实现）。"""
    typer.echo("not implemented", err=True)
    raise typer.Exit(code=1)


@app.command()
def get() -> None:
    """按 card_id 点查（未实现）。"""
    typer.echo("not implemented", err=True)
    raise typer.Exit(code=1)


@app.command("legal-apply")
def legal_apply(
    proposal: Annotated[
        Path, typer.Option("--proposal", help="变更提案 yaml（FR-5.2 人工确认后）")
    ],
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """应用赛制变更提案：备份 → 关旧快照开新快照 → 版本递增 → CHANGELOG。

    成功后回写提案文件 status=applied（FR-5.2 闭环）。
    """
    try:
        sid = apply_snapshot(db_path, proposal)
    except (ValueError, LookupError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    from ptcgdb.monitor.proposals import mark_proposal_applied

    mark_proposal_applied(proposal, sid)
    typer.echo(f"OK: 新快照 {sid} 已生效（备份在 {db_path.parent / 'versions'}）")
    typer.echo(f"提案已标记 applied: {proposal}")


@app.command("legal-errata")
def legal_errata(
    config_dir: Path = Path("config/errata"),
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """L2 勘误导入：config/errata/*.yml → errata 表（upsert 幂等，FR-5.3）。"""
    from ptcgdb.legal.errata import import_errata

    result = import_errata(db_path, config_dir)
    typer.echo(f"OK: imported={len(result.imported)}: {', '.join(result.imported)}")
    for w in result.warnings:
        typer.echo(f"  ! {w}", err=True)
    if result.warnings and not result.imported:
        raise typer.Exit(code=1)


@app.command()
def accept(
    db_path: Path = DEFAULT_DB_PATH,
    out_dir: Path = Path("reports"),
    work_dir: Path = Path("data/accept-work"),
) -> None:
    """一键验收（PRD §10）：A1/A4/A5/A6/A7/A8 重跑 + 证据报告。真实库只读。"""
    from ptcgdb.accept.runner import run_acceptance

    report = run_acceptance(db_path, out_dir, work_dir)
    for s in report.sections:
        typer.echo(f"{s.aid} {'PASS' if s.passed else 'FAIL'} — {s.title}")
    typer.echo(f"报告: {report.path}")
    if not report.passed:
        typer.echo("存在 FAIL 项，详见报告（需人工裁决）", err=True)
        raise typer.Exit(code=1)


@app.command()
def sample(
    a2: bool = typer.Option(False, "--a2", help="只生成 A2 字段抽样清单（100 张）"),
    a3: bool = typer.Option(False, "--a3", help="只生成 A3 机制核对报告（自动校验 + 50 张清单）"),
    seed: int = typer.Option(20260801, "--seed", help="抽样种子（同 seed 可复现）"),
    db_path: Path = DEFAULT_DB_PATH,
    out_dir: Path = Path("reports"),
) -> None:
    """A2/A3 抽样比对工具：生成人工卡面比对清单（小程序无 API，比对需人工）。"""
    from ptcgdb.accept.sampling import write_a2_checklist, write_a3_report

    if not a2 and not a3:
        a2 = a3 = True
    if a2:
        path = write_a2_checklist(db_path, out_dir, seed=seed)
        typer.echo(f"A2 清单: {path}")
    if a3:
        path = write_a3_report(db_path, out_dir, seed=seed)
        typer.echo(f"A3 报告: {path}")


@app.command("map-en")
def map_en(
    db_path: Path = DEFAULT_DB_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    out_dir: Path = Path("reports"),
) -> None:
    """EN 映射填充：mik raw 英文桥 → name_en 核实 + external_ids(mik_en)（task 022）。"""
    from ptcgdb.mapping.en import fill_en
    from ptcgdb.mapping.report import write_en_report

    result = fill_en(db_path, raw_dir)
    path = write_en_report(result, out_dir)
    typer.echo(
        f"total={result.total} filled={result.filled} already={result.already} "
        f"no_bridge={len(result.no_bridge)}"
    )
    typer.echo(f"报告: {path}")


@app.command("map-tcgdex")
def map_tcgdex(
    fetch: bool = typer.Option(False, "--fetch", help="重新下载 TCGdex/ptcd 数据入 raw 层"),
    db_path: Path = DEFAULT_DB_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    out_dir: Path = Path("reports"),
) -> None:
    """TCGdex 接入：EN 桥 → TCGdex ID 解析 + zh-cn 系列壳对账（task 023）。"""
    from ptcgdb.mapping.report import write_tcgdex_report
    from ptcgdb.mapping.tcgdex import fetch_raw, reconcile_sets, resolve_en

    if fetch:
        written = fetch_raw(raw_dir, force=True)
        typer.echo(f"raw 更新: {', '.join(written)}")
    result = resolve_en(db_path, raw_dir)
    reconcile = reconcile_sets(db_path, raw_dir)
    path = write_tcgdex_report(result, reconcile, out_dir)
    typer.echo(
        f"mik_en={result.total} resolved={len(result.resolved)} "
        f"unmapped_set={sum(len(v) for v in result.unmapped_set.values())} "
        f"missing_card={len(result.missing_card)} "
        f"name_mismatch={len(result.name_mismatch)}"
    )
    typer.echo(f"报告: {path}")


@app.command("map-ja")
def map_ja(
    fetch: bool = typer.Option(False, "--fetch", help="下载 ptcd 卡数据 + PokéAPI 名表入 raw 层"),
    db_path: Path = DEFAULT_DB_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    out_dir: Path = Path("reports"),
) -> None:
    """JP 映射填充：dexId 链日文物种名 + 词表组合 name_ja + external_ids(tcgdex)（task 024）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from ptcgdb.mapping.ja import fetch_ja_raw, fill_ja
    from ptcgdb.mapping.report import write_ja_report
    from ptcgdb.orm import ExternalId

    if fetch:
        written = fetch_ja_raw(raw_dir)
        typer.echo(f"raw 更新: {len(written)} 个文件")
    result = fill_ja(db_path, raw_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        total_bridge = session.query(ExternalId).filter_by(system="mik_en").count()
    engine.dispose()
    path = write_ja_report(result, total_bridge, out_dir)
    typer.echo(
        f"mik_en={total_bridge} tcgdex_ids={result.external_ids_written} "
        f"name_ja={result.name_ja_filled} conflicts={len(result.conflicts)} "
        f"questions={sum(len(v) for v in result.questions.values())}"
    )
    for category in sorted(result.questions):
        typer.echo(f"  {category}: {len(result.questions[category])}")
    typer.echo(f"报告: {path}")


@app.command("map-tera")
def map_tera(
    db_path: Path = DEFAULT_DB_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    out_dir: Path = Path("reports"),
) -> None:
    """太晶识别：ptcd EN 卡 subtypes 'Tera' 印刷级富化 is_tera（task 030 F-03）。"""
    from ptcgdb.mapping.report import write_tera_report
    from ptcgdb.mapping.tera import fill_tera

    result = fill_tera(db_path, raw_dir)
    path = write_tera_report(result, out_dir)
    typer.echo(
        f"total={result.total} bridged={result.bridged} tera={result.tera} "
        f"non_tera={result.resolved_non_tera} no_bridge={len(result.no_bridge)} "
        f"unmapped_set={len(result.unmapped_set)} missing_card={len(result.missing_card)}"
    )
    typer.echo(f"报告: {path}")


@app.command("seed-face-totals")
def seed_face_totals(
    db_path: Path = DEFAULT_DB_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
) -> None:
    """卡面分母种子：生成/校验 config/set_card_face_totals.yml 并入 sets（task 030 F-01）。"""
    from ptcgdb.normalize import face_totals

    result = face_totals.generate_seed(db_path, raw_dir)
    path = face_totals.write_seed(result)
    applied = face_totals.apply_seed_to_sets(db_path)
    typer.echo(
        f"种子: total 型 {len(result.totals)} 套 / packs 型 {len(result.packs)} 套；"
        f"sets.card_face_total 播种 {applied} 套"
    )
    if result.conflicts:
        typer.echo(f"冲突（未播种 {len(result.conflicts)} 项）:")
        for c in result.conflicts:
            typer.echo(f"  - {c}")
    typer.echo(f"种子文件: {path}")


@app.command("mark-aliases")
def mark_aliases_cmd(db_path: Path = DEFAULT_DB_PATH) -> None:
    """mik 双重列示别名标记：字母编号能量 → 数字正本 alias_of（task 030 F-02）。"""
    from ptcgdb.normalize.aliases import mark_aliases

    result = mark_aliases(db_path)
    typer.echo(
        f"alias 标记 {len(result.marked)} 张 / 清除 {len(result.cleared)} 张 / "
        f"待裁决 {len(result.questions)} 张"
    )
    for card_id, reason in sorted(result.questions.items()):
        typer.echo(f"  - {card_id}: {reason}")


@app.command()
def rollback(db_path: Path = DEFAULT_DB_PATH) -> None:
    """回滚：用最新备份覆盖当前 DB（FR-6.3）。"""
    try:
        name = rollback_db(db_path)
    except LookupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"OK: 已回滚至备份 {name}")


@app.command("legal-seed")
def legal_seed(
    config_dir: Path = Path("config/legality"),
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """环境快照种子入库：config/legality/*.yml → legality_snapshots（upsert，幂等）。"""
    ids = seed_snapshots(db_path, config_dir)
    typer.echo(f"OK: seeded {len(ids)} snapshots: {', '.join(ids)}")


@app.command()
def legal(
    date_: str = typer.Option(..., "--date", help="查询日期 YYYY-MM-DD"),
    format_: str = typer.Option("standard", "--format", help="赛制（standard/open…）"),
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """合法性判定：输出指定日期+赛制的合法卡池规模与白名单命中组。"""
    from datetime import date as date_cls

    d = date_cls.fromisoformat(date_)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            try:
                pool = legal_at(session, d, format_)
            except LookupError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=1) from exc
    except OperationalError:
        raise _db_not_found_exit(db_path) from None
    finally:
        engine.dispose()
    typer.echo(
        f"snapshot={pool.snapshot_id} date={pool.date} format={pool.format} "
        f"legal_cards={len(pool.card_ids)}"
    )
    typer.echo(f"白名单命中 {len(pool.by_name_group)} 组：")
    for group, ids in pool.by_name_group.items():
        typer.echo(f"  {group}: {len(ids)} 张")


@app.command("deck-check")
def deck_check(
    file: Annotated[
        Path, typer.Option("--file", help="卡表 YAML（cards = card_id → 数量，PRD FR-8）"),
    ],
    date_: Annotated[
        str | None, typer.Option("--date", help="校验日期 YYYY-MM-DD（覆盖文件值，默认当天）"),
    ] = None,
    format_: Annotated[
        str | None, typer.Option("--format", help="赛制（覆盖文件值，默认 standard）"),
    ] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """FR-8 卡组校验：卡表 → DeckReport。ok 退出 0，有违规退出 1，输入/快照错误退出 2。"""
    from datetime import date as date_cls

    import yaml

    from ptcgdb.sdk import open_db

    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
            raise ValueError("卡表文件须含 cards 映射（card_id: 数量）")
        deck = [cid for cid, n in data["cards"].items() for _ in range(int(n))]
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        typer.echo(f"卡表文件错误: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    raw_date = date_ if date_ is not None else data.get("date")
    try:
        if raw_date is None:
            d = date_cls.today()
        elif isinstance(raw_date, date_cls):
            d = raw_date  # YAML 会把 YYYY-MM-DD 标量解析成 date
        else:
            d = date_cls.fromisoformat(str(raw_date))
    except ValueError as exc:
        typer.echo(f"日期格式错误: {raw_date}", err=True)
        raise typer.Exit(code=2) from exc
    fmt = format_ or data.get("format") or "standard"

    try:
        db = open_db(db_path)
    except Exception:
        raise _db_not_found_exit(db_path) from None
    try:
        report = db.validate_deck(deck, date=d, format=fmt)
    except OperationalError:
        raise _db_not_found_exit(db_path) from None
    except LookupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        db.close()
    typer.echo(
        f"snapshot={report.snapshot_id} date={report.date} format={report.format} "
        f"deck_size={report.deck_size} ok={report.ok}"
    )
    for v in report.violations:
        typer.echo(f"  [{v.kind}] {v.detail}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def export(
    out: Annotated[Path, typer.Option("--out", help="导出目录")] = Path("dist"),
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """导出七件套（FR-7）：manifest/cards/sets/relations/legality/db/checksums/schema.md。"""
    manifest = export_all(db_path, out)
    typer.echo(
        f"OK: {out}/ version={manifest['version']} "
        f"schema_version={manifest['schema_version']} counts={manifest['counts']}"
    )


def _run_scrape(kind: str, raw_dir: Path, db_path: Path, force: bool, set_id: str | None) -> None:
    try:
        with HttpClient(BASE_URL) as http:
            runner = ScrapeRunner(raw_dir, MikMoeScraper(http), db_path)
            if kind == "sets":
                result = runner.scrape_sets(force=force)
            else:
                result = runner.scrape_cards(
                    set_ids=[set_id] if set_id else None, force=force
                )
    except CircuitOpenError as exc:
        typer.echo(f"熔断中止：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    stats = result.stats
    fetched = sum(1 for r in stats.scraped if r["action"] == "fetched")
    skipped = sum(1 for r in stats.scraped if r["action"] == "skipped")
    typer.echo(
        f"run_id={result.run_id} status={'aborted' if stats.aborted else 'ok'} "
        f"fetched={fetched} skipped={skipped} question={len(stats.question)} "
        f"missing={len(stats.missing)} lists={result.lists_path}"
    )
    if stats.aborted:
        typer.echo("警告：本轮运行因熔断提前中止，已抓产物与清单已落盘", err=True)
        raise typer.Exit(code=1)


@scrape_app.command("sets")
def scrape_sets(
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    force: bool = typer.Option(False, "--force", help="忽略已有 raw 文件强制重抓"),
) -> None:
    """抓系列清单（product-list）+ 各系列详情（product-detail）。"""
    _run_scrape("sets", raw_dir, db_path, force, None)


@scrape_app.command("cards")
def scrape_cards(
    set_id: str | None = typer.Option(
        None, "--set", help="只抓指定系列（setId，如 CSM1aC）；缺省抓全部系列"
    ),
    force: bool = typer.Option(False, "--force", help="忽略已有 raw 文件强制重抓"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """抓单卡（card-detail）。断点续传：已抓且 hash 有效的卡自动跳过。"""
    _run_scrape("cards", raw_dir, db_path, force, set_id)


@scrape_app.command("tourneys")
def scrape_tourneys(
    series_id: str | None = typer.Option(
        None, "--series-id", help="只抓指定赛事系列（seriesId）；缺省抓全部系列"
    ),
    max_tournaments: int | None = typer.Option(
        None, "--max-tournaments", help="最多处理的赛事场数（调试/小样用）"
    ),
    top_n: int = typer.Option(
        64, "--top-n", help="rank-individual 页大小（默认 64 与 top64 对齐）"
    ),
    force: bool = typer.Option(False, "--force", help="忽略已有 raw 文件强制重抓"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """抓赛事链路：series-list → list → detail/rank(top64)/static → 各卡组 deck/detail。

    断点续传：raw 文件存在且 hash 有效即跳过（零请求）。限速由 HttpClient 保证。
    """
    try:
        with HttpClient(BASE_URL) as http:
            runner = TournamentScrapeRunner(
                raw_dir, MikMoeTournamentScraper(http), db_path
            )
            result = runner.scrape(
                series_id=series_id,
                max_tournaments=max_tournaments,
                top_n=top_n,
                force=force,
            )
    except CircuitOpenError as exc:
        typer.echo(f"熔断中止：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    stats = result.stats
    fetched = sum(1 for r in stats.scraped if r["action"] == "fetched")
    skipped = sum(1 for r in stats.scraped if r["action"] == "skipped")
    typer.echo(
        f"run_id={result.run_id} status={'aborted' if stats.aborted else 'ok'} "
        f"fetched={fetched} skipped={skipped} question={len(stats.question)} "
        f"missing={len(stats.missing)} lists={result.lists_path}"
    )
    if stats.aborted:
        typer.echo("警告：本轮运行因熔断提前中止，已抓产物与清单已落盘", err=True)
        raise typer.Exit(code=1)


@scrape_app.command("limitless")
def scrape_limitless(
    date_from: str | None = typer.Option(
        None, "--date-from", help="窗口起 YYYY-MM-DD（缺省 = EN 对齐窗口）"
    ),
    date_to: str | None = typer.Option(
        None, "--date-to", help="窗口止 YYYY-MM-DD（缺省 = EN 对齐窗口）"
    ),
    max_tournaments: int | None = typer.Option(
        None, "--max-tournaments", help="最多 accepted 的赛事场数（调试/小样用）"
    ),
    force: bool = typer.Option(False, "--force", help="忽略已有 raw 文件强制重抓"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """抓 Limitless EN 赛事：清单翻页 → 对齐窗口过滤 → accepted 抓 standings/pairings。

    窗口缺省 = EN 对齐窗口（成本先验 FR-9.1a，最终判据是卡级映射 full）。断点续传：
    raw 文件存在且 hash 有效即跳过（零请求）。限速 6.5s/请求（匿名额度 50 请求/5 分钟，
    FR-9.5 红线）。
    """
    try:
        with HttpClient(
            LIMITLESS_BASE_URL, rate_limiter=RateLimiter(interval=LIMITLESS_INTERVAL)
        ) as http:
            runner = LimitlessScrapeRunner(raw_dir, LimitlessScraper(http), db_path)
            result = runner.scrape(
                date_from=date_from,
                date_to=date_to,
                max_tournaments=max_tournaments,
                force=force,
            )
    except CircuitOpenError as exc:
        typer.echo(f"熔断中止：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"日期格式错误（YYYY-MM-DD）：{exc}", err=True)
        raise typer.Exit(code=2) from exc
    stats = result.stats
    accepted = sum(1 for r in stats.scraped if r["action"] == "accepted")
    rejected = sum(1 for r in stats.scraped if r["action"] == "rejected")
    fetched = sum(1 for r in stats.scraped if r["action"] == "fetched")
    skipped = sum(1 for r in stats.scraped if r["action"] == "skipped")
    typer.echo(
        f"run_id={result.run_id} status={'aborted' if stats.aborted else 'ok'} "
        f"accepted={accepted} rejected={rejected} fetched={fetched} skipped={skipped} "
        f"question={len(stats.question)} missing={len(stats.missing)} lists={result.lists_path}"
    )
    if stats.aborted:
        typer.echo("警告：本轮运行因熔断提前中止，已抓产物与清单已落盘", err=True)
        raise typer.Exit(code=1)


@app.command("ingest-tourneys")
def ingest_tourneys_cmd(
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """赛事入库：raw mikmoe/tournaments + decks → tournaments/decks/deck_cards。

    重跑幂等；count 合计 != 60 的卡组整组拦截（FR-9.6 质量门）并以非零码退出。
    """
    result = ingest_tourneys(raw_dir, db_path)
    typer.echo(
        f"tournaments={result.tournaments} decks={result.decks} appearances={result.appearances} "
        f"deck_cards={result.deck_cards} blocked={len(result.blocked)} "
        f"unknown_cards={len(result.unknown_cards)} warnings={len(result.warnings)}"
    )
    for b in result.blocked:
        typer.echo(f"  ✗ {b['deck_id']}: {b['reason']}")
    for u in result.unknown_cards[:20]:
        typer.echo(f"  ? 未解析卡 {u['deck_id']}: {u['raw_name']} ×{u['count']}")
    for w in result.warnings[:20]:
        typer.echo(f"  ? {w}")
    if result.blocked:
        typer.echo("有卡组被 60 张质量门拦截，详见上方清单", err=True)
        raise typer.Exit(code=1)


@app.command("ingest-limitless")
def ingest_limitless_cmd(
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Limitless 赛事入库：raw limitless/tournaments → tournaments/decks 四表（task 028）。

    decklist→简中映射 = ptcd 定位 → name_en exact match → env 优先/最新印刷裁决；
    重跑幂等；count 合计 != 60 的卡组整组拦截（FR-9.6 质量门）并以非零码退出。
    """
    from ptcgdb.normalize.ingest_limitless import ingest_limitless

    result = ingest_limitless(raw_dir, db_path)
    typer.echo(
        f"tournaments={result.tournaments} decks={result.decks} appearances={result.appearances} "
        f"deck_cards={result.deck_cards} blocked={len(result.blocked)} "
        f"unknown_cards={len(result.unknown_cards)} warnings={len(result.warnings)}"
    )
    typer.echo(f"映射决策分布: {dict(sorted(result.mapping_rules.items()))}")
    for b in result.blocked:
        typer.echo(f"  ✗ {b['deck_id']}: {b['reason']}")
    for u in result.unknown_cards[:20]:
        typer.echo(f"  ? 未解析卡 {u['deck_id']}: {u['raw_name']} ×{u['count']}")
    for w in result.warnings[:20]:
        typer.echo(f"  ? {w}")
    if result.blocked:
        typer.echo("有卡组被 60 张质量门拦截，详见上方清单", err=True)
        raise typer.Exit(code=1)


def _make_notifier(notify: bool, webhook: str | None):
    """--notify/--no-notify + --webhook 组装 on_event 通知回调。"""
    from ptcgdb.monitor.notify import Notifier, make_event_handler

    if not notify and not webhook:
        return None
    return make_event_handler(Notifier(desktop=notify, webhook_url=webhook))


@monitor_app.command("l0")
def monitor_l0(
    dry_run: bool = typer.Option(False, "--dry-run", help="只探测增量（只读，零额外请求）"),
    notify: bool = typer.Option(True, "--notify/--no-notify", help="重要事件桌面通知"),
    webhook: str | None = typer.Option(None, "--webhook", help="webhook URL（可选）"),
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """L0 新卡增量管线：总量探测 → 抓新卡 → 校验 → active → 快照后处理。"""
    from ptcgdb.monitor.l0 import run_l0

    try:
        with HttpClient(BASE_URL) as http:
            result = run_l0(
                db_path, raw_dir, MikMoeScraper(http), dry_run=dry_run,
                on_event=_make_notifier(notify, webhook),
            )
    except CircuitOpenError as exc:
        typer.echo(f"熔断中止：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    for inc in result.report.increments:
        typer.echo(f"增量 set={inc.set_id} kind={inc.kind} {inc.current} → {inc.expected}")
    for inc in result.report.suspicious:
        typer.echo(
            f"可疑（cardsNum 缩水，未处理）set={inc.set_id} {inc.current} → {inc.expected}",
            err=True,
        )
    if result.dry_run:
        typer.echo("dry-run：仅探测，未抓取未入库")
        return
    for sid, rules in result.blocked.items():
        typer.echo(f"set={sid} 校验失败已阻断: {', '.join(rules)}", err=True)
    typer.echo(
        f"activated={result.activated} blocked={len(result.blocked)} "
        f"data_version={result.data_version or '-'}"
    )
    if result.blocked:
        raise typer.Exit(code=1)


@monitor_app.command("l1")
def monitor_l1(
    baseline: bool = typer.Option(False, "--baseline", help="只建基线快照，不比对不出提案"),
    notify: bool = typer.Option(True, "--notify/--no-notify", help="重要事件桌面通知"),
    webhook: str | None = typer.Option(None, "--webhook", help="webhook URL（可选）"),
    db_path: Path = DEFAULT_DB_PATH,
    store_dir: Path = Path("data/monitor/l1"),
    proposals_dir: Path = Path("data/proposals"),
) -> None:
    """L1 赛制监控：官网三页正文提取 + hash 比对 → 变更生成提案（≤3 次请求，限速 2s）。"""
    import httpx

    from ptcgdb.monitor.l1 import PAGE_TARGETS, run_l1
    from ptcgdb.scrapers.http import RateLimiter

    notifier = _make_notifier(notify, webhook)

    def on_event(e: str, p: dict) -> None:
        typer.echo(f"[{e}] {p}")
        if notifier is not None:
            notifier(e, p)

    limiter = RateLimiter()  # 官网只读低频：≤1 次/2 秒
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    with httpx.Client(headers={"User-Agent": ua}, follow_redirects=True, timeout=30.0) as client:
        def fetch(url: str) -> str:
            limiter.wait()
            resp = client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {url}")
            limiter.report_success()
            return resp.text

        try:
            result = run_l1(
                fetch, db_path, store_dir, proposals_dir, baseline=baseline,
                on_event=on_event,
            )
        except (RuntimeError, httpx.HTTPError) as exc:
            typer.echo(f"L1 抓取失败：{exc}", err=True)
            raise typer.Exit(code=1) from exc

    typer.echo(
        f"pages={len(PAGE_TARGETS)} baseline={result.baselines} "
        f"unchanged={result.unchanged} noop={result.noop} "
        f"proposals={len(result.proposals)} news={len(result.news)}"
    )
    if result.proposals:
        typer.echo("提案待人工确认：", err=True)
        for p in result.proposals:
            typer.echo(f"  - {p}", err=True)


@monitor_app.command("proposals")
def monitor_proposals(
    proposals_dir: Path = Path("data/proposals"),
) -> None:
    """列出待审/已审提案（FR-5.2 闭环：确认后用 legal-apply --proposal 应用）。"""
    from ptcgdb.monitor.proposals import list_proposals

    rows = list_proposals(proposals_dir)
    if not rows:
        typer.echo(f"无提案（{proposals_dir}）")
        return
    for r in rows:
        typer.echo(
            f"[{r['status']}] {r['snapshot_id']}（{r['format']}，检测于 {r['detected_at']}）\n"
            f"    {r['path']}"
        )
        for err in r["parse_errors"]:
            typer.echo(f"    ! {err}")


if __name__ == "__main__":
    app()

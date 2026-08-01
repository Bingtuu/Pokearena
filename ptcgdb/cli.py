"""ptcgdb 命令行入口（typer）。"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from ptcgdb.export.exporter import export_all
from ptcgdb.legal import legal_at, seed_snapshots
from ptcgdb.legal.versions import apply_snapshot
from ptcgdb.legal.versions import rollback as rollback_db
from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize import ingest_set
from ptcgdb.orm import Card, Set
from ptcgdb.scrapers import CircuitOpenError, HttpClient, MikMoeScraper, ScrapeRunner
from ptcgdb.scrapers.mikmoe import BASE_URL
from ptcgdb.validate import run_validations, write_report

app = typer.Typer(help="简中 PTCG 标准环境卡牌数据库 CLI")
scrape_app = typer.Typer(help="数据采集（mik.moe 主源，限速 ≤1 次/2 秒）")
monitor_app = typer.Typer(help="监控管线（L0 新卡增量 / L1 赛制变更）")
app.add_typer(scrape_app, name="scrape")
app.add_typer(monitor_app, name="monitor")

DEFAULT_DB_PATH = Path("data/ptcg-cn.db")
DEFAULT_RAW_DIR = Path("data/raw")


@app.command("init-db")
def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """建库/迁移：对数据库执行全部未应用的迁移，打印 user_version。"""
    version = apply_migrations(db_path)
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
    typer.echo("not implemented")


@app.command()
def get() -> None:
    """按 card_id 点查（未实现）。"""
    typer.echo("not implemented")


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
    with Session(engine) as session:
        try:
            pool = legal_at(session, d, format_)
        except LookupError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    engine.dispose()
    typer.echo(
        f"snapshot={pool.snapshot_id} date={pool.date} format={pool.format} "
        f"legal_cards={len(pool.card_ids)}"
    )
    typer.echo(f"白名单命中 {len(pool.by_name_group)} 组：")
    for group, ids in pool.by_name_group.items():
        typer.echo(f"  {group}: {len(ids)} 张")


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


@app.command()
def stats() -> None:
    """库内统计（未实现）。"""
    typer.echo("not implemented")


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

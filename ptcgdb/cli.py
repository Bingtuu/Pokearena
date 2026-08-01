"""ptcgdb 命令行入口（typer）。"""

from pathlib import Path

import typer

from ptcgdb.migrations import apply_migrations
from ptcgdb.scrapers import CircuitOpenError, HttpClient, MikMoeScraper, ScrapeRunner
from ptcgdb.scrapers.mikmoe import BASE_URL

app = typer.Typer(help="简中 PTCG 标准环境卡牌数据库 CLI")
scrape_app = typer.Typer(help="数据采集（mik.moe 主源，限速 ≤1 次/2 秒）")
app.add_typer(scrape_app, name="scrape")

DEFAULT_DB_PATH = Path("data/ptcg-cn.db")
DEFAULT_RAW_DIR = Path("data/raw")


@app.command("init-db")
def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """建库/迁移：对数据库执行全部未应用的迁移，打印 user_version。"""
    version = apply_migrations(db_path)
    typer.echo(f"OK: {db_path} (user_version={version})")


@app.command()
def search() -> None:
    """检索卡牌（未实现）。"""
    typer.echo("not implemented")


@app.command()
def get() -> None:
    """按 card_id 点查（未实现）。"""
    typer.echo("not implemented")


@app.command()
def legal() -> None:
    """合法性判定（未实现）。"""
    typer.echo("not implemented")


@app.command()
def export() -> None:
    """导出七件套（未实现）。"""
    typer.echo("not implemented")


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


if __name__ == "__main__":
    app()

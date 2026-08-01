"""ptcgdb 命令行入口（typer）。"""

from pathlib import Path

import typer

from ptcgdb.migrations import apply_migrations

app = typer.Typer(help="简中 PTCG 标准环境卡牌数据库 CLI")

DEFAULT_DB_PATH = Path("data/ptcg-cn.db")


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

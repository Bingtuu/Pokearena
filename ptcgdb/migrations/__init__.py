"""schema 迁移执行器（FR-6.4）。

`PRAGMA user_version` + `migrations/` 顺序 SQL 脚本，不用 Alembic。
重复执行幂等：user_version 记录已应用的最新版本，低于等于它的脚本跳过。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent
_FILENAME_RE = re.compile(r"^(\d+)_.*\.sql$")


def available_migrations() -> list[tuple[int, Path]]:
    """返回 [(版本号, SQL 文件路径)]，按版本号升序。"""
    migrations: list[tuple[int, Path]] = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = _FILENAME_RE.match(path.name)
        if match:
            migrations.append((int(match.group(1)), path))
    return sorted(migrations)


def apply_migrations(db_path: str | Path) -> int:
    """对 db_path 执行全部未应用的迁移，返回执行后的 user_version。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, path in available_migrations():
            if version <= current:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

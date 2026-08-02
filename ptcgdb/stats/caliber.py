"""口径版本化（PRD FR-9.6）：统计口径词表的 SHA-256 前 12 位入 meta。

跨库比对复算结果先核对口径版本：name_group 归组规则与赛事 tier 系数词表
变化会改变统计结果，meta 记录 hash 使差异可发现。init-db 时写入（INSERT OR
REPLACE，幂等）；导出 manifest 同步。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ptcgdb.normalize.fields import CONFIG_DIR

CALIBER_FILES = {
    "name_group_rules_hash": CONFIG_DIR / "name_group_rules.yml",
    "tournament_tiers_hash": CONFIG_DIR / "vocabularies" / "tournament_tiers.yml",
}


def caliber_hashes() -> dict[str, str]:
    """词表文件 → SHA-256 前 12 位。"""
    return {
        key: hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        for key, path in CALIBER_FILES.items()
    }


def write_caliber_hashes(db_path: str | Path) -> dict[str, str]:
    """口径 hash 写入 meta（幂等覆盖），返回写入的 dict。"""
    hashes = caliber_hashes()
    conn = sqlite3.connect(db_path)
    try:
        for key, value in hashes.items():
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )
        conn.commit()
    finally:
        conn.close()
    return hashes

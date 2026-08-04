"""环境快照种子：config/legality/*.yml → legality_snapshots 表（task 007）。

种子文件是唯一事实来源（官方赛制页结构化），入库按 snapshot_id upsert，重跑幂等。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.orm import LegalitySnapshot

DEFAULT_CONFIG_DIR = Path("config/legality")


class WhitelistEntry(BaseModel):
    """白名单条目：按 name_group 匹配（FR-3.2 第 2 步）。"""

    model_config = ConfigDict(frozen=True)

    name_full: str
    note: str | None = None


class BannedEntry(BaseModel):
    """禁卡条目：按名称 + 特性/招式名匹配（FR-3.2 第 1 步）。"""

    model_config = ConfigDict(frozen=True)

    name: str
    ability_or_attack: str | None = None
    note: str | None = None


class MarkOverride(BaseModel):
    """赛制标记"视作"覆盖：按 card_id 精确匹配（FR-3.2 第 3 步）。"""

    model_config = ConfigDict(frozen=True)

    card_id: str
    mark: str
    note: str | None = None


class SnapshotSeed(BaseModel):
    """一份环境快照的种子数据（对应 legality_snapshots 一行）。"""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    format: str  # standard / open（开放字符串）
    effective_from: date
    source_url: str | None = None
    allowed_marks: list[str]
    allowed_basic_energy_types: list[str]
    whitelist_cards: list[WhitelistEntry] = []
    banned_cards: list[BannedEntry] = []
    mark_overrides: list[MarkOverride] = []


def load_seeds(config_dir: Path = DEFAULT_CONFIG_DIR) -> list[SnapshotSeed]:
    """加载目录下全部 *.yml 种子，按 snapshot_id 排序。"""
    seeds = [
        SnapshotSeed.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
        for f in sorted(config_dir.glob("*.yml"))
    ]
    if not seeds:
        raise ValueError(f"种子目录为空: {config_dir}")
    return sorted(seeds, key=lambda s: s.snapshot_id)


def seed_snapshots(
    db_path: Path, config_dir: Path = DEFAULT_CONFIG_DIR
) -> list[str]:
    """把种子 upsert 进 legality_snapshots（同 snapshot_id 覆盖更新），返回入库 id 列表。"""
    seeds = load_seeds(config_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for seed in seeds:
            payload = {
                "format": seed.format,
                "effective_from": seed.effective_from,
                "allowed_marks": seed.allowed_marks,
                "allowed_basic_energy_types": seed.allowed_basic_energy_types,
                "whitelist_cards": [w.model_dump() for w in seed.whitelist_cards],
                "banned_cards": [b.model_dump() for b in seed.banned_cards],
                "mark_overrides": [m.model_dump() for m in seed.mark_overrides],
                "source_url": seed.source_url,
            }
            row = session.get(LegalitySnapshot, seed.snapshot_id)
            if row is not None and row.effective_to is not None:
                raise ValueError(
                    f"快照 {seed.snapshot_id} 已冻结"
                    f"（effective_to={row.effective_to}），不可覆盖。"
                    f"请使用 legal-apply 创建新快照。"
                )
            if row is None:
                session.add(
                    LegalitySnapshot(
                        snapshot_id=seed.snapshot_id,
                        effective_to=None,
                        latest_text_overrides={},
                        created_at=datetime.now(UTC),
                        **payload,
                    )
                )
            else:
                # upsert：种子字段全部覆盖；effective_to / latest_text_overrides / created_at 不动
                for key, value in payload.items():
                    setattr(row, key, value)
        session.commit()
    engine.dispose()
    return [s.snapshot_id for s in seeds]

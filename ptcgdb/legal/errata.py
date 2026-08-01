"""L2 勘误导入（task 015，PRD FR-5.3）。

`config/errata/*.yml` 人工维护（官方公告的卡牌补充说明/勘误）→ errata 表 upsert。
card_id 不存在记 warning 跳过（不中断）；重跑幂等。
引擎 `effective_text` 统一消费：勘误（最新生效）> 最新印刷 > text_raw。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, Errata

DEFAULT_ERRATA_DIR = Path("config/errata")


class ErrataSeed(BaseModel):
    """一条勘误的种子数据（对应 errata 一行）。"""

    model_config = ConfigDict(frozen=True)

    errata_id: str
    card_id: str
    effective_from: date
    corrected_text: str
    notice_url: str | None = None


@dataclass
class ImportResult:
    imported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def import_errata(db_path: Path, config_dir: Path = DEFAULT_ERRATA_DIR) -> ImportResult:
    """把 config_dir 下全部 *.yml 勘误 upsert 进 errata 表。"""
    result = ImportResult()
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        result.warnings.append(f"勘误目录不存在: {config_dir}")
        return result

    seeds: list[ErrataSeed] = []
    for path in sorted(config_dir.glob("*.yml")):
        try:
            seeds.append(ErrataSeed.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            ))
        except (yaml.YAMLError, ValueError) as exc:
            result.warnings.append(f"{path.name}: 解析失败 {exc}")

    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for seed in seeds:
            if session.get(Card, seed.card_id) is None:
                result.warnings.append(
                    f"{seed.errata_id}: card_id 不存在（{seed.card_id}），跳过"
                )
                continue
            row = session.get(Errata, seed.errata_id)
            if row is None:
                session.add(Errata(**seed.model_dump()))
            else:
                for key, value in seed.model_dump().items():
                    setattr(row, key, value)
            result.imported.append(seed.errata_id)
        session.commit()
    engine.dispose()
    return result

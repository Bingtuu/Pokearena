"""task 022：EN 映射填充——mik raw 英文桥（nameEn/setCodeEn/cardIndexEn）。

填充 `cards.name_en` + `external_ids(system='mik_en', external_id='{setCodeEn}-{cardIndexEn}')`。
幂等：name_en 一致记 already，external_ids 主键 merge；raw 层只读。
无桥字段的卡（30thP/宝石包/部分促销，简中独占）记 no_bridge 清单，不猜测。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.orm import Card, ExternalId
from ptcgdb.validate.rules import _raw_card_index


@dataclass
class EnFillResult:
    total: int = 0
    filled: int = 0
    already: int = 0
    no_bridge: list[str] = field(default_factory=list)
    by_set: dict[str, list[int]] = field(default_factory=dict)  # set_id → [mapped, total]


def fill_en(db_path: Path, raw_dir: Path) -> EnFillResult:
    """全库扫描填充 EN 映射。返回统计与无桥清单（按 card_id 排序）。"""
    raw_index = _raw_card_index(raw_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    result = EnFillResult()
    with Session(engine) as session:
        cards = list(session.scalars(select(Card)))
        result.total = len(cards)
        for card in cards:
            bucket = result.by_set.setdefault(card.set_id, [0, 0])
            bucket[1] += 1
            en_name = en_id = None
            path = raw_index.get((card.set_id, card.number))
            if path is not None:
                data = json.loads(path.read_text(encoding="utf-8"))["data"]
                if (
                    data.get("nameEn")
                    and data.get("setCodeEn")
                    and data.get("cardIndexEn") is not None
                ):
                    en_name = data["nameEn"]
                    en_id = f"{data['setCodeEn']}-{data['cardIndexEn']}"
            if en_name is None:
                result.no_bridge.append(card.card_id)
                continue
            bucket[0] += 1
            if card.name_en == en_name:
                result.already += 1
            else:
                card.name_en = en_name
                result.filled += 1
            session.merge(
                ExternalId(card_id=card.card_id, system="mik_en", external_id=en_id)
            )
        session.commit()
    engine.dispose()
    result.no_bridge.sort()
    return result

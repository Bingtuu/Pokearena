"""task 030（F-02）：mik 双重列示别名标记 `cards.alias_of`。

A2 比对实测：CS4DaC/CSVL1C 的字母编号基本能量条目（FIG/WAT/…）与同系列
数字编号条目 raw 逐字段全等（仅 cardIndex 不同），是同一张物理卡的重复列示，
卡面以数字编号为准。规则（零猜测）：

  基本能量 ∧ 字母编号 ∧ 同系列同名数字编号孪生**恰好 1 张** → alias_of = 孪生
  孪生 0 张（如 CSVH5C 'NaN1'）或多张 → 不标，记 questions 清单人工裁决

幂等可重跑；alias 行保留（主键与 12,420 总数口径不动）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.orm import Card


@dataclass
class AliasMarkResult:
    marked: dict[str, str] = field(default_factory=dict)  # alias card_id → 正本 card_id
    cleared: list[str] = field(default_factory=list)  # 规则不再命中而清除的旧标记
    questions: dict[str, str] = field(default_factory=dict)  # card_id → 原因


def mark_aliases(db_path: Path) -> AliasMarkResult:
    """全库扫描标记/清除 alias_of。幂等。"""
    engine = create_engine(f"sqlite:///{db_path}")
    result = AliasMarkResult()
    with Session(engine) as session:
        cards = list(session.scalars(select(Card).filter_by(is_basic_energy=True)))
        # 同系列同名数字编号正本索引
        canonical: dict[tuple[str, str], list[str]] = {}
        for c in cards:
            if c.number.isdigit():
                canonical.setdefault((c.set_id, c.name_full), []).append(c.card_id)
        for c in cards:
            if c.number.isdigit():
                continue  # 数字编号条目永为正本
            twins = canonical.get((c.set_id, c.name_full), [])
            if len(twins) == 1:
                if c.alias_of != twins[0]:
                    c.alias_of = twins[0]
                result.marked[c.card_id] = twins[0]
            else:
                if c.alias_of is not None:
                    c.alias_of = None
                    result.cleared.append(c.card_id)
                reason = "同系列无数字编号孪生" if not twins else f"孪生多张: {twins}"
                result.questions[c.card_id] = reason
        session.commit()
    engine.dispose()
    return result

"""A1 白名单逐卡核对器（task 016，PRD §10 A1）。

按赛制独立核对当前快照：
- 白名单逐条：name_full 归组可解析（诊断）且 legal_at 有合法印刷（判定）；
- 基本能量双向：allowed 每种有合法卡；词表内不在 allowed 的种类池外（负向，妖能量反例）。
只报告不修复：不符项带原因，需人工裁决。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptcgdb.legal.engine import _select_snapshot_orm, group_map, legal_at
from ptcgdb.normalize import fields
from ptcgdb.orm import Card


@dataclass
class AuditEntry:
    name: str
    kind: str  # whitelist / energy / energy_negative
    ok: bool
    detail: str


@dataclass
class AuditResult:
    format: str
    entries: list[AuditEntry] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(e.ok for e in self.entries)


def _known_energy_types() -> list[str]:
    """词表内全部基本能量种类（负向核对分母）。"""
    return sorted(set(fields.load_energy_code_map().values()))


def audit_format(session: Session, fmt: str, d: date) -> AuditResult:
    """核对 fmt 赛制当前快照（覆盖日期 d）的白名单与能量合法性。"""
    snapshot = _select_snapshot_orm(session, fmt, d)
    pool = legal_at(session, d, fmt)
    groups = group_map(session)
    group_exists = {g for groups_of in groups.values() for g in groups_of}
    name_fulls = set(session.scalars(select(Card.name_full)).all())
    # 各能量种类的 active 基本能量卡
    energy_cards: dict[str, list[str]] = {}
    for card in session.scalars(
        select(Card).where(Card.status == "active", Card.is_basic_energy.is_(True))
    ):
        for t in card.provides or []:
            energy_cards.setdefault(t, []).append(card.card_id)

    result = AuditResult(format=fmt)
    for w in sorted(snapshot.whitelist_cards or [], key=lambda x: x["name_full"]):
        name = w["name_full"]
        resolved = name in group_exists or name in name_fulls
        printings = pool.by_name_group.get(name, [])
        if printings:
            result.entries.append(AuditEntry(
                name=name, kind="whitelist", ok=True,
                detail=f"{len(printings)} 张合法印刷",
            ))
        else:
            diag = "归组/卡名在库中不存在" if not resolved else "归组存在但无合法印刷"
            result.entries.append(AuditEntry(name=name, kind="whitelist", ok=False,
                                             detail=diag))

    allowed = set(snapshot.allowed_basic_energy_types or [])
    for t in _known_energy_types():
        cards = energy_cards.get(t, [])
        legal = [cid for cid in cards if cid in pool.card_ids]
        if t in allowed:
            ok = bool(legal)
            result.entries.append(AuditEntry(
                name=f"能量:{t}", kind="energy", ok=ok,
                detail=f"{len(legal)} 张合法" if ok else "allowed 但库中无合法基本能量卡",
            ))
        else:
            ok = not legal
            result.entries.append(AuditEntry(
                name=f"能量负向:{t}", kind="energy_negative", ok=ok,
                detail="池外（正确）" if ok
                else f"不应合法但 {len(legal)} 张在池内: {legal[:3]}",
            ))
    return result

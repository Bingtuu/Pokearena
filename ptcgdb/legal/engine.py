"""合法性引擎（task 008，PRD FR-3.1~3.3）。

纯函数语义：输入 session + 日期 + 赛制，输出合法卡池 / 有效文本。
判定顺序（FR-3.2，任一命中即定）：
  1. 禁卡表（名称 + 特性/招式名）→ 不合法
  2. 白名单（name_group 匹配，按赛制独立清单）→ 合法
  3. 赛制标记"视作"覆盖（mark_overrides，card_id 精确匹配）→ 以覆盖标记继续 4
  4. 赛制标记 ∈ allowed_marks → 合法
  5. 基本能量：is_basic_energy 且能量种类 ∈ allowed_basic_energy_types → 合法
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ptcgdb.orm import Card, CardNameGroup, Errata, LegalitySnapshot
from ptcgdb.schemas.models import EffectiveText, LegalityPool


def _select_snapshot(session: Session, fmt: str, d: date) -> LegalitySnapshot:
    """取覆盖日期 d 的最新快照；无快照抛 LookupError。"""
    row = session.scalars(
        select(LegalitySnapshot)
        .where(
            LegalitySnapshot.format == fmt,
            LegalitySnapshot.effective_from <= d,
            or_(LegalitySnapshot.effective_to.is_(None), d <= LegalitySnapshot.effective_to),
        )
        .order_by(LegalitySnapshot.effective_from.desc())
        .limit(1)
    ).first()
    if row is None:
        raise LookupError(f"无覆盖 {d} 的 {fmt} 赛制快照")
    return row


def _group_map(session: Session) -> dict[str, set[str]]:
    """card_id -> 所属 name_group 集合。"""
    result: dict[str, set[str]] = {}
    for card_id, group_key in session.execute(
        select(CardNameGroup.card_id, CardNameGroup.group_key)
    ):
        result.setdefault(card_id, set()).add(group_key)
    return result


def _is_banned(card: Card, names: set[str], banned: list[dict]) -> bool:
    """禁卡匹配：名称命中（含同组印刷）；带特性/招式名限定时需再命中该名称。"""
    for entry in banned:
        if entry["name"] not in names:
            continue
        qualifier = entry.get("ability_or_attack")
        if not qualifier:
            return True
        ability_names = {a["name"] for a in card.abilities or []}
        attack_names = {a["name"] for a in card.attacks or []}
        if qualifier in ability_names or qualifier in attack_names:
            return True
    return False


def legal_at(session: Session, d: date, fmt: str) -> LegalityPool:
    """合法卡池（FR-3.1）：只统计 status=active 的卡。"""
    snapshot = _select_snapshot(session, fmt, d)
    allowed_marks = set(snapshot.allowed_marks)
    allowed_energies = set(snapshot.allowed_basic_energy_types)
    whitelist = {w["name_full"] for w in snapshot.whitelist_cards}
    overrides = {m["card_id"]: m["mark"] for m in snapshot.mark_overrides}
    groups_of = _group_map(session)

    pool: set[str] = set()
    by_group: dict[str, list[str]] = {}
    for card in session.scalars(select(Card).where(Card.status == "active")):
        names = groups_of.get(card.card_id, set()) | {card.name_full}
        # 1. 禁卡表
        if _is_banned(card, names, snapshot.banned_cards):
            continue
        # 2. 白名单（name_group 匹配）
        hit_groups = names & whitelist
        if hit_groups:
            pool.add(card.card_id)
            for g in sorted(hit_groups):
                by_group.setdefault(g, []).append(card.card_id)
            continue
        # 3. 视作覆盖 → 4. 赛制标记
        mark = overrides.get(card.card_id, card.regulation_mark)
        if mark is not None and mark in allowed_marks:
            pool.add(card.card_id)
            continue
        # 5. 基本能量（种类合法性完全由快照维护，不做全局特判）
        if (
            card.is_basic_energy
            and card.provides
            and all(p in allowed_energies for p in card.provides)
        ):
            pool.add(card.card_id)

    return LegalityPool(
        snapshot_id=snapshot.snapshot_id,
        format=fmt,
        date=d,
        card_ids=frozenset(pool),
        by_name_group={g: sorted(ids) for g, ids in sorted(by_group.items())},
    )


def effective_text(session: Session, card_id: str, d: date) -> EffectiveText:
    """有效文本（FR-3.3）：勘误（最新生效）> 最新印刷 > text_raw。"""
    card = session.get(Card, card_id)
    if card is None:
        raise LookupError(f"卡牌不存在: {card_id}")

    # 最新印刷：查覆盖日期 d 的快照 latest_text_overrides（新快照优先，格式间确定序）
    resolved_id, source = card_id, "text_raw"
    snapshots = session.scalars(
        select(LegalitySnapshot)
        .where(
            LegalitySnapshot.effective_from <= d,
            or_(LegalitySnapshot.effective_to.is_(None), d <= LegalitySnapshot.effective_to),
        )
        .order_by(LegalitySnapshot.effective_from.desc(), LegalitySnapshot.format)
    )
    for snap in snapshots:
        target = (snap.latest_text_overrides or {}).get(card_id)
        if target:
            resolved_id, source = target, "latest_print"
            break
    resolved = session.get(Card, resolved_id)
    if resolved is None:
        raise LookupError(f"latest_text_overrides 指向不存在的卡: {resolved_id}")

    # 勘误：最新已生效者优先
    errata = session.scalars(
        select(Errata)
        .where(Errata.card_id == resolved_id, Errata.effective_from <= d)
        .order_by(Errata.effective_from.desc())
        .limit(1)
    ).first()
    if errata is not None:
        return EffectiveText(
            card_id=card_id, resolved_card_id=resolved_id,
            text=errata.corrected_text, source="errata",
        )
    return EffectiveText(
        card_id=card_id, resolved_card_id=resolved_id,
        text=resolved.text_raw, source=source,
    )

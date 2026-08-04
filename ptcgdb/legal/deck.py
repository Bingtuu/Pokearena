"""FR-3.4 同名计数引擎（task 025，PRD v1.7）+ FR-8 validate_deck 核（task 026）。

纯函数核 `check_counts` / `validate_deck`：操作 frozen Pydantic 模型，供 CLI 与
SDK 双后端复用（对齐 legal engine 的分层模式）。

check_counts 判定（FR-3.4 逐条）：
  1. deck_size：卡表总数 ≠ 60；
  2. name_limit 双层：单 card_id ≤ deck_limit（仅在单卡上限 < 组上限时单独报告，
     否则由组违规覆盖，避免同一事实重复报告）；同 name_group 总数 ≤ 组上限
     （组内含 V-UNION 部件 = 4，否则 max(成员 deck_limit)）；基本能量豁免；
  3. ace_spec_limit：全卡组 is_ace_spec 总数 ≤ 1；
  4. radiant_limit：全卡组 rule_box_type=radiant 总数 ≤ 1。

validate_deck 组合 select_snapshot/build_pool 的产物（pool）与 check_counts，
追加合法性层（FR-8 Violation 语义全集）：
  - banned / not_legal 互斥——不在合法卡池的卡先查禁卡表，命中报 banned，
    否则报 not_legal（禁卡优先，与 build_pool 五步判定同序）；
  - 按 card_id 逐卡报告，count = 卡表内 copies 数；
  - evolution_chain 为预留类型，当前规则集不产生。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from ptcgdb.legal.engine import is_banned
from ptcgdb.schemas.models import (
    Card,
    DeckReport,
    LegalityPool,
    LegalitySnapshot,
    Violation,
)

DECK_SIZE = 60
V_UNION_GROUP_LIMIT = 4  # V-UNION 组上限（部件各 1、组总 ≤4）


def _group_limit(members: list[Card]) -> int:
    if any(m.rule_box_type == "v_union" for m in members):
        return V_UNION_GROUP_LIMIT
    return max(m.deck_limit for m in members)


def check_counts(
    deck: list[str],
    cards_by_id: Mapping[str, Card],
    groups_of: Mapping[str, set[str]],
) -> list[Violation]:
    """同名计数判定。deck = card_id 列表（可重复）；返回违规列表（可为空）。

    groups_of：card_id → 所属 name_group 集合（无归组行的卡回退 {name_full}，
    与 ingest 的默认归组口径一致）。
    """
    violations: list[Violation] = []

    # 1. deck_size
    if len(deck) != DECK_SIZE:
        violations.append(Violation(
            kind="deck_size",
            detail=f"卡组共 {len(deck)} 张，应为 {DECK_SIZE} 张",
            cards=[], count=len(deck),
        ))

    # unknown_card（库外 id 不参与后续计数）
    unknown = sorted({cid for cid in deck if cid not in cards_by_id})
    if unknown:
        violations.append(Violation(
            kind="unknown_card",
            detail=f"{len(unknown)} 种卡不在库：{', '.join(unknown)}",
            cards=unknown, count=len(unknown),
        ))

    counts = Counter(cid for cid in deck if cid in cards_by_id)

    # 组 → 成员（全库反查，组上限由全库成员形态决定）
    members_of: dict[str, set[str]] = {}
    for cid, card in cards_by_id.items():
        for g in groups_of.get(cid) or {card.name_full}:
            members_of.setdefault(g, set()).add(cid)

    # 2. name_limit 双层
    for g in sorted(members_of):
        member_ids = members_of[g]
        total = sum(counts.get(cid, 0) for cid in member_ids)
        if total == 0:
            continue
        members = [cards_by_id[cid] for cid in member_ids]
        if all(m.is_basic_energy for m in members):
            continue  # 基本能量不受同名上限约束
        limit = _group_limit(members)
        # 单卡上限（仅当单卡上限 < 组上限时单独报告——V-UNION 部件各 1 的场景）
        for cid in sorted(member_ids):
            n = counts.get(cid, 0)
            card = cards_by_id[cid]
            if n > card.deck_limit and card.deck_limit < limit:
                violations.append(Violation(
                    kind="name_limit",
                    detail=f"「{card.name_full}」单卡 {n} 张，上限 {card.deck_limit}",
                    cards=[cid], count=n,
                ))
        if total > limit:
            involved = sorted(cid for cid in member_ids if counts.get(cid))
            violations.append(Violation(
                kind="name_limit",
                detail=f"同名组「{g}」共 {total} 张，上限 {limit}",
                cards=involved, count=total,
            ))

    # 3. ace_spec_limit（跨卡名全局 ≤1）
    ace_ids = sorted(cid for cid in counts if cards_by_id[cid].is_ace_spec)
    ace_total = sum(counts[cid] for cid in ace_ids)
    if ace_total > 1:
        violations.append(Violation(
            kind="ace_spec_limit",
            detail=f"ACE SPEC 卡全卡组共 {ace_total} 张，上限 1",
            cards=ace_ids, count=ace_total,
        ))

    # 4. radiant_limit（跨卡名全局 ≤1）
    radiant_ids = sorted(
        cid for cid in counts if cards_by_id[cid].rule_box_type == "radiant"
    )
    radiant_total = sum(counts[cid] for cid in radiant_ids)
    if radiant_total > 1:
        violations.append(Violation(
            kind="radiant_limit",
            detail=f"光辉宝可梦全卡组共 {radiant_total} 张，上限 1",
            cards=radiant_ids, count=radiant_total,
        ))

    return violations


def validate_deck(
    deck: list[str],
    cards_by_id: Mapping[str, Card],
    groups_of: Mapping[str, set[str]],
    snapshot: LegalitySnapshot,
    pool: LegalityPool,
) -> DeckReport:
    """FR-8 卡组校验：计数层（check_counts）+ 合法性层（banned/not_legal）。

    deck = card_id 列表（可重复）；snapshot/pool = select_snapshot/build_pool 的
    产物（pool 携带 format/date/snapshot_id）。返回结构化 DeckReport，不抛异常。
    """
    violations = check_counts(deck, cards_by_id, groups_of)

    copies = Counter(deck)
    for cid in sorted(copies):
        card = cards_by_id.get(cid)
        if card is None or cid in pool.card_ids:
            continue  # 库外卡已由 unknown_card 报告；合法卡跳过
        names = set(groups_of.get(cid) or ()) | {card.name_full}
        if is_banned(card, names, snapshot.banned_cards):
            violations.append(Violation(
                kind="banned",
                detail=f"「{card.name_full}」命中禁卡表（{pool.format} {pool.date}）",
                cards=[cid], count=copies[cid],
            ))
        else:
            violations.append(Violation(
                kind="not_legal",
                detail=f"「{card.name_full}」不在 {pool.format} {pool.date} 合法卡池",
                cards=[cid], count=copies[cid],
            ))

    return DeckReport(
        ok=not violations,
        deck_size=len(deck),
        format=pool.format,
        date=pool.date,
        snapshot_id=pool.snapshot_id,
        violations=violations,
    )

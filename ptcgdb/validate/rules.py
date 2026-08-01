"""FR-2.3 六条校验规则（draft→active 的阻断门槛）。

任一规则失败即阻断并出报告（PRD FR-2.3）。规则 1/2/4/5 纯库内复核；
规则 3/6 需要 raw 目录做 DB vs raw 复核（raw 层只读，经 read_raw 校验 hash）。

与 PRD 的偏差（task 006）：PRD 规则 6 原文为"与降级源抽样比对"，D1 后 M1
仅有 mik.moe 单源，本期以 DB vs raw 同源自验替代，报告（report.py）如实注明；
降级源比对待多源（Phase 2）后补齐。
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session

from ptcgdb.normalize import fields
from ptcgdb.orm import Card, CardRelation, Set
from ptcgdb.scrapers.raw_store import read_raw

# 规则 1 必填字段（PRD FR-2.3：卡名、卡号、赛制标记、卡牌种类、text_raw）
# 赛制标记对基本能量豁免（见 check_required 注）
REQUIRED_FIELDS = ("name_full", "number", "regulation_mark", "card_type", "text_raw")

# V-UNION 四方位（PRD §7.2 union_position）
V_UNION_POSITIONS = ("左上", "右上", "左下", "右下")

# 规则 6 抽样比例：每系列 ≥5% 向上取整、至少 1 张
SAMPLE_RATIO = 0.05


@dataclass
class RuleResult:
    """单条规则的结构化结果。failures 为空即通过；details 放对账表/抽样清单。"""

    rule: str
    passed: bool = True
    checked: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None

    def fail(self, **item: Any) -> None:
        self.passed = False
        self.failures.append(item)


@dataclass
class _Vocabs:
    """规则 2/3 用词的词表快照（config/vocabularies/，开放词表不写死）。"""

    energy_names: set[str]
    card_types: set[str]
    trainer_subtypes: set[str]
    rarities: set[str]
    rule_box_types: set[str]
    stages: set[str]
    code_map: dict[str, str]


def _load_vocabs(vocab_dir: Path) -> _Vocabs:
    card_type_map = fields.load_card_type_map(vocab_dir)
    energy_doc = yaml.safe_load(
        (vocab_dir / "energy_types.yml").read_text(encoding="utf-8")
    )
    return _Vocabs(
        energy_names={e["name"] for e in energy_doc["types"]},
        card_types={ct for ct, _ in card_type_map.values()},
        trainer_subtypes={st for _, st in card_type_map.values() if st},
        rarities=fields.load_rarities(vocab_dir),
        rule_box_types=fields.load_rule_box_types(vocab_dir),
        stages=set(fields.load_stage_map(vocab_dir).values()),
        code_map=fields.load_energy_code_map(vocab_dir),
    )


def check_required(cards: list[Card]) -> RuleResult:
    """规则 1：卡名/卡号/赛制标记/卡牌种类/text_raw 非空。

    基本能量豁免（task 005 实测）：is_basic_energy=TRUE 的卡无赛制标记、
    卡面无文字（text_raw 为空）均为数据事实——合法性走 is_basic_energy+快照
    路径（PRD FR-3.2），"卡面全部文字逐字保留"（§7.2）对无字卡面即空串。
    两项存 NULL/空不算必填缺失；其余字段对基本能量仍必填。
    """
    res = RuleResult(rule="必填非空", checked=len(cards))
    res.note = "regulation_mark/text_raw 对 is_basic_energy=TRUE 的卡豁免（PRD FR-3.2/§7.2）"
    for c in cards:
        for name in REQUIRED_FIELDS:
            if name in ("regulation_mark", "text_raw") and c.is_basic_energy:
                continue
            value = getattr(c, name)
            if value is None or (isinstance(value, str) and not value.strip()):
                res.fail(card_id=c.card_id, field=name, note="必填字段为空")
    return res


def check_enums(cards: list[Card], vocabs: _Vocabs) -> RuleResult:
    """规则 2：属性/卡牌种类/罕贵度/规则框/进化阶段等枚举值在词表内。

    regulation_mark 无词表文件（开放字符串），枚举校验不含赛制标记，见 note。
    """
    res = RuleResult(rule="枚举合法", checked=len(cards))
    res.note = "regulation_mark 无词表文件（开放字符串），未做枚举校验"
    for c in cards:
        if c.card_type not in vocabs.card_types:
            res.fail(card_id=c.card_id, field="card_type", value=c.card_type, note="不在词表")
        if c.trainer_subtype is not None and c.trainer_subtype not in vocabs.trainer_subtypes:
            res.fail(
                card_id=c.card_id, field="trainer_subtype",
                value=c.trainer_subtype, note="不在词表",
            )
        if c.rarity not in vocabs.rarities:
            res.fail(card_id=c.card_id, field="rarity", value=c.rarity, note="不在词表")
        if c.rule_box_type is not None and c.rule_box_type not in vocabs.rule_box_types:
            res.fail(
                card_id=c.card_id, field="rule_box_type",
                value=c.rule_box_type, note="不在词表",
            )
        if c.stage is not None and c.stage not in vocabs.stages:
            res.fail(card_id=c.card_id, field="stage", value=c.stage, note="不在词表")
        for type_value, field_name in (
            *((t, "types") for t in c.types or []),
            *((t, "provides") for t in c.provides or []),
        ):
            if type_value not in vocabs.energy_names:
                res.fail(
                    card_id=c.card_id, field=field_name, value=type_value, note="不在词表"
                )
        for wr, field_name in ((c.weakness, "weakness"), (c.resistance, "resistance")):
            if wr and wr.get("type") not in vocabs.energy_names:
                res.fail(
                    card_id=c.card_id, field=field_name,
                    value=wr.get("type"), note="不在词表",
                )
    return res


def check_energy(
    cards: list[Card], vocabs: _Vocabs, raw_dir: Path | None
) -> RuleResult:
    """规则 3：招式 cost 能量符号在词表内；给出 raw_dir 时复核 cost 保序与 retreat_cost。

    cost 顺序复核直接复用 normalize 的 parse_cost：raw cost 串重算结果应与
    DB attacks[].cost（[{type, count}] 分组保序）逐段相等。
    """
    res = RuleResult(rule="能量成本合法且保序")
    if raw_dir is None:
        res.note = "未提供 raw_dir，仅做词表校验，保序复核跳过"
    for c in cards:
        res.checked += 1
        for i, attack in enumerate(c.attacks or []):
            for item in attack.get("cost") or []:
                if item.get("type") not in vocabs.energy_names:
                    res.fail(
                        card_id=c.card_id, field=f"attacks[{i}].cost",
                        value=item.get("type"), note="能量符号不在词表",
                    )
        if raw_dir is None:
            continue
        raw_path = Path(raw_dir) / "mikmoe" / c.set_id / f"{c.number}.json"
        raw = read_raw(raw_path)
        if raw is None:
            res.fail(card_id=c.card_id, field="raw", note="raw 缺失或 hash 无效，保序无法复核")
            continue
        pa = (raw.get("data") or {}).get("pokemonAttr") or {}
        db_attacks = c.attacks or []
        raw_attacks = pa.get("attack") or []
        if len(db_attacks) != len(raw_attacks):
            res.fail(card_id=c.card_id, field="attacks", note="招式数量与 raw 不一致")
            continue
        for i, (db_atk, raw_atk) in enumerate(zip(db_attacks, raw_attacks, strict=True)):
            try:
                expected, expected_mod = fields.parse_cost_full(
                    raw_atk.get("cost"), vocabs.code_map
                )
            except fields.UnknownEnumError as exc:
                res.fail(
                    card_id=c.card_id, field=f"attacks[{i}].cost",
                    note=f"raw cost 含未知能量码: {exc}",
                )
                continue
            if db_atk.get("cost") != expected:
                res.fail(
                    card_id=c.card_id, field=f"attacks[{i}].cost",
                    db=db_atk.get("cost"), raw=expected, note="cost 顺序/分组与 raw 不一致",
                )
            if db_atk.get("cost_modifier") != expected_mod:
                res.fail(
                    card_id=c.card_id, field=f"attacks[{i}].cost_modifier",
                    db=db_atk.get("cost_modifier"), raw=expected_mod,
                    note="cost 追加标记与 raw 不一致",
                )
        if c.retreat_cost != pa.get("retreatCost"):
            res.fail(
                card_id=c.card_id, field="retreat_cost",
                db=c.retreat_cost, raw=pa.get("retreatCost"), note="撤退费用与 raw 不一致",
            )
    return res


def check_reconciliation(sets: list[Set], cards: list[Card]) -> RuleResult:
    """规则 4：系列对账，入库数 == expected_count + expected_secret_count（§7.1）。"""
    res = RuleResult(rule="系列对账", checked=len(sets))
    counts = Counter(c.set_id for c in cards)
    for s in sets:
        actual = counts.get(s.set_id, 0)
        if s.expected_count is None:
            res.details.append(
                {"set_id": s.set_id, "expected": None, "actual": actual, "ok": False}
            )
            res.fail(set_id=s.set_id, actual=actual, note="expected_count 未填，无法对账")
            continue
        expected = s.expected_count + (s.expected_secret_count or 0)
        ok = actual == expected
        res.details.append(
            {"set_id": s.set_id, "expected": expected, "actual": actual, "ok": ok}
        )
        if not ok:
            res.fail(
                set_id=s.set_id, expected=expected, actual=actual,
                note="入库数 != expected_count + expected_secret_count",
            )
    return res


def check_vunion(cards: list[Card], relations: list[CardRelation]) -> RuleResult:
    """规则 5：V-UNION 4 部件齐全（union_part_of 连通分量）、方位互斥不重复。

    无 V-UNION 样本（rule_box_type=v_union 或 union_position 非空）时规则跳过。
    方位校验仅在有方位数据时执行：mik 无部件方位字段（task 005 SSP 实测，
    四部件同构），全 None 时只查 4 部件齐全并如实注明。
    """
    res = RuleResult(rule="V-UNION 完整性")
    union_cards = [c for c in cards if c.rule_box_type == "v_union" or c.union_position]
    if not union_cards:
        res.note = "无 V-UNION 样本，规则跳过"
        return res
    res.checked = len(union_cards)
    by_id = {c.card_id: c for c in union_cards}

    # 并查集：union_part_of 边（无向）求连通分量，一个分量 = 一只 V-UNION
    parent = {cid: cid for cid in by_id}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in relations:
        if r.relation_type != "union_part_of":
            continue
        if r.card_id in by_id and r.related_card_id in by_id:
            parent[find(r.card_id)] = find(r.related_card_id)

    comps: dict[str, list[Card]] = {}
    for c in union_cards:
        comps.setdefault(find(c.card_id), []).append(c)

    for comp in comps.values():
        comp.sort(key=lambda c: c.card_id)
        ids = [c.card_id for c in comp]
        if len(comp) != 4:
            res.fail(card_ids=ids, note=f"union_part_of 部件数={len(comp)}，应为 4")
        positions = [c.union_position for c in comp]
        if all(p is None for p in positions):
            # mik 无部件方位字段（task 005 SSP 实测：四部件数据完全同构），
            # 方位校验整体跳过并如实注明，不判失败
            res.note = "部件方位数据不可得（mik 无此字段），方位校验跳过（task 005）"
            continue
        seen: set[str] = set()
        for c in comp:
            pos = c.union_position
            if pos is None:
                res.fail(card_id=c.card_id, note="union_position 未填（部分部件有方位数据）")
            elif pos not in V_UNION_POSITIONS:
                res.fail(card_id=c.card_id, value=pos, note="未知方位")
            elif pos in seen:
                res.fail(card_id=c.card_id, value=pos, note="方位重复")
            else:
                seen.add(pos)
        missing = set(V_UNION_POSITIONS) - seen
        if len(comp) == 4 and missing:
            res.fail(card_ids=ids, note=f"方位缺失: {sorted(missing)}")
    return res


def check_sampling(cards: list[Card], raw_dir: Path | None) -> RuleResult:
    """规则 6：每系列 ≥5% 抽样（向上取整至少 1 张），DB vs raw 逐字段比对。

    抽样确定性：card_id 升序后等距取样。比对字段：卡名 + HP + 招式名，
    一致率必须 100%（任一字段不一致即失败）。
    """
    res = RuleResult(rule="抽样比对")
    res.note = "PRD 原文为与降级源比对；M1 单源，本期为 DB vs raw 同源自验"
    if raw_dir is None:
        res.note += "；未提供 raw_dir，规则跳过"
        return res
    by_set: dict[str, list[Card]] = {}
    for c in cards:
        by_set.setdefault(c.set_id, []).append(c)
    for set_id, set_cards in sorted(by_set.items()):
        set_cards.sort(key=lambda c: c.card_id)
        n = max(math.ceil(len(set_cards) * SAMPLE_RATIO), 1)
        stride = len(set_cards) / n
        sampled = [set_cards[int(i * stride)] for i in range(n)]
        res.details.append(
            {
                "set_id": set_id,
                "total": len(set_cards),
                "samples": [c.card_id for c in sampled],
            }
        )
        for c in sampled:
            res.checked += 1
            raw = read_raw(Path(raw_dir) / "mikmoe" / set_id / f"{c.number}.json")
            if raw is None:
                res.fail(card_id=c.card_id, field="raw", note="raw 缺失或 hash 无效，无法比对")
                continue
            data = raw.get("data") or {}
            pa = data.get("pokemonAttr") or {}
            if c.name_full != data.get("name"):
                res.fail(
                    card_id=c.card_id, field="name_full",
                    db=c.name_full, raw=data.get("name"), note="卡名不一致",
                )
            if c.hp != pa.get("hp"):
                res.fail(
                    card_id=c.card_id, field="hp",
                    db=c.hp, raw=pa.get("hp"), note="HP 不一致",
                )
            db_names = [a.get("name") for a in c.attacks or []]
            raw_names = [a.get("name") or "" for a in pa.get("attack") or []]
            if db_names != raw_names:
                res.fail(
                    card_id=c.card_id, field="attacks.name",
                    db=db_names, raw=raw_names, note="招式名不一致",
                )
    return res


def run_validations(
    db_path: Path,
    *,
    set_id: str | None = None,
    raw_dir: Path | None = None,
    config_dir: Path | None = None,
) -> list[RuleResult]:
    """对指定系列（缺省全部）按 FR-2.3 顺序跑六条规则。"""
    vocab_dir = (Path(config_dir) / "vocabularies") if config_dir else fields.VOCAB_DIR
    vocabs = _load_vocabs(vocab_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        set_stmt = select(Set)
        card_stmt = select(Card)
        if set_id:
            if session.get(Set, set_id) is None:
                raise ValueError(f"系列不存在: {set_id}")
            set_stmt = set_stmt.where(Set.set_id == set_id)
            card_stmt = card_stmt.where(Card.set_id == set_id)
        sets = list(session.scalars(set_stmt))
        cards = list(session.scalars(card_stmt))
        relations: list[CardRelation] = []
        if cards:
            card_ids = [c.card_id for c in cards]
            rel_stmt = select(CardRelation).where(
                CardRelation.relation_type == "union_part_of",
                or_(
                    CardRelation.card_id.in_(card_ids),
                    CardRelation.related_card_id.in_(card_ids),
                ),
            )
            relations = list(session.scalars(rel_stmt))
        results = [
            check_required(cards),
            check_enums(cards, vocabs),
            check_energy(cards, vocabs, raw_dir),
            check_reconciliation(sets, cards),
            check_vunion(cards, relations),
            check_sampling(cards, raw_dir),
        ]
    engine.dispose()
    return results

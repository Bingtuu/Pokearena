"""派生计算：owner/species 拆解、rule_box、归组、进化链、deck/prize 上限。

规则来源：PRD §6.2 同名归组、§7.2 字段语义；mik mechanic/label 取值以
task 004 字段形态调查结论为准（未知取值记 question，零猜测）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ptcgdb.normalize.fields import CONFIG_DIR, Questions, UnknownEnumError

# mik mechanic → PRD rule_box_type（task 004 实测：GX / Prism Star / null）
MECHANIC_RULE_BOX = {
    "GX": "gx",
    "Prism Star": "prism_star",
}

# mik label → effect_tags 粗粒度标签（task 004 实测：Ultra Beast=究极异兽）
LABEL_TAGS = {
    "Ultra Beast": "究极异兽",
}

# 被 rule_box 消费、不进 effect_tags 的 label（task 005 实测：TAG TEAM GX
# 卡 mechanic="GX" + label=["TAG TEAM"]，CSM2aC/CSM2DC；PRD §7.2 prize=3）
RULE_BOX_LABELS = {"TAG TEAM"}

# name_full 规则后缀（拆 species 用；ex/GX 后缀不同的卡规则上不同名，见 §6.2）
RULE_SUFFIXES = ("GX", "◇", "ex", "V-UNION", "VMAX", "VSTAR", "V")

# 奖赏卡数（PRD §7.2：默认 1；ex/GX=2；tag_team_gx/v_union=3；mega_ex=3 前瞻）
PRIZE_BY_RULE_BOX = {
    "ex": 2,
    "gx": 2,
    "tag_team_gx": 3,
    "v_union": 3,
    "mega_ex": 3,
    "v": 2,
    "vmax": 3,
    "vstar": 2,
}

# 卡组同名上限（PRD §7.2：默认 4；ACE SPEC/光辉/V-UNION 部件/◇=1）
DECK_LIMIT_BY_RULE_BOX = {
    "prism_star": 1,  # ◇ 卡面规则：同名◇卡卡组中只能放 1 张
    "radiant": 1,
    "v_union": 1,
}

# 基本能量 9 种属性（task 005 CSM1DC 实测 9 种，含妖：DAR/FAI/FIG/FIR/GRA/LIG/MET/PSY/WAT）
BASIC_ENERGY_TYPES = ["草", "火", "水", "雷", "超", "斗", "恶", "钢", "妖"]


def load_name_group_rules(config_dir: Path | None = None) -> list[dict[str, str]]:
    """读取 config/name_group_rules.yml 的 same_name 规则（PRD §6.2）。"""
    config_dir = Path(config_dir) if config_dir else CONFIG_DIR
    data = yaml.safe_load(
        (config_dir / "name_group_rules.yml").read_text(encoding="utf-8")
    )
    return list(data.get("same_name") or [])


def split_owner_species(
    name_full: str, owners: list[str]
) -> tuple[str | None, str]:
    """拆 owner 前缀与规则后缀 → (owner, species)。

    owner 前缀形如 "火箭队的X"；species 去掉 GX/◇/ex 等规则后缀。
    "阿罗拉 X" 是地区形态而非 owner，不拆解（保留在 species 内）。
    """
    owner = None
    rest = name_full
    for o in owners:
        prefix = f"{o}的"
        if name_full.startswith(prefix):
            owner = o
            rest = name_full[len(prefix):]
            break
    for suffix in RULE_SUFFIXES:
        if rest.endswith(suffix):
            rest = rest[: -len(suffix)]
            break
    return owner, rest


def derive_rule_box(
    mechanic: str | None,
    label: list[str] | None,
    questions: Questions,
    card_id: str,
) -> tuple[str | None, list[str] | None]:
    """mechanic/label → (rule_box_type, effect_tags)。未知取值记 question 不猜测。"""
    labels = label or []
    rule_box_type = None
    if mechanic:
        try:
            rule_box_type = MECHANIC_RULE_BOX[mechanic]
        except KeyError:
            questions.add(card_id, "mechanic", mechanic, "未知 mechanic，rule_box_type 置空")
    # TAG TEAM GX：mechanic="GX" + label 含 "TAG TEAM" → tag_team_gx（prize=3）
    if mechanic == "GX" and "TAG TEAM" in labels:
        rule_box_type = "tag_team_gx"
    tags: list[str] = []
    for item in labels:
        if item in RULE_BOX_LABELS:
            continue  # 已被 rule_box 消费，不进 effect_tags
        try:
            tags.append(LABEL_TAGS[item])
        except KeyError:
            questions.add(card_id, "label", item, "未知 label，未映射 effect_tags")
    return rule_box_type, (tags or None)


def derive_deck_limit(rule_box_type: str | None, is_ace_spec: bool) -> int:
    if is_ace_spec:
        return 1
    if rule_box_type and rule_box_type in DECK_LIMIT_BY_RULE_BOX:
        return DECK_LIMIT_BY_RULE_BOX[rule_box_type]
    return 4


def derive_prize_cards(rule_box_type: str | None) -> int:
    if rule_box_type and rule_box_type in PRIZE_BY_RULE_BOX:
        return PRIZE_BY_RULE_BOX[rule_box_type]
    return 1


def derive_is_tera(mechanic: str | None, label: list[str] | None, name_full: str) -> bool:
    """太晶/星晶标志。日月/剑盾无样本；按朱紫机制预留判定（mechanic/label/卡名含太晶）。"""
    haystacks = [mechanic or "", *(label or []), name_full]
    return any("太晶" in h or "Tera" in h for h in haystacks)


def derive_is_ace_spec(mechanic: str | None, label: list[str] | None, name_full: str) -> bool:
    haystacks = [mechanic or "", *(label or []), name_full]
    return any("ACE SPEC" in h for h in haystacks)


def derive_basic_energy(
    mik_card_type: str, name_full: str, questions: Questions, card_id: str
) -> tuple[bool, list[str] | None]:
    """→ (is_basic_energy, provides)。

    mik cardType="Basic Energy" 即基本能量（task 005 CSM1DC 实测）；
    "Energy" 未实测，按预置保留同路径处理。
    provides 从卡名属性词解析。特殊能量效果差异大（条件性提供属性），
    provides 置 None 并记 question，效果文本见 text_raw。
    """
    if mik_card_type in ("Basic Energy", "Energy"):
        for t in BASIC_ENERGY_TYPES:
            if t in name_full:
                return True, [t]
        questions.add(card_id, "name", name_full, "基本能量卡名未含已知属性，provides 置空")
        return True, None
    if mik_card_type == "Special Energy":
        questions.add(
            card_id, "provides", None, "特殊能量 provides 未结构化（条件性效果见 text_raw）"
        )
    return False, None


def name_group_key(name_full: str, rules: list[dict[str, str]]) -> str:
    """PRD §6.2 归组 key：默认 name_full；命中 same_name 规则（含 "base（限定语）"）归到 base。"""
    for rule in rules:
        base = rule["base"]
        if name_full == base or name_full.startswith(f"{base}（"):
            return base
    return name_full


def resolve_evolution(
    records: list[dict[str, Any]],
    questions: Questions,
) -> None:
    """在系列内解析 evolves_from_text → evolves_from_id，并派生 evolution_chain_id。

    records 为 normalize 后的卡牌 dict（就地修改，需含 card_id/name_full/species/
    card_type/evolves_from_text 键）。同名多印刷取编号最小者；
    先按 name_full 精确匹配，再按 species 匹配（覆盖"阿罗拉 X ← X"形态）；
    系列内解析不到 → None + question（跨系列/未收录情况）。
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_species: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_name.setdefault(rec["name_full"], []).append(rec)
        if rec["card_type"] == "pokemon" and rec.get("species"):
            by_species.setdefault(rec["species"], []).append(rec)

    for rec in records:
        rec.setdefault("evolves_from_id", None)
        text = rec.get("evolves_from_text")
        if not text:
            continue
        candidates = by_name.get(text) or by_species.get(text) or []
        candidates = [c for c in candidates if c["card_id"] != rec["card_id"]]
        if candidates:
            candidates.sort(key=lambda c: c["card_id"])
            rec["evolves_from_id"] = candidates[0]["card_id"]
        else:
            rec["evolves_from_id"] = None
            questions.add(
                rec["card_id"], "evolves_from_text", text, "系列内未解析到进化前卡牌"
            )

    by_id = {rec["card_id"]: rec for rec in records}
    for rec in records:
        rec.setdefault("evolution_chain_id", None)
        if rec["card_type"] != "pokemon":
            continue
        seen = set()
        node = rec
        while node.get("evolves_from_id") and node["card_id"] not in seen:
            seen.add(node["card_id"])
            node = by_id[node["evolves_from_id"]]
        rec["evolution_chain_id"] = node["card_id"]


def evolve_relations(records: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """由 evolves_from_id 生成 card_relations 行 (card_id, related_card_id, relation_type)。"""
    rows: list[tuple[str, str, str]] = []
    for rec in records:
        src = rec.get("evolves_from_id")
        if src:
            rows.append((rec["card_id"], src, "evolves_from"))
            rows.append((src, rec["card_id"], "evolves_to"))
    return rows


__all__ = [
    "UnknownEnumError",
    "derive_basic_energy",
    "derive_deck_limit",
    "derive_is_ace_spec",
    "derive_is_tera",
    "derive_prize_cards",
    "derive_rule_box",
    "evolve_relations",
    "load_name_group_rules",
    "name_group_key",
    "resolve_evolution",
    "split_owner_species",
]

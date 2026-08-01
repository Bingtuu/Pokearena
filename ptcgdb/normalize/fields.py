"""字段映射：mik.moe card-detail → PRD §7.2 结构化字段。

红线（AGENTS.md / PRD §6.4）：
- `text_raw` 逐字保留，绝不做术语规范化；【】占位符不翻译；
- 归一只发生在结构化字段（cost / types / weakness 等），不动原文；
- 未知枚举**零猜测**：映射表里没有的取值一律记 question 并抛 `UnknownEnumError`
  或以 None 入库 + question，绝不默默吞掉。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
VOCAB_DIR = CONFIG_DIR / "vocabularies"

DAMAGE_RE = re.compile(r"^(\d+)([+\-×])?$")

# damage 修饰符合法取值（PRD §7.2：NULL / "+" / "-" / "×"）
DAMAGE_MODIFIERS = {"+", "-", "×"}


class UnknownEnumError(ValueError):
    """映射表外的未知枚举值。调用方必须记 question，不允许猜测。"""


class Questions:
    """未知值/疑点收集器（入库报告用）。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, card_id: str | None, field: str, value: Any, note: str) -> None:
        self.items.append(
            {"card_id": card_id, "field": field, "value": value, "note": note}
        )

    def __len__(self) -> int:
        return len(self.items)


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_energy_code_map(vocab_dir: Path = VOCAB_DIR) -> dict[str, str]:
    """mik 单字母码 → 中文属性名。无 mik_code 的词表条目不参与反映射。"""
    data = _load_yaml(vocab_dir / "energy_types.yml")
    return {
        entry["mik_code"]: entry["name"]
        for entry in data["types"]
        if entry.get("mik_code")
    }


def load_card_type_map(
    vocab_dir: Path = VOCAB_DIR,
) -> dict[str, tuple[str, str | None]]:
    """mik cardType → (card_type, trainer_subtype)。"""
    data = _load_yaml(vocab_dir / "card_types.yml")
    return {
        entry["mik"]: (entry["card_type"], entry.get("trainer_subtype"))
        for entry in data["card_types"]
    }


def load_stage_map(vocab_dir: Path = VOCAB_DIR) -> dict[str, str]:
    """mik pokemonAttr.stage → PRD stage。"""
    data = _load_yaml(vocab_dir / "stages.yml")
    return {entry["mik"]: entry["stage"] for entry in data["stages"]}


def load_era_map(vocab_dir: Path = VOCAB_DIR) -> dict[str, str]:
    """mik product series → PRD era。"""
    data = _load_yaml(vocab_dir / "eras.yml")
    return {entry["mik_series"]: entry["era"] for entry in data["eras"]}


def load_rarities(vocab_dir: Path = VOCAB_DIR) -> set[str]:
    return set(_load_yaml(vocab_dir / "rarities.yml")["rarities"])


def load_owners(vocab_dir: Path = VOCAB_DIR) -> list[str]:
    return list(_load_yaml(vocab_dir / "owners.yml")["owners"])


def load_rule_box_types(vocab_dir: Path = VOCAB_DIR) -> set[str]:
    return set(_load_yaml(vocab_dir / "rule_box_types.yml")["rule_box_types"])


def map_energy(code: str, code_map: dict[str, str]) -> str:
    """单字母码 → 中文属性。未知码抛 UnknownEnumError（调用方记 question）。"""
    try:
        return code_map[code]
    except KeyError:
        raise UnknownEnumError(f"未知能量/属性码: {code!r}") from None


def parse_cost(cost: str | None, code_map: dict[str, str]) -> list[dict[str, Any]]:
    """cost 编码串 → [{type, count}]，按连续相同码分组、保序（PRD §7.2 示例）。

    "" / "0"（无费用招式，CSM1aC 实测）→ []。含追加标记 "+" 的串请用
    parse_cost_full（本函数对 "+" 抛 UnknownEnumError，不静默丢弃）。
    """
    items, modifier = parse_cost_full(cost, code_map)
    if modifier is not None:
        raise UnknownEnumError(f"cost 含追加标记 {modifier!r}，请用 parse_cost_full: {cost!r}")
    return items


def parse_cost_full(
    cost: str | None, code_map: dict[str, str]
) -> tuple[list[dict[str, Any]], str | None]:
    """cost 编码串 → ([{type, count}] 保序, cost_modifier)。

    尾部 "+" = 追加费用标记（TAG TEAM GX 实测 "WWC+"，CSM2aC：追加 3 个【水】
    能量则追加效果，卡面文本在 effect_text）。"+" 出现在非尾部 → UnknownEnumError。
    """
    if not cost or cost == "0":
        return [], None
    modifier = None
    body = cost
    if body.endswith("+"):
        modifier = "+"
        body = body[:-1]
    if not body or body == "0":
        # 无费用招式可带追加标记（"0+"，CSM2bC 臭臭泥&阿罗拉臭臭泥GX 实测）
        return [], modifier
    result: list[dict[str, Any]] = []
    for ch in body:
        type_name = map_energy(ch, code_map)
        if result and result[-1]["type"] == type_name:
            result[-1]["count"] += 1
        else:
            result.append({"type": type_name, "count": 1})
    return result, modifier


def parse_damage(damage: str | None) -> tuple[int | None, str | None]:
    """damage "20"/"20+"/"20×"/"" → (damage_base, damage_modifier)。"""
    if not damage:
        return None, None
    match = DAMAGE_RE.fullmatch(damage.strip())
    if not match:
        raise UnknownEnumError(f"无法解析的 damage 形态: {damage!r}")
    base = int(match.group(1))
    modifier = match.group(2)
    return base, modifier


def parse_attack(
    raw: dict[str, Any], code_map: dict[str, str]
) -> dict[str, Any]:
    """mik pokemonAttr.attack[] 条目 → PRD §7.2 attacks 子结构。

    cost_modifier：cost 尾部追加标记（TAG TEAM GX "WWC+"，CSM2aC 实测），
    PRD §7.2 attacks 子结构的增量字段（字段只加不删）。
    """
    base, modifier = parse_damage(raw.get("damage"))
    cost, cost_modifier = parse_cost_full(raw.get("cost"), code_map)
    return {
        "name": raw.get("name") or "",
        "cost": cost,
        "cost_modifier": cost_modifier,
        "damage_base": base,
        "damage_modifier": modifier,
        # 招式效果文本逐字保留，不规范化
        "effect_text": raw.get("text") or "",
    }


def parse_weak_res(
    raw: dict[str, Any] | None, code_map: dict[str, str]
) -> dict[str, Any] | None:
    """weakness/resistance {energy, value} → {type, value}；value 按卡面原样存字符串。"""
    if not raw:
        return None
    value = raw.get("value")
    return {"type": map_energy(raw["energy"], code_map), "value": str(value)}


def map_card_type(
    mik_card_type: str, card_type_map: dict[str, tuple[str, str | None]]
) -> tuple[str, str | None]:
    """mik cardType → (card_type, trainer_subtype)。未知抛 UnknownEnumError。"""
    try:
        return card_type_map[mik_card_type]
    except KeyError:
        raise UnknownEnumError(f"未知 cardType: {mik_card_type!r}") from None


def map_stage(mik_stage: str | None, stage_map: dict[str, str]) -> str | None:
    if not mik_stage:
        return None
    try:
        return stage_map[mik_stage]
    except KeyError:
        raise UnknownEnumError(f"未知 stage: {mik_stage!r}") from None


def split_number(card_index: str, cards_num: int | None) -> tuple[str, str]:
    """cardIndex → (number, number_display)。number 保留前导零。"""
    number = str(card_index)
    display = f"{number}/{cards_num}" if cards_num else number
    return number, display

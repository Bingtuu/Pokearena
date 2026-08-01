"""核心 Pydantic 模型：Card / Set / LegalitySnapshot 及 cards 表 JSON 子结构。

字段对应 PRD §7（cards 的 attacks/weakness/resistance 语义以 §7.2 JSON 示例为准）。
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AttackCost(BaseModel):
    """招式能量费用单元，保序组成 cost 数组。"""

    model_config = ConfigDict(frozen=True)

    type: str  # 属性（词表 config/vocabularies/energy_types.yml）
    count: int


class Attack(BaseModel):
    """招式（PRD §7.2 attacks 示例）。"""

    model_config = ConfigDict(frozen=True)

    name: str
    cost: list[AttackCost]
    damage_base: int | None  # 卡面固定伤害；无固定伤害时为 None
    damage_modifier: str | None  # NULL / "+" / "-" / "×"
    effect_text: str


class Ability(BaseModel):
    """特性（兼容一卡多特性）。"""

    model_config = ConfigDict(frozen=True)

    name: str
    text: str


class Weakness(BaseModel):
    """弱点，value 按卡面原样存字符串（"×2"）。"""

    model_config = ConfigDict(frozen=True)

    type: str
    value: str


class Resistance(BaseModel):
    """抵抗力，value 按卡面原样存字符串（"-30"）。"""

    model_config = ConfigDict(frozen=True)

    type: str
    value: str


class Card(BaseModel):
    """cards 卡牌主表导出形状（SDK 返回类型）。"""

    model_config = ConfigDict(frozen=True)

    card_id: str
    set_id: str
    number: str
    number_display: str
    name_full: str
    species: str | None
    owner: str | None
    card_type: str
    regulation_mark: str | None  # 无赛制标记（基本能量）为 None
    rarity: str
    stage: str | None
    hp: int | None
    types: list[str] | None
    evolves_from_text: str | None
    evolves_from_id: str | None
    evolution_chain_id: str | None
    rule_box_type: str | None
    has_rule_box: bool
    is_tera: bool
    union_position: str | None
    prize_cards: int
    deck_limit: int
    is_ace_spec: bool
    abilities: list[Ability] | None
    attacks: list[Attack] | None
    weakness: Weakness | None
    resistance: Resistance | None
    retreat_cost: int | None
    trainer_subtype: str | None
    provides: list[str] | None
    is_basic_energy: bool
    text_raw: str
    effect_tags: list[str] | None
    name_en: str | None
    name_ja: str | None
    name_zh_tw: str | None
    source: str
    fetched_at: datetime
    status: str


class Set(BaseModel):
    """sets 系列表导出形状。"""

    model_config = ConfigDict(frozen=True)

    set_id: str
    name_zh: str
    era: str
    release_date: date | None
    regulation_mark: str
    expected_count: int | None
    expected_secret_count: int | None
    source: str
    fetched_at: str


class LegalitySnapshot(BaseModel):
    """legality_snapshots 环境快照导出形状。"""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    format: str
    effective_from: date
    effective_to: date | None
    allowed_marks: list[str]
    allowed_basic_energy_types: list[str]
    whitelist_cards: list[dict]
    banned_cards: list[dict]
    mark_overrides: list[dict]
    latest_text_overrides: dict[str, str]
    source_url: str | None
    created_at: datetime

"""核心 Pydantic 模型：Card / Set / LegalitySnapshot 及 cards 表 JSON 子结构。

字段对应 PRD §7（cards 的 attacks/weakness/resistance 语义以 §7.2 JSON 示例为准）。
"""

from datetime import date, datetime
from typing import Any

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
    # 追加费用标记（TAG TEAM GX "WWC+" → "+"；v1.4 增量，只加不删）
    cost_modifier: str | None = None
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
    alias_of: str | None = None  # mik 双重列示别名→正本 card_id（v1.11 增量，只加不删）
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
    card_face_total: int | None = None  # 卡面分母种子（v1.11 增量，只加不删）
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
    latest_text_overrides: dict[str, Any]
    source_url: str | None
    created_at: datetime


class ErrataRecord(BaseModel):
    """errata 官方勘误导出形状（legality.json data.errata）。"""

    model_config = ConfigDict(frozen=True)

    errata_id: str
    card_id: str
    effective_from: date
    corrected_text: str
    notice_url: str | None


class LegalityPool(BaseModel):
    """legal_at 返回的合法卡池（FR-3.1 / FR-8）。"""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    format: str
    date: date
    card_ids: frozenset[str]
    by_name_group: dict[str, list[str]]  # 白名单命中的组 → 该组全部入库印刷行


class EffectiveText(BaseModel):
    """effective_text 返回的有效文本（FR-3.3 / FR-8）。"""

    model_config = ConfigDict(frozen=True)

    card_id: str  # 请求的卡
    resolved_card_id: str  # 实际文本来源卡（经 latest_text_overrides 解析）
    text: str
    source: str  # errata / latest_print / text_raw


class Violation(BaseModel):
    """validate_deck / 计数引擎的结构化违规（FR-3.4 / FR-8，v1.7 语义全集）。

    kind ∈ {deck_size, unknown_card, not_legal, banned, name_limit,
            ace_spec_limit, radiant_limit, evolution_chain(预留)}
    """

    model_config = ConfigDict(frozen=True)

    kind: str  # 违规类型（开放字符串，PRD FR-8 语义表）
    detail: str  # 人类可读说明
    cards: list[str]  # 涉及的 card_id（排序去重）
    count: int | None = None  # 实际数量（供 AI 策略消费）


class DeckReport(BaseModel):
    """validate_deck 返回的卡组校验报告（FR-8，task 026）。

    结构化 violations 不抛异常（AI 策略消费）；ok = 无任何违规。
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    deck_size: int
    format: str
    date: date
    snapshot_id: str
    violations: list[Violation]


class CardStat(BaseModel):
    """stats_* 返回的单组统计（PRD FR-9.7 / FR-8 v1.10）。

    value 为指标值（WUR / WR / WWS，float64 全精度）；n 为样本量
    （usage/wws-b=携带出战条目数，a 层=对局数）；basis/layer 为口径标签；
    n < min_n 时 low_confidence=True。
    """

    model_config = ConfigDict(frozen=True)

    group_key: str  # name_group 归组 key（规范化完整卡名）
    display_name: str
    value: float
    n: int
    basis: str = ""  # decks / copies（usage 口径标签）
    layer: str = ""  # a / b（winrate/wws 口径标签）
    low_confidence: bool = False


class CardDrilldown(BaseModel):
    """stats_card 单卡逐赛事钻取行（PRD FR-9.7）。"""

    model_config = ConfigDict(frozen=True)

    tournament_id: str
    tournament_name: str
    date: str
    tier: str | None
    n_decks: int  # 携带该组的出战条目数
    weighted_carry: float  # 名次权重携带份额 Σ w̃
    topcut_decks: int  # top-cut 携带数（rank ≤ topcut_slots）
    best_rank: int


class StatsResult(BaseModel):
    """stats_usage / stats_winrate / stats_wws 返回（PRD FR-9.7 SDK 包装）。

    meta 回显 as_of/窗口/scope/division/口径标签/词表 hash（FR-9.6 as_of 回显契约）。
    """

    model_config = ConfigDict(frozen=True)

    meta: dict[str, Any]
    data: list[CardStat]


class DrilldownResult(BaseModel):
    """stats_card 返回（meta + 逐赛事钻取行）。"""

    model_config = ConfigDict(frozen=True)

    meta: dict[str, Any]
    data: list[CardDrilldown]

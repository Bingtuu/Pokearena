"""全部表定义（PRD §7.1 ~ §7.3）。

枚举一律开放字符串（词表见 config/vocabularies/），不落合法性布尔值。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ptcgdb.orm.base import Base


class Set(Base):
    """sets 系列表（PRD §7.1）。"""

    __tablename__ = "sets"

    set_id: Mapped[str] = mapped_column(String, primary_key=True)  # 商品编号，如 CSV1C
    name_zh: Mapped[str] = mapped_column(String)  # 系列名
    era: Mapped[str] = mapped_column(String)  # 太阳&月亮/剑&盾/朱&紫/特典/未划分（开放词表）
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    regulation_mark: Mapped[str] = mapped_column(String)  # 该系列卡牌的赛制标记
    # 官方公布收录数（mik cardsNum 全量口径，≠卡面分母）
    expected_count: Mapped[int | None] = mapped_column(Integer)
    expected_secret_count: Mapped[int | None] = mapped_column(Integer)  # 官方公布的编号外卡数
    # 卡面分母种子（v1.11；NULL=未覆盖）
    card_face_total: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)  # 溯源
    fetched_at: Mapped[str] = mapped_column(String)  # PRD §7.1 定为 TEXT


class Card(Base):
    """cards 卡牌主表（PRD §7.2）。

    card_id = {set_id}-{number}；同号异画/促销复刻追加 -a/-b 后缀并人工登记。
    """

    __tablename__ = "cards"

    card_id: Mapped[str] = mapped_column(String, primary_key=True)
    set_id: Mapped[str] = mapped_column(ForeignKey("sets.set_id"), index=True)
    number: Mapped[str] = mapped_column(String)  # 纯序号，保留前导零
    number_display: Mapped[str] = mapped_column(String)  # 卡面印刷编号，如 009/127
    name_full: Mapped[str] = mapped_column(String, index=True)  # 完整卡名（含 ex/火箭队前后缀）
    species: Mapped[str | None] = mapped_column(String, index=True)  # 宝可梦种名（检索用）
    owner: Mapped[str | None] = mapped_column(String)  # 训练家宝可梦归属（开放词表）
    card_type: Mapped[str] = mapped_column(String)  # pokemon / trainer / energy
    # 卡面原值；无赛制标记（基本能量）存 NULL
    regulation_mark: Mapped[str | None] = mapped_column(String, index=True)
    rarity: Mapped[str] = mapped_column(String)  # 罕贵度（开放词表）
    stage: Mapped[str | None] = mapped_column(String)  # 基础/1阶/2阶/超级进化…（开放）
    hp: Mapped[int | None] = mapped_column(Integer)
    types: Mapped[list[str] | None] = mapped_column(JSON)  # 属性数组（前瞻兼容双属性）
    evolves_from_text: Mapped[str | None] = mapped_column(String)  # 卡面印刷原文
    evolves_from_id: Mapped[str | None] = mapped_column(ForeignKey("cards.card_id"))
    evolution_chain_id: Mapped[str | None] = mapped_column(String)  # 派生：同链共享 ID
    rule_box_type: Mapped[str | None] = mapped_column(String)  # ex/gx/…/mega_ex（开放词表）
    has_rule_box: Mapped[bool] = mapped_column(Boolean)  # 派生查询位
    is_tera: Mapped[bool] = mapped_column(Boolean, index=True)  # 太晶/星晶标志
    union_position: Mapped[str | None] = mapped_column(String)  # V-UNION 方位：左上/右上/左下/右下
    prize_cards: Mapped[int] = mapped_column(Integer, default=1)  # 昏厥时对手获得奖赏卡数
    deck_limit: Mapped[int] = mapped_column(Integer, default=4)  # 卡面/机制固有上限
    is_ace_spec: Mapped[bool] = mapped_column(Boolean)
    abilities: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)  # [{name, text}]
    attacks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)  # 结构见 PRD §7.2 示例
    weakness: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {type, value}
    resistance: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {type, value}
    retreat_cost: Mapped[int | None] = mapped_column(Integer)
    trainer_subtype: Mapped[str | None] = mapped_column(String)  # 物品/支援者/竞技场/宝可梦道具
    provides: Mapped[list[str] | None] = mapped_column(JSON)  # 能量卡提供的能量类型数组
    is_basic_energy: Mapped[bool] = mapped_column(Boolean, index=True)  # 派生：基本能量
    text_raw: Mapped[str] = mapped_column(Text)  # 卡面全部文字逐字保留，绝不规范化
    effect_tags: Mapped[list[str] | None] = mapped_column(JSON)  # 粗粒度标签（PRD §6.4）
    # mik 双重列示别名→正本（v1.11）
    alias_of: Mapped[str | None] = mapped_column(ForeignKey("cards.card_id"))
    name_en: Mapped[str | None] = mapped_column(String)  # 跨语言映射（Phase 2 填充）
    name_ja: Mapped[str | None] = mapped_column(String)
    name_zh_tw: Mapped[str | None] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)  # official_miniprogram / mik_moe / manual…
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, index=True)  # draft / active / deprecated


class CardRelation(Base):
    """card_relations 卡牌关系（PRD §6.3 / §7.3）。

    relation_type ∈ {evolves_from, evolves_to, mentions, reprint_of, union_part_of, name_group}
    """

    __tablename__ = "card_relations"

    card_id: Mapped[str] = mapped_column(ForeignKey("cards.card_id"), primary_key=True)
    related_card_id: Mapped[str] = mapped_column(
        ForeignKey("cards.card_id"), primary_key=True, index=True
    )
    relation_type: Mapped[str] = mapped_column(String, primary_key=True)
    confidence: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)


class NameGroup(Base):
    """name_groups 同名归组（PRD §6.2）。"""

    __tablename__ = "name_groups"

    group_key: Mapped[str] = mapped_column(String, primary_key=True)  # 规范化完整卡名
    display_name: Mapped[str] = mapped_column(String)
    rule_note: Mapped[str | None] = mapped_column(String)  # 特殊规则注释


class CardNameGroup(Base):
    """cards_name_group：卡牌 ↔ 同名组。"""

    __tablename__ = "cards_name_group"

    card_id: Mapped[str] = mapped_column(ForeignKey("cards.card_id"), primary_key=True)
    group_key: Mapped[str] = mapped_column(
        ForeignKey("name_groups.group_key"), primary_key=True
    )


class LegalitySnapshot(Base):
    """legality_snapshots 环境快照（PRD §7.3）。旧快照永不删除，历史快照 override 冻结。"""

    __tablename__ = "legality_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    format: Mapped[str] = mapped_column(String)  # standard / open（开放字符串）
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    allowed_marks: Mapped[list[str]] = mapped_column(JSON)  # ["G","H","I"]
    allowed_basic_energy_types: Mapped[list[str]] = mapped_column(JSON)  # 开放赛制含"妖"
    whitelist_cards: Mapped[list[dict[str, Any]]] = mapped_column(JSON)  # [{name_full, note}]
    banned_cards: Mapped[list[dict[str, Any]]] = mapped_column(JSON)  # [{name, ability_or_attack}]
    mark_overrides: Mapped[list[dict[str, Any]]] = mapped_column(JSON)  # [{card_id, mark, note}]
    latest_text_overrides: Mapped[dict[str, Any]] = mapped_column(JSON)  # 旧卡 → 最新文本 card_id
    source_url: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Errata(Base):
    """errata 官方勘误（不覆盖 text_raw）。"""

    __tablename__ = "errata"

    errata_id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.card_id"))
    effective_from: Mapped[date] = mapped_column(Date)
    corrected_text: Mapped[str] = mapped_column(Text)
    notice_url: Mapped[str | None] = mapped_column(String)


class RulesDocument(Base):
    """rules_documents 规则书/赛场规则/公告。"""

    __tablename__ = "rules_documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    version_label: Mapped[str | None] = mapped_column(String)
    effective_from: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String)
    local_path: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)


class ScrapeRun(Base):
    """scrape_runs 采集批次日志（FR-1.4 三清单 + manifest）。"""

    __tablename__ = "scrape_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    card_count: Mapped[int | None] = mapped_column(Integer)
    ok_count: Mapped[int | None] = mapped_column(Integer)
    question_count: Mapped[int | None] = mapped_column(Integer)
    missing_count: Mapped[int | None] = mapped_column(Integer)
    lists_path: Mapped[str | None] = mapped_column(String)  # 三清单文件路径
    status: Mapped[str] = mapped_column(String)
    manifest_hash: Mapped[str | None] = mapped_column(String)


class ExternalId(Base):
    """external_ids 跨语言对齐（Phase 2）。

    system ∈ {mik_en, tcgdex, pokemon_card_jp}（PRD v1.5）——system 本身编码
    置信度来源路径：mik_en=英文桥直取（bridge）、tcgdex=TCGdex 同 ID 链出
    （tcgdex-linked）、pokemon_card_jp=官方卡查核对（manual）。
    """

    __tablename__ = "external_ids"

    card_id: Mapped[str] = mapped_column(ForeignKey("cards.card_id"), primary_key=True)
    system: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str] = mapped_column(String)


class Meta(Base):
    """meta 库级元信息（FR-6.1），如 schema_version。"""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


# 复合索引（PRD §7.3 索引段）；单字段索引用 mapped_column(index=True) 声明。
Index(
    "ix_legality_snapshots_format_effective_from",
    LegalitySnapshot.format,
    LegalitySnapshot.effective_from,
)

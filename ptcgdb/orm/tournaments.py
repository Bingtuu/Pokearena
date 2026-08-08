"""赛事卡组四表 ORM（PRD §7.5 v1.10 续，FR-9；task 027）。

主键口径 {source}:{源侧id}（FR-9.6 防跨源碰撞）；枚举一律开放字符串，
tier/division 词表见 config/vocabularies/tournament_tiers.yml。
**decks = 卡组内容实体**（mik deckId 实测按内容去重，多名选手/多场赛事共用）；
名次/积分/选手/战绩挂 deck_appearances 出战条目。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ptcgdb.orm.base import Base


class Tournament(Base):
    """tournaments 赛事表（PRD §7.5）。

    tier_coef 物化自词表（FR-9.6 事实完整性：SQL 消费方免读词表）；未知 tier 置 None。
    """

    __tablename__ = "tournaments"

    tournament_id: Mapped[str] = mapped_column(String, primary_key=True)  # {source}:{源侧id}
    source: Mapped[str] = mapped_column(String)  # mik_moe / limitless / pokemon_card_jp
    series_id: Mapped[str | None] = mapped_column(String)  # mik 系列 id
    name: Mapped[str] = mapped_column(String)
    tier: Mapped[str | None] = mapped_column(String)  # 开放词表 tournament_tiers.yml
    tier_coef: Mapped[float | None] = mapped_column(Float)
    division: Mapped[str | None] = mapped_column(String)  # master/senior/junior
    date: Mapped[date | None] = mapped_column(Date)  # 举办日
    location: Mapped[str | None] = mapped_column(String)
    participant_count: Mapped[int | None] = mapped_column(Integer)
    topcut_slots: Mapped[int | None] = mapped_column(Integer)  # 淘汰赛名额
    format: Mapped[str | None] = mapped_column(String)  # standard / open
    regulation_mark: Mapped[str | None] = mapped_column(String)  # 赛制标记区间（GHI…）
    format_end: Mapped[str | None] = mapped_column(String)  # 截止系列（CSV10C）
    env: Mapped[str | None] = mapped_column(String)  # 赛制标记集合（GHI…），日期∩日历段推导
    is_qual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # 预赛场次
    is_team: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # 双卡组赛
    official_url: Mapped[str | None] = mapped_column(String)  # 官方公告链接
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

    appearances: Mapped[list[DeckAppearance]] = relationship(back_populates="tournament")


class Deck(Base):
    """decks 卡组内容实体（PRD §7.5 v1.10 续）：同一套 60 张清单全源一行。

    mik deckId 实测为内容实体（按内容去重）；variant 归类为内容级属性
    （deck/detail 的 variant 字段）。
    """

    __tablename__ = "decks"

    deck_id: Mapped[str] = mapped_column(String, primary_key=True)  # {source}:{源侧id}
    archetype_id: Mapped[str | None] = mapped_column(String)  # variantId / 自动归类 id
    archetype_name: Mapped[str | None] = mapped_column(String)  # 卡组归类名
    deck_code: Mapped[str | None] = mapped_column(String)  # 小程序分享码
    mapping_status: Mapped[str] = mapped_column(String)  # full / partial / unmapped
    mapped_ratio: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

    appearances: Mapped[list[DeckAppearance]] = relationship(back_populates="deck")
    cards: Mapped[list[DeckCard]] = relationship(back_populates="deck")


class DeckAppearance(Base):
    """deck_appearances 出战条目：一套内容在一次赛事取得的一个名次。

    统计"卡组数"的口径单元（FR-9.4）；player_ref 只存官方选手编号（隐私最小化）。
    """

    __tablename__ = "deck_appearances"

    deck_id: Mapped[str] = mapped_column(ForeignKey("decks.deck_id"), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(
        ForeignKey("tournaments.tournament_id"), primary_key=True, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    points: Mapped[float | None] = mapped_column(Float)
    player_ref: Mapped[str | None] = mapped_column(String)  # pinCode
    record_wins: Mapped[int | None] = mapped_column(Integer)  # A 层逐局战绩（Limitless）
    record_losses: Mapped[int | None] = mapped_column(Integer)
    record_ties: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

    deck: Mapped[Deck] = relationship(back_populates="appearances")
    tournament: Mapped[Tournament] = relationship(back_populates="appearances")


class Pairing(Base):
    """pairings 逐桌对阵（PRD §7.5 v1.14，task 028）。

    WR A 层与镜像剔除的事实源（Phase 4 前置资产）；winner NULL=平局或未报（不猜）。
    列名 table_no 避 SQLite 关键字 table；round 同名属性显式映射列名。
    """

    __tablename__ = "pairings"

    tournament_id: Mapped[str] = mapped_column(
        ForeignKey("tournaments.tournament_id"), primary_key=True
    )
    phase: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1=瑞士轮 2=淘汰赛
    round: Mapped[int] = mapped_column("round", Integer, primary_key=True)
    table_no: Mapped[int] = mapped_column(Integer, primary_key=True)  # 桌号
    player1: Mapped[str] = mapped_column(String)  # 源侧选手标识（limitless 用户名）
    player2: Mapped[str] = mapped_column(String)
    winner: Mapped[str | None] = mapped_column(String)  # NULL=平局或未报（不猜）
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)


class DeckCard(Base):
    """deck_cards 卡组构成（PRD §7.5）。

    保真全量 60 张（含能量）；card_id 可空——映射不上不猜，raw_name 保真（FR-9.2）。
    stat_scope 为派生过滤位（pokemon / supporter / stadium / other，FR-9.3）。
    """

    __tablename__ = "deck_cards"

    deck_id: Mapped[str] = mapped_column(
        ForeignKey("decks.deck_id"), primary_key=True
    )
    card_id: Mapped[str | None] = mapped_column(
        ForeignKey("cards.card_id"), primary_key=True, index=True, nullable=True
    )
    count: Mapped[int] = mapped_column(Integer)
    raw_name: Mapped[str] = mapped_column(String, primary_key=True)
    stat_scope: Mapped[str] = mapped_column(String)

    deck: Mapped[Deck] = relationship(back_populates="cards")

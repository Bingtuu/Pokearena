"""赛事卡组 Pydantic 模型（PRD §7.5，task 027）：raw 响应解析的目标形状。

与三表逐列对应；字段只加不删（FR-6.2）。mapping_status / stat_scope 在解析段
只占位，由入库段按映射率与 cards 表重算（FR-9.1 / FR-9.3）。
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TournamentRecord(BaseModel):
    """tournaments 赛事表解析形状（PRD §7.5）。

    tournament_id = {source}:{源侧id}（FR-9.6）；tier_coef 物化自词表，
    未知 tier 为 None（词表外不猜，见 config/vocabularies/tournament_tiers.yml）。
    """

    model_config = ConfigDict(frozen=True)

    tournament_id: str  # mik_moe:{tournamentId}
    source: str  # mik_moe
    series_id: str | None  # mik 系列 id（源侧原值）
    name: str
    tier: str | None  # 词表归一后的规范 tier；未知保留源侧原值
    tier_coef: float | None  # 未知 tier → None（warning）
    division: str | None  # master/senior/junior；未知保留源侧原值
    date: date | None  # 举办日（源侧 endDate）
    location: str | None
    participant_count: int | None
    topcut_slots: int | None  # 淘汰赛名额；解析段无此数据，留 None
    format: str | None  # standard / open（detail regulation 小写归一）
    regulation_mark: str | None  # 赛制标记区间（GHI…）
    format_end: str | None  # 截止系列（CSV10C）
    is_qual: bool | None  # 预赛场次
    is_team: bool | None  # 双卡组/团体赛制
    official_url: str | None  # 官方公告链接（交叉核对）
    fetched_at: datetime


class DeckRecord(BaseModel):
    """decks 卡组内容实体表形状（PRD §7.5 v1.10 续）：同一套 60 张清单全源一行。"""

    model_config = ConfigDict(frozen=True)

    deck_id: str  # {source}:{源侧id}
    archetype_id: str | None  # variantId / 自动归类 id
    archetype_name: str | None
    deck_code: str | None  # 小程序分享码
    mapping_status: str  # full(≥95%) / partial / unmapped（FR-9.1）
    mapped_ratio: float | None
    source: str
    fetched_at: datetime


class AppearanceRecord(BaseModel):
    """deck_appearances 出战条目解析形状（PRD §7.5 v1.10 续）。

    一套卡组内容在一次赛事取得的一个名次：rank/points/player_ref 挂此；
    variant 归类是内容级属性（deck/detail variant），不在出战条目上。
    player_ref 只存官方选手编号 pinCode（隐私最小化，FR-9.5）；
    record_* 为 A 层逐局战绩（Limitless），mik 源恒为 None。
    """

    model_config = ConfigDict(frozen=True)

    deck_id: str  # mik_moe:{deckId}
    tournament_id: str
    rank: int | None
    points: float | None
    player_ref: str | None  # pinCode
    record_wins: int | None = None
    record_losses: int | None = None
    record_ties: int | None = None
    source: str = "mik_moe"
    fetched_at: datetime


class DeckCardRecord(BaseModel):
    """deck_cards 卡组构成解析形状（PRD §7.5）。

    card_id = {setCode}-{cardIndex} 原样拼接（不补零；基本能量 cardIndex 为字母码）；
    映射不上 card_id=None + raw_name 保真，不猜（FR-9.2）。
    """

    model_config = ConfigDict(frozen=True)

    deck_id: str
    card_id: str | None
    count: int
    raw_name: str  # 源侧原始卡名（保真）
    stat_scope: str = "other"  # 解析段占位，入库段按 cards 表派生（FR-9.3）
    group_key: str | None = None  # 导出冗余列（FR-9.7）：免联 cards_name_group

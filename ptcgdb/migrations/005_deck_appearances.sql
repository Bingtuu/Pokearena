-- 005 deck_appearances：decks 拆为「卡组内容实体 + 出战条目」（PRD §7.5 v1.10 续，task 027 实测订正）
-- 背景：mik deckId 实测为内容实体——同一套 60 张清单按内容去重，可被多名选手/
-- 多场赛事共用（真实采集 1,396 名次条目 vs 1,252 套内容；存在同一赛事两个名次
-- 共用同一 deckId 的实例）。004 的 decks（名次挂在内容上）语义不成立，重建。
-- 数据可由 raw 层重 ingest 完整恢复（raw append-only）；特性未发布，无下游。
DROP TABLE IF EXISTS deck_cards;
DROP TABLE IF EXISTS decks;

-- 卡组内容实体：同一套 60 张清单全源一行
CREATE TABLE IF NOT EXISTS decks (
    deck_id TEXT PRIMARY KEY,        -- {source}:{源侧id}（FR-9.6 防跨源碰撞）
    archetype_id TEXT,               -- variantId / 自动归类 id（内容级：deck/detail 的 variant）
    archetype_name TEXT,             -- 卡组归类名（沙奈朵…）
    deck_code TEXT,                  -- 小程序分享码（可空）
    mapping_status TEXT NOT NULL,    -- full(≥95%) / partial / unmapped（FR-9.1）
    mapped_ratio REAL,
    source TEXT NOT NULL,
    fetched_at DATETIME
);

-- 出战条目：一套内容在一次赛事取得的一个名次（统计"卡组数"的口径单元，FR-9.4）
CREATE TABLE IF NOT EXISTS deck_appearances (
    deck_id TEXT NOT NULL REFERENCES decks(deck_id),
    tournament_id TEXT NOT NULL REFERENCES tournaments(tournament_id),
    rank INTEGER NOT NULL,
    points REAL,
    player_ref TEXT,                 -- 官方选手编号（pinCode；隐私最小化，不存昵称）
    record_wins INTEGER,             -- A 层逐局战绩（Limitless；可空 = 源无此数据）
    record_losses INTEGER,
    record_ties INTEGER,
    source TEXT NOT NULL,
    fetched_at DATETIME,
    PRIMARY KEY (deck_id, tournament_id, rank)
);

-- 卡组构成（保真全量 60 张；card_id 可空——映射不上不猜，raw_name 保真）
CREATE TABLE IF NOT EXISTS deck_cards (
    deck_id TEXT NOT NULL REFERENCES decks(deck_id),
    card_id TEXT REFERENCES cards(card_id),
    count INTEGER NOT NULL,
    raw_name TEXT NOT NULL,
    stat_scope TEXT NOT NULL,        -- pokemon / supporter / stadium / other（FR-9.3）
    PRIMARY KEY (deck_id, card_id, raw_name)
);

CREATE INDEX IF NOT EXISTS ix_deck_appearances_tournament_id ON deck_appearances (tournament_id);
CREATE INDEX IF NOT EXISTS ix_deck_cards_card_id ON deck_cards (card_id);

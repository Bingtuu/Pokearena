-- 004_tournaments: 赛事卡组三表（PRD §7.5，FR-9；task 027）
-- 列与 PRD §7.5 逐列一致；IF NOT EXISTS 保证幂等。
-- 注意：物化视图 v_stat_deck_cards / v_tournament_weights 属 task 029 范围，不在本迁移。

CREATE TABLE IF NOT EXISTS tournaments (
	tournament_id  TEXT PRIMARY KEY,   -- {source}:{源侧id} 口径，防跨源碰撞（FR-9.6）
	source         TEXT NOT NULL,      -- mik_moe / limitless / pokemon_card_jp
	series_id      TEXT,               -- mik 系列 id（可空）
	name           TEXT NOT NULL,
	tier           TEXT,               -- city/advanced/super/master/cl/pjcs/regional…（开放词表 config/vocabularies/tournament_tiers.yml）
	tier_coef      REAL,               -- 物化自词表的 tier 系数；未知 tier 置 NULL
	division       TEXT,               -- master/senior/junior（开放词表）
	date           DATE,               -- 举办日
	location       TEXT,
	participant_count INTEGER,
	topcut_slots   INTEGER,            -- 淘汰赛名额（B 层 q0 分子）
	format         TEXT,               -- standard / open
	regulation_mark TEXT,              -- 赛制标记区间（GHI…）
	format_end     TEXT,               -- 截止系列（CSV10C）
	is_qual        BOOLEAN,            -- 预赛场次（统计默认排除）
	is_team        BOOLEAN,            -- 双卡组/团体赛制（统计默认排除）
	official_url   TEXT,               -- 官方公告链接（交叉核对）
	fetched_at     DATETIME
);

CREATE TABLE IF NOT EXISTS decks (
	deck_id        TEXT PRIMARY KEY,   -- {source}:{源侧id} 口径
	tournament_id  TEXT NOT NULL REFERENCES tournaments(tournament_id),
	player_ref     TEXT,               -- 官方选手编号（pinCode；隐私最小化）
	rank           INTEGER,
	points         REAL,
	record_wins    INTEGER,            -- A 层逐局战绩（Limitless；可空 = 源无此数据）
	record_losses  INTEGER,
	record_ties    INTEGER,
	archetype_id   TEXT,               -- variantId / 自动归类 id
	archetype_name TEXT,               -- 卡组归类名
	deck_code      TEXT,               -- 小程序分享码（可空）
	mapping_status TEXT NOT NULL,      -- full(≥95%) / partial / unmapped（FR-9.1）
	mapped_ratio   REAL,
	source         TEXT NOT NULL,
	fetched_at     DATETIME
);

CREATE INDEX IF NOT EXISTS ix_decks_tournament_id ON decks (tournament_id);

CREATE TABLE IF NOT EXISTS deck_cards (
	deck_id        TEXT NOT NULL REFERENCES decks(deck_id),
	card_id        TEXT REFERENCES cards(card_id),  -- 可空：映射不上不猜（FR-9.2）
	count          INTEGER NOT NULL,
	raw_name       TEXT NOT NULL,      -- 源侧原始卡名（保真）
	stat_scope     TEXT NOT NULL,      -- pokemon / supporter / stadium / other（FR-9.3）
	PRIMARY KEY (deck_id, card_id, raw_name)
);

CREATE INDEX IF NOT EXISTS ix_deck_cards_card_id ON deck_cards (card_id);

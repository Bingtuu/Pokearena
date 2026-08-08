-- 009：pairings 逐桌对阵表 + 统计视图 basis 口径列（PRD v1.14 §7.5 / FR-9.7，task 028）
-- pairings = WR A 层与镜像剔除的事实源（Phase 4 前置资产）；winner NULL=平局或未报（不猜）。
-- basis 口径：source→basis 映射（mik_moe→cn / limitless→intl_aligned /
--   pokemon_card_jp→jp），EN/JP 对齐样本不与 CN 样本混同（FR-9.1a）；
--   两视图在 006 定义基础上逐字保留原逻辑、只加 basis 列（SQLite 不支持
--   CREATE OR REPLACE VIEW，DROP 后重建）。

CREATE TABLE IF NOT EXISTS pairings (
	tournament_id  TEXT NOT NULL REFERENCES tournaments(tournament_id),
	phase          INTEGER NOT NULL,  -- 1=瑞士轮 2=淘汰赛
	round          INTEGER NOT NULL,
	table_no       INTEGER NOT NULL,  -- 桌号（列名避 SQLite 关键字 table）
	player1        TEXT NOT NULL,     -- 源侧选手标识（limitless 用户名）
	player2        TEXT NOT NULL,
	winner         TEXT,              -- 胜者选手标识；NULL=平局或未报（不猜）
	fetched_at     DATETIME,
	PRIMARY KEY (tournament_id, phase, round, table_no)
);

DROP VIEW IF EXISTS v_tournament_weights;
CREATE VIEW v_tournament_weights AS
SELECT
	tournament_id,
	name,
	tier,
	tier_coef,
	division,
	date,
	participant_count,
	topcut_slots,
	is_qual,
	is_team,
	tier_coef * log10(participant_count) AS static_weight,
	CASE source WHEN 'mik_moe' THEN 'cn' WHEN 'limitless' THEN 'intl_aligned'
	            WHEN 'pokemon_card_jp' THEN 'jp' ELSE source END AS basis
FROM tournaments;

DROP VIEW IF EXISTS v_stat_deck_cards;
CREATE VIEW v_stat_deck_cards AS
SELECT
	a.tournament_id,
	a.deck_id,
	a.rank,
	a.points,
	a.record_wins,
	a.record_losses,
	a.record_ties,
	dc.card_id,
	dc.count,
	dc.raw_name,
	dc.stat_scope,
	cng.group_key,
	CASE a.source WHEN 'mik_moe' THEN 'cn' WHEN 'limitless' THEN 'intl_aligned'
	              WHEN 'pokemon_card_jp' THEN 'jp' ELSE a.source END AS basis
FROM deck_cards dc
JOIN decks d ON d.deck_id = dc.deck_id AND d.mapping_status = 'full'
JOIN deck_appearances a ON a.deck_id = dc.deck_id
LEFT JOIN cards_name_group cng ON cng.card_id = dc.card_id
WHERE dc.stat_scope IN ('pokemon', 'supporter', 'stadium');

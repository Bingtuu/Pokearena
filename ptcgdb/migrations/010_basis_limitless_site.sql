-- 010：统计视图 basis 口径加 limitless_site→intl_aligned（task 028 主站 HTML 通道）
-- 主站人工收录（limitless_site）与 API 通道（limitless）同为 EN 官方系列赛样本，
-- basis 同归 intl_aligned（FR-9.1a：EN/JP 对齐样本不与 CN 样本混同）。
-- 两视图在 009 定义基础上逐字保留原逻辑、basis CASE 仅加一行 WHEN；
-- SQLite 不支持 CREATE OR REPLACE VIEW，DROP 后重建。

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
	            WHEN 'limitless_site' THEN 'intl_aligned'
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
	              WHEN 'limitless_site' THEN 'intl_aligned'
	              WHEN 'pokemon_card_jp' THEN 'jp' ELSE a.source END AS basis
FROM deck_cards dc
JOIN decks d ON d.deck_id = dc.deck_id AND d.mapping_status = 'full'
JOIN deck_appearances a ON a.deck_id = dc.deck_id
LEFT JOIN cards_name_group cng ON cng.card_id = dc.card_id
WHERE dc.stat_scope IN ('pokemon', 'supporter', 'stadium');

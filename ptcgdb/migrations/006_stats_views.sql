-- 006：统计物化视图（PRD v1.10 FR-9.7，task 029）
-- 视图只封装过滤与连接，不含业务公式——公式只在 canonical SQL（ptcgdb/stats/sql/）。
-- v_stat_deck_cards：deck_cards ⋈ decks ⋈ deck_appearances 三表联查 + 统计范围过滤
--   （mapping_status='full' ∧ stat_scope ∈ {pokemon,supporter,stadium}）+ group_key 预联；
--   行粒度 = 出战条目 × 卡。v_tournament_weights：赛事静态权重件
--   （tier_coef × log10(participant_count)；时间衰减因子由查询参数 as_of 在 SQL 中计算）。

CREATE VIEW IF NOT EXISTS v_tournament_weights AS
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
	tier_coef * log10(participant_count) AS static_weight
FROM tournaments;

CREATE VIEW IF NOT EXISTS v_stat_deck_cards AS
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
	cng.group_key
FROM deck_cards dc
JOIN decks d ON d.deck_id = dc.deck_id AND d.mapping_status = 'full'
JOIN deck_appearances a ON a.deck_id = dc.deck_id
LEFT JOIN cards_name_group cng ON cng.card_id = dc.card_id
WHERE dc.stat_scope IN ('pokemon', 'supporter', 'stadium');

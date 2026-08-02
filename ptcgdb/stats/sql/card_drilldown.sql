-- card_drilldown.sql — 单卡逐赛事钻取（PRD FR-9.7 stats card）
-- 每场赛事一行：携带出战条目数、名次权重携带份额、top-cut 携带数、最佳名次。
-- 参数：:group_key + 标准窗口/过滤参数（:as_of :date_from :date_to :scope :division
--       :tiers :include_qual :include_team）
WITH eligible AS (
	SELECT tournament_id, name, tier, date, topcut_slots,
	       static_weight * pow(0.5, (julianday(:as_of) - julianday(date)) / 90.0) AS w_t
	FROM v_tournament_weights
	WHERE date BETWEEN :date_from AND :date_to
	  AND (:division IS NULL OR division = :division)
	  AND (:include_qual = 1 OR is_qual = 0)
	  AND (:include_team = 1 OR is_team = 0)
	  AND (:tiers IS NULL OR INSTR(',' || :tiers || ',', ',' || tier || ',') > 0)
	  AND static_weight IS NOT NULL
),
app AS (
	SELECT a.tournament_id, a.deck_id, a.rank,
	       CASE WHEN a.points IS NOT NULL AND a.points > 0 THEN a.points
	            ELSE 1.0 / a.rank END AS w_d
	FROM deck_appearances a
	JOIN decks d ON d.deck_id = a.deck_id AND d.mapping_status = 'full'
	WHERE a.tournament_id IN (SELECT tournament_id FROM eligible)
),
norm AS (
	SELECT tournament_id, deck_id, rank,
	       w_d / SUM(w_d) OVER (PARTITION BY tournament_id) AS w_share
	FROM app
),
per_app AS (
	SELECT v.tournament_id, v.deck_id, v.rank, MAX(n.w_share) AS carry
	FROM v_stat_deck_cards v
	JOIN norm n ON n.tournament_id = v.tournament_id
	           AND n.deck_id = v.deck_id AND n.rank = v.rank
	WHERE v.group_key = :group_key
	  AND INSTR(',' || :scope || ',', ',' || v.stat_scope || ',') > 0
	GROUP BY v.tournament_id, v.deck_id, v.rank
)
SELECT e.tournament_id, e.name AS tournament_name, e.date, e.tier,
       COUNT(*) AS n_decks,
       SUM(p.carry) AS weighted_carry,
       SUM(CASE WHEN p.rank <= e.topcut_slots THEN 1 ELSE 0 END) AS topcut_decks,
       MIN(p.rank) AS best_rank
FROM per_app p
JOIN eligible e ON e.tournament_id = p.tournament_id
GROUP BY e.tournament_id
ORDER BY e.date DESC, e.tournament_id;

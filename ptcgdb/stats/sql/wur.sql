-- wur.sql — 加权出场率（PRD FR-9.4 ①，task 029 canonical SQL 单一事实源）
-- WUR(c) = Σ_t W_t·Σ_{d∋c} w̃_d / Σ_t W_t
--   w_d  = points > 0 ? points : 1/rank（出战条目名次权重）
--   w̃_d  = w_d / Σ_{d∈t} w_d（赛事内份额化，mapping_status='full' 范围内归一）
--   W_t  = tier_coef × log10(participant_count) × 0.5^((as_of - date)/90)
-- 参数：:as_of :date_from :date_to :scope(逗号串) :division :tiers(逗号串|NULL)
--       :include_qual :include_team :usage_basis('decks'|'copies')
--       :basis('cn'|'intl_aligned'|'jp'|NULL=全部，v1.14)
--       division 过滤语义（v1.14 续）：division IS NULL 的赛事不因 :division 被排除
WITH eligible AS (
	SELECT tournament_id, topcut_slots, participant_count,
	       static_weight * pow(0.5, (julianday(:as_of) - julianday(date)) / 90.0) AS w_t
	FROM v_tournament_weights
	WHERE date BETWEEN :date_from AND :date_to
	  AND (:division IS NULL OR division = :division OR division IS NULL)
	  AND (:include_qual = 1 OR is_qual = 0)
	  AND (:include_team = 1 OR is_team = 0)
	  AND (:tiers IS NULL OR INSTR(',' || :tiers || ',', ',' || tier || ',') > 0)
	  AND (:basis IS NULL OR basis = :basis)
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
per_app AS (  -- 每组 × 出战条目携带一次（decks）或按张数（copies）
	SELECT v.group_key, v.tournament_id, v.deck_id, v.rank,
	       (CASE WHEN :usage_basis = 'copies' THEN CAST(SUM(v.count) AS REAL)
	             ELSE 1.0 END) * MAX(n.w_share) AS carry
	FROM v_stat_deck_cards v
	JOIN norm n ON n.tournament_id = v.tournament_id
	           AND n.deck_id = v.deck_id AND n.rank = v.rank
	WHERE INSTR(',' || :scope || ',', ',' || v.stat_scope || ',') > 0
	  AND v.group_key IS NOT NULL
	GROUP BY v.group_key, v.tournament_id, v.deck_id, v.rank
),
agg AS (
	SELECT p.group_key, SUM(e.w_t * p.carry) AS weighted_carry, COUNT(*) AS n
	FROM per_app p
	JOIN eligible e ON e.tournament_id = p.tournament_id
	GROUP BY p.group_key
)
SELECT a.group_key, g.display_name,
       a.weighted_carry / (SELECT SUM(w_t) FROM eligible) AS value,
       a.n
FROM agg a
JOIN name_groups g ON g.group_key = a.group_key
ORDER BY value DESC, a.group_key;

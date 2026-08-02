-- wws.sql — 加权胜率（PRD FR-9.4 ③）
-- WWS(c) = WUR(c) × WR_adj(c)
--   WUR 因子恒用**全口径赛事范围**（与 wur.sql 一致，可复算契约：WWS = WUR × WR_adj）；
--   A 层（:layer='a'）：WR_adj = (W + 0.5·T + :k_a·0.5) / (W + L + T + :k_a)，k=20 等效局向 50% 收缩
--   B 层（:layer='b'）：WR_adj = (T_w + :k_b·q0) / (U_w + :k_b)，k=10 等效卡组向赛事基准
--                       转化率 q0 = Σ W_t·(slots/participants) / Σ W_t 收缩（非 0.5）；
--                       T_w/U_w/q0 只用 topcut_slots 已知的赛事（eligible_b 子范围）。
-- 参数：:as_of :date_from :date_to :scope :division :tiers :include_qual :include_team
--       :layer('a'|'b') :k_a :k_b
WITH eligible AS (  -- 全口径赛事范围（WUR 因子与出战条目归一化用）
	SELECT tournament_id, topcut_slots, participant_count,
	       static_weight * pow(0.5, (julianday(:as_of) - julianday(date)) / 90.0) AS w_t
	FROM v_tournament_weights
	WHERE date BETWEEN :date_from AND :date_to
	  AND (:division IS NULL OR division = :division)
	  AND (:include_qual = 1 OR is_qual = 0)
	  AND (:include_team = 1 OR is_team = 0)
	  AND (:tiers IS NULL OR INSTR(',' || :tiers || ',', ',' || tier || ',') > 0)
	  AND static_weight IS NOT NULL
),
eligible_b AS (  -- B 层子范围：topcut 名额已知的赛事
	SELECT * FROM eligible WHERE topcut_slots IS NOT NULL
),
app AS (
	SELECT a.tournament_id, a.deck_id, a.rank,
	       CASE WHEN a.points IS NOT NULL AND a.points > 0 THEN a.points
	            ELSE 1.0 / a.rank END AS w_d,
	       a.record_wins, a.record_losses, a.record_ties
	FROM deck_appearances a
	JOIN decks d ON d.deck_id = a.deck_id AND d.mapping_status = 'full'
	WHERE a.tournament_id IN (SELECT tournament_id FROM eligible)
),
norm AS (
	SELECT tournament_id, deck_id, rank,
	       w_d / SUM(w_d) OVER (PARTITION BY tournament_id) AS w_share,
	       record_wins, record_losses, record_ties
	FROM app
),
per_app AS (  -- 每组 × 出战条目：名次权重份额 + 逐局战绩（每组只计一次）
	SELECT v.group_key, v.tournament_id, v.deck_id, v.rank,
	       MAX(n.w_share) AS carry,
	       MAX(n.record_wins) AS wins, MAX(n.record_losses) AS losses,
	       MAX(n.record_ties) AS ties
	FROM v_stat_deck_cards v
	JOIN norm n ON n.tournament_id = v.tournament_id
	           AND n.deck_id = v.deck_id AND n.rank = v.rank
	WHERE INSTR(',' || :scope || ',', ',' || v.stat_scope || ',') > 0
	  AND v.group_key IS NOT NULL
	GROUP BY v.group_key, v.tournament_id, v.deck_id, v.rank
),
agg AS (
	SELECT p.group_key,
	       SUM(e.w_t * p.carry) AS wur_num,
	       SUM(CASE WHEN eb.tournament_id IS NOT NULL THEN e.w_t * p.carry ELSE 0.0 END) AS u_w,
	       SUM(CASE WHEN eb.tournament_id IS NOT NULL AND p.rank <= e.topcut_slots
	                THEN e.w_t * p.carry ELSE 0.0 END) AS t_w,
	       COUNT(*) AS n_apps,
	       SUM(CASE WHEN p.wins IS NOT NULL THEN p.wins ELSE 0 END) AS wsum,
	       SUM(CASE WHEN p.wins IS NOT NULL THEN p.losses ELSE 0 END) AS lsum,
	       SUM(CASE WHEN p.wins IS NOT NULL THEN p.ties ELSE 0 END) AS tsum
	FROM per_app p
	JOIN eligible e ON e.tournament_id = p.tournament_id
	LEFT JOIN eligible_b eb ON eb.tournament_id = p.tournament_id
	GROUP BY p.group_key
)
SELECT a.group_key, g.display_name,
       (a.wur_num / (SELECT SUM(w_t) FROM eligible))
       * CASE WHEN :layer = 'a'
              THEN (CAST(a.wsum AS REAL) + 0.5 * a.tsum + :k_a * 0.5)
                   / (a.wsum + a.lsum + a.tsum + :k_a)
              ELSE (a.t_w + :k_b * (SELECT SUM(w_t * 1.0 * topcut_slots / participant_count)
                                    / SUM(w_t) FROM eligible_b))
                   / (a.u_w + :k_b)
         END AS value,
       CASE WHEN :layer = 'a' THEN a.wsum + a.lsum + a.tsum ELSE a.n_apps END AS n
FROM agg a
JOIN name_groups g ON g.group_key = a.group_key
WHERE :layer = 'a' OR (SELECT count(*) FROM eligible_b) > 0  -- B 层子范围为空 → 指标不可用
ORDER BY value DESC, a.group_key;

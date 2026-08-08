-- winrate_a.sql — A 层胜率（PRD FR-9.4 ② A 层，有逐局战绩时）
-- WR(c) = (Σ wins + 0.5·Σ ties) / Σ(wins + losses + ties)
--   统计单元 = 携带 c 的出战条目中 record_wins 非空者；一对局一权重（不加权）。
-- 参数：:as_of :date_from :date_to :scope :division :tiers :include_qual :include_team
--       :basis('cn'|'intl_aligned'|'jp'|NULL=全部，v1.14)
--       division 过滤语义（v1.14 续）：division IS NULL 的赛事不因 :division 被排除
WITH eligible AS (
	SELECT tournament_id
	FROM v_tournament_weights
	WHERE date BETWEEN :date_from AND :date_to
	  AND (:division IS NULL OR division = :division OR division IS NULL)
	  AND (:include_qual = 1 OR is_qual = 0)
	  AND (:include_team = 1 OR is_team = 0)
	  AND (:tiers IS NULL OR INSTR(',' || :tiers || ',', ',' || tier || ',') > 0)
	  AND (:basis IS NULL OR basis = :basis)
	  AND static_weight IS NOT NULL
),
carrying AS (  -- 每组 × 出战条目（有 record）一行
	SELECT v.group_key, v.tournament_id, v.deck_id, v.rank,
	       MAX(v.record_wins) AS wins, MAX(v.record_losses) AS losses,
	       MAX(v.record_ties) AS ties
	FROM v_stat_deck_cards v
	WHERE v.record_wins IS NOT NULL
	  AND v.tournament_id IN (SELECT tournament_id FROM eligible)
	  AND INSTR(',' || :scope || ',', ',' || v.stat_scope || ',') > 0
	  AND v.group_key IS NOT NULL
	GROUP BY v.group_key, v.tournament_id, v.deck_id, v.rank
)
SELECT c.group_key, g.display_name,
       (CAST(SUM(c.wins) AS REAL) + 0.5 * SUM(c.ties))
         / (SUM(c.wins) + SUM(c.losses) + SUM(c.ties)) AS value,
       SUM(c.wins) + SUM(c.losses) + SUM(c.ties) AS n
FROM carrying c
JOIN name_groups g ON g.group_key = c.group_key
GROUP BY c.group_key
ORDER BY value DESC, c.group_key;

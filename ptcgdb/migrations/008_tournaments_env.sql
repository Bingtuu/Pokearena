-- 008：赛事环境推导落库（PRD FR-9.1b，task 028）
-- tournaments.env = 赛事日期 ∩ 赛区旋转日历段（config/tournament_envs.yml）
-- 推导出的赛制标记集合（如 "GHI"）；未命中 → NULL + 记 monitor 异常，不猜。
-- 历史赛事按范围收口不回填（2026-08-04 拍板），重跑 ingest-tourneys 逐场推导。

ALTER TABLE tournaments ADD COLUMN env VARCHAR;

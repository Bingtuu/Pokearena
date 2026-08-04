# 026 · validate_deck SDK 与 M7 验收

| 项 | 内容 |
|---|---|
| 状态 | DONE（2026-08-04） |
| 关联 | PRD §FR-8（DeckReport/Violation）；里程碑 M7；差异化定位 ② |
| 预估 | 1~2 天 |

## 目标

`db.validate_deck(deck, date, format) -> DeckReport` 双后端落地 + CLI + 验收——本库差异化定位的核心接口（规则语义一等公民）。

## 步骤

- [x] SDK：`validate_deck` 双后端实现（DbBackend/JsonlBackend 同一契约），返回 frozen DeckReport（结构化 violations，不抛异常）
- [x] CLI：`ptcgdb deck-check --file deck.yml --date --format`（卡表输入格式定 PRD v1.12：cards = card_id → 数量映射）
- [x] 构造用例矩阵：合法 60 张 / 59、61 张 / 同名超 4 / ACE SPEC 2 种 / 光辉 2 张 / V-UNION 部件重复 / 禁卡（open）/ 非合法标记卡 / 白名单旧卡（effective_text 场景）/ evolution_chain 违规（验证为预留不产生）
- [x] 双后端一致契约测试 + 真实赛事卡组校验（数据源：mik.moe 赛事数据库，本库赛事四表）
- [x] M7 验收 + STATUS 勾选 + CHANGELOG 更新

## 验收标准

- [x] 用例矩阵全过，双后端一致
- [x] 真实赛事卡组校验结果与人工核对一致
- [x] 全量测试绿、ruff 通过；Phase 2 收官文档同步（README/STATUS/CHANGELOG）

## 完成总结

**做了什么**：`ptcgdb/legal/deck.py` 纯函数核 `validate_deck`（组合 select_snapshot/build_pool 产物 + check_counts；合法性层 banned/not_legal 互斥、禁卡优先，逐 card_id 报告附 copies 数）；`DeckReport` frozen schema；`engine._is_banned` 改公开 `is_banned` 复用；SDK `validate_deck(deck, date, format)` 双后端同一契约（卡查找用全量卡、合法池按 active，无覆盖快照抛 LookupError）；CLI `ptcgdb deck-check --file deck.yml [--date] [--format]`（退出码 0/1/2）；卡表 YAML 格式 + PRD 升 v1.12。TDD：三测试文件均先 RED 后 GREEN。

**验收结果**：用例矩阵 14 + 双后端契约 5 + CLI 5 全绿，全量 **327 测试绿**（303→+24）、ruff 全净。真实卡组校验：1,396 条出战全量跑——快照覆盖期 **408/408 全部 ok（违规 0）**，988 条早于快照生效期（2026-07-16）如实分档 no_snapshot；负向 sanity 5 例全中（not_legal / banned 无限定 / banned 特性限定 / 两例不命中）；卡表真值人工核对 3/3 逐张一致（DB vs mik raw deck detail）。验收报告 `reports/task026-validate-deck-20260804.md`。

**与预估的偏差**：1 天内完成，无偏差。

**遗留问题**：① 快照覆盖范围仅 2026-07-16 起，历史环境（西安超级赛/高级赛夏季场 988 条出战）无覆盖快照——历史快照补录另立项；② validate_deck 逐次调用重建卡池，批量场景（1,396 次全量校验约 15~25 分钟）需调用方按日期缓存（验收脚本已示范），SDK 层批量接口暂不提供（YAGNI）。

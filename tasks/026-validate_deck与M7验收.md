# 026 · validate_deck SDK 与 M7 验收

| 项 | 内容 |
|---|---|
| 状态 | DOING（2026-08-04 启动） |
| 关联 | PRD §FR-8（DeckReport/Violation）；里程碑 M7；差异化定位 ② |
| 预估 | 1~2 天 |

## 目标

`db.validate_deck(deck, date, format) -> DeckReport` 双后端落地 + CLI + 验收——本库差异化定位的核心接口（规则语义一等公民）。

## 步骤

- [ ] SDK：`validate_deck` 双后端实现（DbBackend/JsonlBackend 同一契约），返回 frozen DeckReport（结构化 violations，不抛异常）
- [ ] CLI：`ptcgdb deck-check --file deck.yml --date --format`（卡表输入格式定 PRD v1.6）
- [ ] 构造用例矩阵：合法 60 张 / 59、61 张 / 同名超 4 / ACE SPEC 2 种 / 光辉 2 张 / V-UNION 部件重复 / 禁卡（open）/ 非合法标记卡 / 白名单旧卡（effective_text 场景）/ evolution_chain 违规
- [ ] 双后端一致契约测试 + 真实赛事卡组校验（数据源：mik.moe 赛事数据库，2023 广州大师赛以来官方积分赛卡组）
- [ ] M7 验收 + STATUS 勾选 + CHANGELOG 更新

## 验收标准

- [ ] 用例矩阵全过，双后端一致
- [ ] 真实赛事卡组校验结果与人工核对一致
- [ ] 全量测试绿、ruff 通过；Phase 2 收官文档同步（README/STATUS/CHANGELOG）

## 完成总结（DONE 时填写）

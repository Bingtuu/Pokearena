# task 026 验收报告 —— validate_deck SDK 与 M7 验收

日期：2026-08-04 · 库：data/ptcg-cn.db（user_version=7）· PRD v1.12

## 1. 单元/契约测试（全绿）

| 层 | 文件 | 用例数 | 覆盖 |
|---|---|---|---|
| 核心纯函数 | tests/test_validate_deck.py | 14 | FR-8 Violation 语义全集：合法 60 张 / 59·61 张 / 同名超 4 / ACE SPEC 2 种 / 光辉 2 张 / V-UNION 部件重复 / banned / banned 优先于 not_legal / not_legal（旧标记）/ 白名单旧卡合法 / 能量种类不合法 / unknown_card / evolution_chain 预留不产生 / 复合违规 |
| SDK 双后端 | tests/test_validate_deck_sdk.py | 5 | ok 卡组双后端 / banned+not_legal / open 赛制允许旧标记（快照选择语义）/ 混合违规 DeckReport 双后端全等 / 无覆盖快照 LookupError |
| CLI | tests/test_deck_check_cli.py | 5 | ok 退 0 / 违规退 1 / CLI 选项覆盖文件值 / 坏文件退 2 / 日期默认当天 |

全量：**327 测试全绿**（303 → +24），ruff 全净。TDD：三个测试文件均先 RED（ImportError/AttributeError/usage error）后 GREEN。

## 2. 真实赛事卡组校验（数据源：mik.moe 赛事库，本库赛事四表）

口径：校验单元 = 出战条目（deck_appearances，1,396 条，全部 format=standard）；
卡表 = deck_cards 按 count 展开 60 张（质量门已保证 60）；日期 = 赛事日期；
卡池按 (date, format) 缓存（脚本 `.scratch/task026_real_decks.py`，结果 `.scratch/task026-real-decks.json`）。

| 分档 | 条数 | 说明 |
|---|---|---|
| ok（零违规） | **408** | 2026-07-16 快照生效后的城市赛场次，**408/408 全部通过，违规 0** |
| no_snapshot | 988 | 赛事日期早于快照生效期（2026-05-31 ~ 07-15，西安超级赛/高级赛夏季场 16 场），LookupError 如实分档不猜测 |

- 408/408 一致率 100%，与「官方积分赛卡组应合法于当期环境」的预期一致。
- 违规语义在真实样本上无触发（早期环境卡组受快照覆盖范围所限）——banned/not_legal 路径由单测与下方负向 sanity 覆盖；**快照覆盖范围（仅 2026-07-16 起）是已知数据缺口**，历史环境快照补录另立项。

## 3. 负向 sanity（真实库，验证违规语义接真数据）

| 卡表 | 赛制 | 预期 | 实际 |
|---|---|---|---|
| CBB2C-0102 伊布（F 标记）+ 59 草能量 | standard 2026-08-01 | not_legal | ✅ not_legal |
| CSM1cC-137 阿塞萝拉（禁卡，无特性限定） | open 2026-08-01 | banned | ✅ banned |
| CSM1aC-060 玛夏多（攻击含「破罐破摔」，禁卡特性限定） | open 2026-08-01 | banned | ✅ banned |
| CS4.5C-059 阿塞萝拉的预感（≠禁卡「阿塞萝拉」，不同归组） | open 2026-08-01 | ok | ✅ ok |
| CS4.5C-026 玛夏多（无破罐破摔，特性限定不命中） | open 2026-08-01 | ok | ✅ ok |

禁卡名按 name_group 匹配（「阿塞萝拉」≠「阿塞萝拉的预感」，两组独立），特性限定按 abilities/attacks 名二次命中——与 task 008 A4 用例语义一致。

## 4. 卡表真值人工核对（DB vs mik raw deck detail）

抽 3 套卡组内容（mik_moe:605947 / 605987 / 655837，含跨 4 赛事复用样本）与
`data/raw/mikmoe/decks/detail/{deckId}.json` 逐张比对（card_id=setCode-cardIndex、count）：
**3/3 完全一致（各 60 张）**——validate_deck 消费的卡表与源站真值一致。

## 5. 结论

验收标准逐条：用例矩阵全过双后端一致 ✅；真实赛事卡组校验与人工核对一致 ✅；
全量测试绿、ruff 通过 ✅。**M7（同名计数引擎 + 卡组校验器 SDK）达成。**

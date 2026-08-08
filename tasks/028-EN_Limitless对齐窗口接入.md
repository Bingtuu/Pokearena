# 028 · EN Limitless 对齐窗口接入（M9-3）

| 项 | 内容 |
|---|---|
| 状态 | DOING（设计段 2026-08-04 定稿；实现段 2026-08-07 开工，环境落库首步完成） |
| 关联 | PRD §FR-9.1 / FR-9.1a / FR-9.1b（v1.13 及续）、§7.5；里程碑 M9-3；`docs/data-sources.md` §7/7b/7c/8b；`config/tournament_envs.yml` |
| 预估 | 2~3 天 |

## 目标

接入 EN Limitless 赛事卡组，**内容时代对齐简中环境**（国际已进 Mega、简中刚退 F）：只采对齐窗口内的官方系列赛上位卡组，经 name_en 桥映射简中卡池，统计仅消费 `mapping_status='full'`——不是有什么拿什么。

**范围收口（2026-08-04 拍板）**：收集与维护以**当前简中比赛环境**（standard 2026-07-16 起，G/H/I）为起点——历史赛事不回填（CN mik 2023~2026-07 场次、EN 更早赛季、历史合法性快照补录均不做）；EN 对齐窗口（2025-04~2026-04-09）日期虽在过去，但属**当前环境的参照数据**，仍是本任务采集目标；窗口随简中环境演进滚动前移（下次旋转时评审）。

**主站通道扩展（2026-08-08 拍板）**：API 通道全窗口实测仅 accepted 5 场（Limitless 是在线赛平台，官方线下大赛在 RK9 上跑，Limitless 主站人工收录其 Top Cut 卡组）——样本太薄，用户拍板扩**主站 HTML 收录通道**（`limitlesstcg.com/tournaments` 官方赛索引 + 赛事页 standings + 卡组页 data-set/data-number，docs/data-sources.md §7 已评估）。口径要点：DB source='limitless_site' 双通道区分（basis 均 intl_aligned）；standings 为全交表收录（NAIC 675 行实测），**名次截断 SITE_CUT_LIMITS**（regional/international/special ≤32、league_cup ≤8，与 CN top64 上位口径同构的截断代理，采集端与入库端共用单一事实源）；record 三列 NULL 不猜（无比分）；topcut_slots=截断后名次数；raw 落解析 JSON 快照不存原始 HTML（体量口径）；JP 国内赛事（Japan Championships/Champions League 等）拒收，JP 对齐二期再议。tier 系数四档（international=4.0/special=1.5/league_cup=1.0 推断值）2026-08-08 用户拍板采纳。

## 调研结论（2026-08-04，已落 docs/data-sources.md）

- **对齐窗口**：简中 standard = G/H/I（2026-07-16 刚退 F）↔ 国际 G/H/I 赛季 = **2025-04 旋转生效 ~ 2026-04-09**（2026-04-10 起国际 H/I/J 进 Mega）。窗口 = 成本先验，最终判据 = 卡级映射 full。
- **源**：Limitless 官方 API（tournaments/standings/decklist/pairings，匿名 50req/5min，历史翻页实测可回溯）为主；TopDeck.gg 免费 API（rounds 逐桌含局分，需 key+署名）备选补充；RK9.gg 仅对账（无 decklist）。JP 对齐二期候选 = PokecaBook/ポケカ飯（robots 放行，name_ja 桥已铺）。
- **pokemon.cn 无可机读赛果**，CN 结构化赛事源维持 mik.moe 唯一。

## 筛选口径（FR-9.1a 定稿）

- **赛事等级**：Regional / International / Special Event / League Cup ≥32 人，Master 组为主口径；线上 code 赛与小型店赛不收（样本污染）。
- **名次**：大赛 Top Cut 全量、League Cup Top 8（与 CN mik top64 上位口径同构；top-cut 转化率天然可得）。pairings 逐局数据不受名次筛选全量保留（WR A 层，可解 task 029 topcut_slots 缺口的替代口径）。
- **映射**：decklist = PTCGO set+number+英文名 → pokemon-tcg-data（ptcgoCode）→ name_en 桥 → 简中 card_id；full 进统计，partial/unmapped 落库保真（raw_name）不进统计。
- **口径标签**：EN 样本统计 `basis=intl_aligned`，不与 CN 样本混同；映射率分布随采集报告如实记录。

## 步骤

- [x] 环境落库：migration user_version 8 加 `tournaments.env` 列；推导器 = 赛事日期 ∩ `config/tournament_envs.yml` 日历段（种子已建，含 EN/JP 官方公告 source_url；CN 复用合法性快照）；未命中 → NULL + monitor 异常；落库后卡组最大赛制标记交叉校验（不符告警不拒收）——2026-08-07 完成：`normalize/envs.py` + ingest 集成，真实库 user_version=8（26 赛：10 场 GHI / 16 场历史 NULL，J 标记告警 2 例），tests/test_envs.py 9 用例
- [x] 采集器：Limitless API（赛事列表按窗口 + 名称正则归类赛事等级 → standings/decklist → pairings），限速 ≥1s/请求、断点续传、append-only raw——2026-08-07 完成：`scrapers/limitless.py`（三端点薄封装，实测校准裸数组形态，6.5s/请求对匿名 50req/5min）+ `limitless_runner.py`（窗口默认 = `envs.alignment_window()` = EN 同 CN 标记段 2025-04-11~2026-04-09，取舍决策逐场落清单）+ http.get_json + CLI `scrape limitless`；tests/test_limitless.py 28 用例；真实采集留验收段
- [x] 赛事等级归类：赛事名正则（Regional/International/Special/League Cup）+ 人数门 ≥32 + Master 组过滤；tier 词表 `config/vocabularies/tournament_tiers.yml` 扩 intl 档位（开放词表）——2026-08-07 完成：`scrapers/limitless.py` classify_tournament（MIN_PLAYERS=32）+ 词表四档（regional=1.5 有 FR-9.4 依据；international=4.0/special=1.5/league_cup=1.0 为推断值，注释标注待确认）
- [x] decklist → 简中映射管线（ptcgoCode join ptcd → name_en 桥），mapping_status 分档入库（复用赛事四表，source='limitless'）——2026-08-07 完成：`normalize/limitless.py`（ptcd 索引 + map_decklist_card 映射链：ptcd 定位/name_fallback → name_en 桥 → Basic 能量别名 → 多候选 env 优先+最新印刷+字典序，全链确定性）+ `ingest_limitless.py`（内容哈希 deck_id 天然跨赛事去重、A 层 record 三列、60 张门、env 推导+交叉校验、幂等）+ CLI `ingest-limitless`；12 用例
- [ ] 质量门与对账：60 张质量门 + 与 Limitless 主站 archetype 分布对账；映射率分布报告
- [x] 统计层：canonical SQL 口径标签加 intl_aligned；pairings 落库（WR A 层数据，Phase 4 前置资产）——2026-08-07 完成：migration 009（user_version=9）pairings 表 + 两物化视图加 basis 列（source→cn/intl_aligned/jp）；五 canonical SQL 加 `:basis` 参数（默认 cn 不混同）+ division 未知不排他语义；pairings 落库幂等 + topcut_slots 由 phase=2 去重选手数反推；CLI/SDK `--basis` + meta 回显；导出十三件套（+pairings.jsonl）；PRD 升 v1.14；tests/test_stats_basis.py 等 14 新用例
- [ ] 验收：窗口采集报告 + 测试绿 + ruff + STATUS/CHANGELOG/PRD 同步

## 验收标准

- [ ] 只入官方系列赛 + 名次筛选生效（采集报告列明每场赛事归类与取舍）
- [ ] 统计仅消费 full 映射卡组；intl_aligned 口径标签贯穿 CLI/SDK/导出
- [ ] 全量测试绿、ruff 通过

## 完成总结（DONE 时填写）

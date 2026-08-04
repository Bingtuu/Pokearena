# 简中PTCG标准环境卡牌数据库 —— 产品需求文档（PRD）与技术方案

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.12 |
| 日期 | 2026-08-01 |
| 状态 | D1 已定（M0：路线 B，tcg.mik.moe 为主源，见第 14 章）；M1~M4 已完成（Phase 1a/1b/1c + 验收 A1~A8 全过），Phase 1 收官 |
| 修订记录 | v1.1：移除卡图采集与存储（数据形态为纯文本/结构化数据）；明确交互形态为 CLI/TUI<br>v1.2：按评审意见修订——card_id 与卡号口径、编号外卡对账口径、白名单关联语义、基本能量建模；修正"宝可装置3.0/宝可齿轮3.0"同名规则来源；快照 override 冻结；JSON 字段示例、索引、服务条款风险；移除 D2<br>v1.3：按外部调研（简中赛制核查 / 开源项目对标 / 数据基建接口调研）修订——**重构基本能量合法性**（妖能量反例：标准 8 种 / 开放 9 种，进快照，废弃全局特判）；新增赛制标记**"视作"覆盖**（天空之柱视作B）、V-UNION 部件建模、`is_tera`、owner 进化封闭泛化（5 组训练家宝可梦）、开放赛制白名单（34 种）与"特别的卡牌"外链监控；**导出契约扩为七件套**（manifest/checksums/sets/relations）+ **双轨版本化**（日历版本 + schema SemVer）；新增**下游 SDK 设计**（open_db/open_jsonl 双后端、合法性一等公民函数）；技术栈调整（SQLAlchemy 2 替代 SQLModel、PRAGMA user_version 替代 Alembic）；补充 2.6 开源对标；验收标准与里程碑同步更新<br>v1.4：task 007 按赛制页正文逐名核定——开放赛制过去系列白名单 **34 种→32 种**（多出 6 种而非 8 种），§2.1/FR-5.4/A1/A4/附录 A 同步修正；种子文件 `config/legality/` 落为白名单结构化事实来源<br>v1.4（续，task 012 统一修订）：合并 M1/M2 实测偏差——①FR-2.3 对账改**条目 setCode + (setCode, cardIndex) 全局去重**口径（附赠能量卡跨系列重复列出，目录口径产生 15 个假缺口），§7.1 expected_count=mik cardsNum 含编号外卡、expected_secret_count 留 NULL；②attacks 子结构新增 **`cost_modifier`** 增量字段（TAG TEAM GX "WWC+" 追加费用，§7.2 示例同步）；③§7.1 主键口径：特典系列 product setCode='PROMO' 与目录 setId 不一致，sets 主键用目录 set_id；④FR-2.3 规则 6 本期为 DB vs raw 同源自验（单源，跨源比对待 Phase 2）、规则 1 增源数据缺失豁免（SSP-195）与基本能量标记可空豁免；⑤简中暂无太晶卡样本（§2.1 补注、A3 改样本出现后补验）；⑥task 011 已并入 legality.json `errata` 键（JSONL 后端 effective_text 用）；⑦D1 决策结果全文同步（§2.3 定位、FR-1.1/1.2 主源= mik.moe、§7.4 规模改实测值 12,420/5,320、§8 架构图、风险登记册、第 14 章改决策记录）<br>v1.4（续，task 014 实测订正）：§2.1 "特别的卡牌"外链（`/tcg-rules-regulation-extra/`）实测为**特殊机制图文说明页**（GX/棱镜之星/究极异兽/TAG TEAM/V-UNION），非"视作覆盖"清单——L1 对其只做正文 hash 监控 + needs_manual 提案，v1.3 推测作废<br>v1.5：按 2026-08-01 校验源与映射源调研（task 021）修订——**跨语言映射取消繁中方向、新增日文原版**：链路改为 简中 ──(mik raw 英文桥 `setCodeEn/cardIndexEn/nameEn`)──▶ EN ──(TCGdex 同 card ID 多语言共构)──▶ JP，官方 pokemon-card.com 卡查仅作 JP 抽样权威核对，不爬繁中站；`name_zh_tw` 保留预留不填充；**校验源矩阵更新**：TCGdex 已收录全部简中系列壳（set_id 与本库一致）但卡级数据 0%——**系列级跨源对账**（系列名+卡数）落地（FR-1.2 / FR-2.3 规则 6），卡级跨源仍待 zh-cn 实装（风险登记册跟踪）；mik.moe 赛事数据库（2023 广州大师赛以来官方积分赛卡组）列为 `validate_deck` 真实卡组校验源；`external_ids.system` 枚举改 `{mik_en, tcgdex, pokemon_card_jp}`<br>v1.5（续，排期调整）：M5 瘦身为 derive 跨系列进化解析（技术债先行）；A2/A3 卡面人工比对独立为 M8 收尾里程碑（需用户在场），M6/M7 不依赖其完成<br>v1.6：按 task 023 实测修订——**v1.5「TCGdex 同 ID 多语言共构取 JP」前提证伪**（EN/JA 卡 id 不共构，交集仅个位数；列表端点无 dexId）：§2.4 JP 映射改**名字级 dexId 链**（EN TCGdex id → pokemon-tcg-data 卡数据 `nationalPokedexNumbers` → PokéAPI 物种名表日文名 + 形态/机制开放词表；基本能量词表定名；训练家/特殊能量本里程碑不填充入 question 清单）；EN 桥 → TCGdex set 映射改**名字连接 + 词表覆盖**（ptcd/TCGdex set id 自 SV 代分叉实测），实测解析率 99.88%；置信度分档新增 `species-linked`；数据源矩阵新增 PokéAPI CSV<br>v1.7：task 025 同名计数引擎设计定稿——FR-3.4 展开为**逐条形式化计数语义**（deck_size=60；单卡/同名组双层上限判定；ACE SPEC 与光辉全卡组 ≤1；◇ 同名 ≤1；V-UNION 部件各 1 且组总 ≤4）；FR-8 `validate_deck` **Violation 语义全集定义**（kind 新增 `unknown_card`/`radiant_limit`（additive）；`evolution_chain` 定死为**预留类型**——官方卡组构筑规则无进化链完整性要求，当前规则集不产生）；DeckReport 字段定稿（ok/deck_size/format/date/snapshot_id/violations，Violation 增 `count`）<br>v1.8：task 027 赛事卡组数据源调研落地 + 数据模型设计——**mik.moe 赛事 API 全端点实测打通**（series-list → list → rank-individual → deck/detail，卡组卡标识 = setCode+cardIndex 与本库主键一致，零映射成本）；EN 源 = **Limitless TCG 官方 API**（play.limitlesstcg.com，匿名 50req/5min，PTCGO set code + number → name_en 桥）；JP 源 = players.pokemon-card.com JSON 壳（名次+卡组码，卡表渲染后置）。新增 **FR-9 赛事卡组与统计基建**：采集范围限定**仅可映射到简中环境的卡组**（EN/JP 按映射率分档 mapping_status）；§7.5 tournaments/decks/deck_cards 三表；**统计范围 = 宝可梦/支援者/竞技场**（能量/物品/宝可梦道具不进统计），统计粒度 = name_group；胜率语义诚实声明为**名次加权使用率 / top-cut 转化率**（mik 无逐局对阵，逐局 matchup 仅 Limitless pairings 可得，后置）；里程碑新增 M9<br>v1.9：task 027 统计指标体系定稿——FR-9.4 展开为**三指标**：①**加权出场率 WUR**（卡组名次权重[官方积分优先、无则 1/rank] 赛事内份额化 × 赛事权重[tier 系数开放词表 × log 人数 × 半衰期 90 天时间衰减]）；②**胜率 WR 分层**（A 层 Limitless record/pairings 真实胜率、镜像对局剔除；B 层 mik 无逐局数据 → top-cut 转化率代理，与 deck-static-by-tour 对账）；③**加权胜率 WWS = WUR × 贝叶斯收缩胜率**（A 层向 0.5 收缩 k=20 等效局；B 层向赛事基准转化率收缩 k=10 等效卡组）；每指标附样本量 n 与口径标签、低样本 low_confidence 标记<br>v1.10：统计可复算性与查询层设计（task 029 设计）——**FR-9.6 可复算性契约**（一切公布指标可由库存事实 + 公开公式复算；权重输入全量落库[tier_coef 物化/topcut_slots/参赛人数/日期]，指标只作派生不落真相；canonical SQL 单一事实源 `ptcgdb/stats/sql/`；name_group 与 tiers 词表 hash 入 meta/manifest；数据质量门：60 张/count 和/唯一性/{source}:{source_id} 主键口径/FK 强制）；§7.5 修订（tournaments 加 topcut_slots/tier_coef、decks 加 record 三列）+ 物化视图 v_stat_deck_cards/v_tournament_weights；**FR-9.7 统计与查询接口**（`ptcgdb stats` 子命令组 usage/winrate/wws/card/overview + `ptcgdb query` 只读 ad-hoc SQL + SDK stats_* 函数 + 导出追加赛事三件套）；M9 拆分 M9-1 数据管线 / M9-2 统计与查询层 / M9-3 EN Limitless<br>v1.10（续，task 027 实测订正）：**mik deckId 实测为卡组内容实体**——同一套 60 张清单按内容去重、可被多名选手/多场赛事共用（真实采集 1,396 个名次条目 vs 1,252 套内容；97 套内容跨赛事；存在同一赛事两个名次共用同一 deckId 的实例）——§7.5 拆表：decks=内容实体（variant/deck_code/映射状态），新增 **deck_appearances** 出战条目表（名次/积分/选手/A 层 record 挂此，PK(deck_id, tournament_id, rank)）；FR-9.2 数据模型、FR-9.4 统计口径（"卡组数"=出战条目数，与 deck-static-by-tour variant count 可对账）、FR-9.7 视图（四表联查）同步；migration 005 重建赛事三表（004 数据可由 raw 重 ingest，特性未发布无下游）<br>v1.11：A2 卡面人工比对（task 020，100/100 核销）三件技术债修复（task 030）——①**F-01 number_display 分母改种子口径**：A2 实测翻案"mik cardsNum=卡面分母"旧注（卡面分母=商品主列表收录数，5 系列数据点 207/414/151/045/222 + CBB* 宝石包 PPNN/包内卡数复合编号），§7.1 新增 `card_face_total`（种子 `config/set_card_face_totals.yml`：实测 > TCGdex zh-cn 壳 official[sanity 门] > CBB 按包），§7.2 number_display 未覆盖系列只显分子；②**F-02 mik 双重列示别名**：§7.2 新增 `alias_of`（16 张字母编号基本能量=同系列数字条目 raw 全等重复，数字为正本，主键与总数口径不动）；③**F-03 太晶翻案**：v1.4 ⑤"暂无太晶样本"作废——mik 无太晶信号，`is_tera` 改走 ptcd EN 卡 `subtypes` 印刷级识别（mapping 层 `map-tera` 富化），rule_box_type 维持 ex；§7.2 text_raw 口径订正为**不含规则框文本**（mik 源不提供，原"含规则框文本"注记错误）<br>v1.12：task 026 落地——**FR-8 `validate_deck` 实装**（组合 build_pool + check_counts，banned/not_legal 互斥禁卡优先，按 card_id 逐卡报告附 copies 数；SDK 双后端同一契约 + CLI `ptcgdb deck-check`）；新增**卡表 YAML 输入格式**（FR-8 末）：`cards` 为 card_id → 数量映射，文件内 `format`/`date` 可选、CLI 选项覆盖、日期默认当天；DeckReport.date 类型定死为 date（与 LegalityPool 一致，原示意注记 str 作废） |
| 项目代号 | ptcg-cn-db |
| 上游目标 | 为"AI模拟对战 + 卡组强度/胜率测试"本地工具提供卡牌数据与规则基建 |

---

## 1. 背景与目标

### 1.1 背景

用户正在构建一个本地工具：通过 AI 模拟宝可梦集换式卡牌游戏（PTCG）**简体中文版**实体卡牌的对战，测试不同卡组的能力与相互胜率。该工具的第一块基石是一个**覆盖当前简中标准赛制全部合法卡牌的知识库/数据库**，以及配套的**卡牌与规则稳定更新机制**。

### 1.2 目标

1. 建成一个本地 SQLite 数据库，完整收录简中当前标准赛制（赛制标记 G/H/I + 官方白名单）的全部卡牌，字段设计完整适配当前复杂机制（ex、太晶、ACE SPEC、训练家宝可梦、规则框等），并前瞻兼容已官宣的临近机制（超级进化ex、GX 复刻）。
2. 建立"原始数据 → 标准化 → 入库 → 导出"的可重复数据管线，支持新卡增量入库。
3. 建立赛制/规则/勘误的**分级自动化更新机制**与**版本化可回滚**能力。
4. 为下游（规则引擎、AI对战模拟、胜率统计）提供稳定的数据契约：**七件套导出 + 双后端 Python SDK**（见 FR-7 / FR-8），使本项目可作为多个项目的通用数据基建。

### 1.3 非目标（本期不做）

- 对战规则引擎本身（Phase 3+）。
- 卡牌效果的结构化 DSL 解析（仅保留原文 + 粗粒度标签，见 6.4；TCG ONE 的工业级实践[^19^]证明 DSL 应与静态数据分离、由下游规则引擎自建）。
- 卡图：不采集、不存储、不分发（本项目数据形态为纯文本/结构化数据）。
- GUI / Web 前端：交互形态为 **CLI，后续可演进为 TUI**（数据库层与 UI 层解耦，见第 3 章）。
- 对战模拟结果统计（Phase 4；且模拟结果**不写入本库**，见第 4 章）。

---

## 2. 调研结论（2026-08-01）

本章是 PRD 的事实基础，全部来自公开来源核查（含 2026-08-01 对官方赛制页的逐项复核）。

### 2.1 当前赛制范围（官方赛制页，更新于 2026-07-16）

- **标准赛制**可用卡牌 = 卡面左下角**赛制标记为 G、H、I** 的卡牌 + **8 种基本能量卡** + 官网列举的**白名单卡牌**[^1^]。
- **基本能量并非全局恒合法**：标准赛制为 8 种（草/火/水/雷/超/斗/恶/钢）；**开放赛制为 9 种（含妖）**——简中日月时代发行过基本妖能量（SM-P 190），官方公告明确开放赛制可用 9 种属性的基本能量[^13^]。**能量种类合法性必须随快照维护，不做全局特判**（见 FR-3.2）。
- 白名单分两部分（完整清单见附录 A）：
  - **特典卡 18 种**（30 周年 PROMO，编号 PROMO_001~024/30th-P 中的 18 个号）；
  - **过去系列卡牌**：标准赛制 26 种，**开放赛制 32 种**（多出捕虫少年、离洞绳、谜之化石、模仿少女、能量签、千金小姐 共 6 种；2026-08-01 按赛制页正文逐名核定，修正 v1.3"34 种/8 种"的估计）[^1^]——白名单必须**按赛制独立**维护。官方明确"卡牌上的描述**按最新卡牌的描述为准**"[^1^]。
- 官方特别规定：卡牌名称为"博士的研究"/"老大的指令"的卡，**即使人物名称或插画不同，均视作同名卡**[^1^] —— 直接影响同名归组逻辑（见 6.2）。
- **赛制标记"视作"覆盖规则**：官方可对**特定印刷**指定"赛制标记视作 X"——先例：起始卡组交相辉映GX 收录的"天空之柱"（CSM2D 339/342）赛制标记**视作 B**[^13^]。这是 card_id 级覆盖（同名其他印刷不受影响），与白名单"按名称归组"语义不同，需单独建模（`mark_overrides`，见 7.3）。开放赛制页附有"**特别的卡牌**"外链（`/tcg-rules-regulation-extra/`）——**2026-08-01 实测（task 014）：该页是 GX/棱镜之星/究极异兽/TAG TEAM/V-UNION 等特殊机制的图文说明页，并非"视作覆盖"清单**；无结构化字段可解析，L1 对其只做正文 hash 监控，变更时生成 needs_manual 提案由人工核对（v1.3"大概率即此类清单"的推测作废）。
- 简中**开放赛制**（允许太阳&月亮/剑&盾/朱&紫全系列 + 扩展白名单 + 9 种基本能量），并配有**禁卡表**（当前禁：玛夏多〔特性：破罐破摔〕、阿塞萝拉、全满药；规则为"即便卡面或罕贵度不同，只要卡牌、特性、招式名称相同即不可用"）[^1^]。2023 年 5 月简中首次公布过 12 种禁牌[^2^]。
- **卡池机制覆盖核查（2026-08-01）**：当前标准合法卡池含 宝可梦ex、**太晶/星晶**（太晶盛聚 CSV9.5C，2026-06）、**古代/未来**（利刃猛醒，2026-01）、ACE SPEC、**5 组训练家宝可梦**（火箭队的/莉莉艾的/竹兰的/玛俐的/N的，共逐荣光 CSV10C，2026-07）[^16^]；GX / TAG TEAM GX / V / VMAX / VSTAR / 光辉 / **V-UNION**（四方联结礼盒：超梦/甲贺忍蛙/苍响）**仅开放赛制可用**；**超级进化ex 尚未在简中发售**（繁中/国际已进入超级进化系列，简中落后约 2~3 个阶段）——schema 保留前瞻字段，验收标准相应调整（见 A3）。**M1 全量实测补注（task 005）**：mik 源 12,473 条目扫描未发现太晶卡样本，`is_tera` 派生判定（卡名/mechanic/label 含"太晶"）预置未触发——太晶卡在 mik 源的数据形态（或是否已收录）待 A2 与官方小程序核对，`is_tera` 字段与判定逻辑保留不动。**v1.11 翻案（task 020 A2 实测）**：太晶卡确实存在且 mik 源本就不提供太晶标记（判据永假）；确诊 3 例（喷火龙ex/伊布ex/拉普拉斯ex），`is_tera` 改走 ptcd EN 卡 subtypes 印刷级识别（见 §7.2 is_tera）。
- **结论**：数据库必须支持多赛制（standard/open）、按赛制独立的白名单、禁卡表、**赛制标记"视作"覆盖**、**基本能量种类**五类合法性数据，且全部按快照版本化。

### 2.2 赛制变更节奏（历史事实）

| 日期 | 事件 |
|---|---|
| 2023-05-19 | 进入剑&盾系列，首次公布 12 种禁牌[^2^] |
| 2024-05-19 | 曾增设第三赛制"太阳&月亮限定赛制"（后取消）[^14^]——`format` 取值必须保持开放，S5 历史回放可能遇到第三个赛制 |
| 2026-01-16 | 标准赛制 E 标退出，可用范围 F/G/H[^3^] |
| 2026-07-16 | 标准赛制 F 标退出，可用范围 G/H/I[^1^] |
| **2026-09-16（预告）** | **"30周年庆典"全球同步发售**（简中首次全球同步；日版/繁中归属超级进化系列；新罕贵度 FUR；30 张历史卡特别式样复刻含 GX 时代卡）[^15^]——下一个确定性变更事件，可能首次将超级进化/GX 复刻机制带入简中当前环境 |

约**每半年退一个标记**；补充包发售节奏约 **2~3 个月一包**[^4^]。官方通常提前 2~3 个月预告新品[^5^]。变更检测按"天"级轮询足够。

### 2.3 数据源评估

| 数据源 | 内容 | 可得性 | 定位 |
|---|---|---|---|
| **官方小程序"宝可梦卡牌会员"** | 简中全部卡牌的官方数据（卡名、卡号、赛制标记、特性/招式/能量/弱点/抵抗力、进化关系、卡图），另有卡组构筑与赛事卡组功能[^6^] | 无公开 API、官网无网页版卡查；接口有 JWT 登录态 + 请求/响应 AES 加密 + 签名四层防护（M0 实测，还原需反编译 wxapkg） | **不可得（D1 已否决抓包路线）**；Phase 2 候选交叉源（A2 卡面核对） |
| **Cryst's Cards Database（tcg.mik.moe）** | 覆盖简中全部卡牌 + 2023 年广州大师赛以来全部官方积分赛事数据/卡组/Meta；官方自述卡牌与赛事数据均来自官方小程序[^7^] | 公开 JSON API（`/api/v3/card/*`，无鉴权明文，接口文档 `docs/data-sources.md`） | **主数据源（D1 = 路线 B，M0 定）** |
| **官方赛制页 pokemon.cn/tcg-rules-regulation** | 标准/开放赛制范围、白名单、禁卡表、"特别的卡牌"外链 | 公开网页[^1^] | **合法性数据权威源**（L1 监控对象） |
| **官网公告（pokemon.cn/category/tcg）** | 赛制调整说明、规则调整、卡牌补充说明（勘误）、新品预告 | 公开网页[^3^] | **变更信号源**（L1/L2 监控对象） |
| **日文官方卡查 pokemon-card.com/card-search** | 日文全部卡牌的官方网页卡查（卡名/编号/赛制标记） | 公开网页 | **JP 映射抽样权威核对源**（v1.5 新增；低频抽样核对，不爬全量） |
| **繁中训练家网站 asia.pokemon-card.com** | 繁中全部卡牌公开网页卡查；繁中标准赛制已含 H/I/J 标[^8^] | 公开网页 | 赛制参考；**v1.5 起取消繁中映射方向**（不做采集，`name_zh_tw` 预留不填充） |
| **pokemon-tcg-data / TCGdex** | 英文全部卡牌开源 JSON / 免费 API；TCGdex 14 语言、MIT 协议，英/日卡级数据覆盖高但 **EN/JA 卡 id 不共构**（2026-08-01 task 023 实测，交集仅个位数，v1.5「同 ID 共构」假设作废）；pokemon-tcg-data 卡数据含 `nationalPokedexNumbers`（dexId，JP 映射锚点）；**已收录全部简中系列壳（set_id 与本库一致）但卡级数据 0%**（2026-08-01 实测）[^10^][^11^] | GitHub / api.tcgdex.net | **EN 映射源 + JP 映射 dexId 锚点**（见 2.4）+ **系列级跨源对账源**（FR-1.2）；zh-cn 卡级实装后可降级为消费方（风险登记册） |
| **PokéAPI（pokeapi/pokeapi CSV）** | 全物种多语言名表（`pokemon_species_names.csv`，含日文） | GitHub 静态 CSV | **JP 映射物种名源**（v1.6 新增；dexId → 日文物种名） |
| **Limitless TCG** | 英文赛事卡组最大聚合库：play 平台线上赛全量（官方 API）+ 主站人工收录官方大赛上位卡组（HTML，PTCGO set code + number 标识） | 官方开放 API（匿名 50 req/5min）+ 公开网页 | **EN 赛事卡组源**（v1.8 新增；set+number → name_en 桥映射简中） |
| **players.pokemon-card.com** | 日本官方赛事系统：City League/CL/PJCS 全量名次 + 官方卡组码（event_search / event_result_detail_search JSON 端点）；卡组内容需前端渲染解码 | 官方站内部 JSON（低频只读） | **JP 赛事壳源**（v1.8 新增；名次+卡组码入库，卡表渲染后置，WAF 严格） |
| **神奇宝贝百科（wiki.52poke.com）** | 按赛制标记分类的卡牌索引等[^12^] | 公开 wiki | 兜底交叉校验 |

**关键事实**：简中卡牌是**独立产品池**（从太阳&月亮既有卡池精选起步、后续套装结构与国际版不同、朱&紫为独占 CSV 编号），任何国际版数据库都不含简中卡[^9^]，无法直接套用，只能自建。

### 2.4 跨语言映射路径（为 AI 模拟与效果解析服务）

国际版（英文/日文）卡牌数据结构化程度高，且有公开的上位卡组/赛事数据可借鉴。映射链路（v1.6 实测修订）：

```
简中卡 ──(mik raw 英文桥 setCodeEn/cardIndexEn/nameEn，主源自带)──▶ EN 卡（TCGdex ID 解析 + 交叉校验）
      ──(EN 卡 dexId〔pokemon-tcg-data 卡数据〕→ PokéAPI 物种名表日文名 + 形态/机制词表)──▶ JP 名
```

- **EN 映射主路径 = 提取 mik raw 已有英文桥字段**（task 001 意外收获），不做模糊匹配；TCGdex / pokemon-tcg-data 静态数据作交叉校验与兜底。
- **EN 桥 → TCGdex ID 解析**（task 023 实测三类形态，均数据驱动处理）：①ptcd set id 与 TCGdex set id 自 SV 代分叉（sv2 vs sv02）——set 映射用**名字连接**（ptcd ptcgoCode→name × TCGdex en-sets name→id）+ 词表覆盖兜底（促销/能量 mik 自造码）；②编号形态差异（零填充 / SM25·SWSH017 字母前缀 / GG·TG·SV 子集套编号）；③命名惯例差异（TCGdex 人物括注尾缀、棱镜星 Prism Star vs ◇、变音符）仅作校验豁免。实测解析率 **99.88%**（12,322/12,337），未解析全量归类入报告。
- **JP 映射 = 名字级映射（v1.6 修订）**：v1.5 设想的「TCGdex 同 ID 多语言共构」**实测证伪**（EN/JA 卡 id 不共构，交集仅个位数；列表端点无 dexId）。修订为：宝可梦走 **dexId → 日文物种名**（同一卡日文名跨印刷不变，无需定位 JA 印刷）+ 形态/归属/机制前后缀开放词表；基本能量封闭集词表定名；**训练家/特殊能量本里程碑不填充**（无可靠批量源，全量入 question 清单）；官方 pokemon-card.com 卡查做 ≥30 张分层低频抽样权威核对（限速 ≥2s/请求、只读）。
- **v1.5 取消繁中方向**：不做 asia.pokemon-card.com 采集；`name_zh_tw` 字段保留预留不填充（字段只加不删）。
- 置信度分档：`bridge`（mik 英文桥直取）/ `tcgdex-linked`（EN 桥解析出 TCGdex ID）/ `species-linked`（dexId 链出日文物种名）/ `manual`（人工核对）；冲突与多候选不猜测，记 question 清单。
- 简中套装结构与国际版不一致（精选/独占 CSV 编号）——映射**按卡级桥字段逐卡对齐**，天然不受套装结构差异影响。
- 映射**只在 Phase 2 建设**，Phase 1 仅预留字段（`name_en/name_ja/name_zh_tw` + `external_ids` 表）。

### 2.5 规则文档现状

简中未检索到独立公开的"规则书 PDF"下载；规则相关内容分布在：官网赛制页、官网公告（赛制/规则调整说明、卡牌补充说明）、小程序内。规则文档版本化按"公告条目 + 赛制页快照"管理（见 9.3），**规则书 PDF 是否存在于小程序内为开放问题**（见第 14 章）。

### 2.6 开源生态对标（2026-08-01 调研）

简中卡库在开源世界**完全空白**（现有项目只覆盖英/日/繁中），自建判断成立。以下开源项目的成熟设计已被本 PRD 采纳：

| 借鉴对象 | 采纳的设计点 |
|---|---|
| pokemon-tcg-data / TCGdex[^10^][^11^] | `card_id = setId-number` 事实标准（与本库一致，保证与下游工具互通）；`regulation_mark` 为源字段、合法性为派生 |
| TCGdex（REST + SDK）[^18^] | 静态数据与查询接口同数据双消费方式 → 本库 `open_db`/`open_jsonl` 双后端 SDK（FR-8）；类型化 Query 构建优于字符串查询语法 |
| type-null/PTCG-database[^9^] | 爬虫**三清单日志**（成功/可疑/缺失，FR-1.4）；伤害建模 `amount+suffix` 分离（即本库 `damage_base/damage_modifier`）；官网脏数据预期（FR-2.3 双源校验） |
| TCG ONE（tcgone）[^19^] | 效果 DSL 与静态数据分离的工业级先例 → 佐证 6.4"本期不做 DSL"的边界决策 |
| ryuu-play[^20^] | "赛制 = 卡池集合 + 规则覆写"的声明式建模 → `legality.json` 快照结构 |
| MTGJSON / Scryfall[^17^] | 多形态导出、**双轨版本化**（日历版本管数据 + SemVer 管结构）、checksums 完整性校验、四段式 CHANGELOG（Added/Changed/Deprecated/Removed）→ FR-6/FR-7 |

**本项目的差异化定位**（比现有开源项目做得更好的点）：①简中**独立赛制**（standard/open）的快照化与历史回放——国际版数据集均不支持，且简中赛制与国际版不同步；②合法性/同名计数/卡组校验为 SDK **一等公民函数**（pokemontcg.io/TCGdex 的 SDK 只做数据查询，不做规则语义）；③白名单旧卡的 `effective_text` 版本化解析（勘误 > 最新印刷 > 原文）。

---

## 3. 用户与使用场景

唯一用户 = 工具作者本人（本地单人工具）；下游消费者 = 同一作者的多个项目（规则引擎、AI 对战模拟、胜率统计）。核心场景：

- **S1 查卡**：按卡名/系列/赛制标记/卡牌种类/特性/招式能量成本等条件检索合法卡池。
- **S2 组卡合法性校验**：给定 60 张卡表，校验张数、同名限制（含博士的研究等特殊同名规则）、ACE SPEC 限 1、赛制合法性（按指定日期的环境快照）。
- **S3 模拟器供数**：下游规则引擎/AI 以 SDK（SQLite 或 JSONL 后端）读取全量卡牌数据与合法性判定。
- **S4 环境演进跟踪**：新包发售/赛制调整时，10~30 分钟内完成数据更新并生成版本。
- **S5 历史环境回放**：按历史快照日期查询当时合法卡池（用于复现历史环境的对战模拟；历史可能包含已取消的第三赛制）。

**交互形态**：CLI 优先（FR-4），后续可在不动数据库层的前提下演进为 TUI（如 Textual）；全部查询能力经 CLI/SDK 暴露，不绑定具体界面。

---

## 4. 范围与分期

| 阶段 | 内容 | 交付物 |
|---|---|---|
| **Phase 1a** | schema 建库 + raw 层 + 全卡首批入库（G/H/I + 白名单 + 基本能量 + 开放赛制全系列） | `ptcg-cn.db`、raw 缓存、校验报告 |
| **Phase 1b** | 环境快照（含禁卡表/视作覆盖/能量种类）+ 版本化/回滚 + **导出七件套** + **SDK 基础**（双后端读取） | legality 快照、CHANGELOG、dist 七件套、`ptcgdb.sdk` |
| **Phase 1c** | 更新机制 L0（新卡增量管线）/L1（赛制页+公告+"特别的卡牌"外链监控与变更提案） | 监控脚本、提案生成器 |
| Phase 2 | 跨语言映射（简中→英文→日文，填充 external_ids / name_en / name_ja；v1.5 起不做繁中）、卡组校验器 SDK（`validate_deck`，真实卡组源 = mik.moe 赛事数据库） | 映射表、DeckReport |
| Phase 3 | 效果粗粒度标签层；配合规则引擎 | effects_tags |
| Phase 4 | 对战模拟与胜率统计。**模拟结果落独立 SQLite/Parquet，经 card_id 关联；卡牌主库永不被写**；可选增出 `cards.parquet` 供 DuckDB 分析 | 独立 sim 库 |

本 PRD 的验收范围 = **Phase 1a/1b/1c**。

---

## 5. 名词约定

- **赛制标记（regulation mark）**：卡面左下角字母（G/H/I…），合法性第一手依据[^1^]。
- **视作规则（mark override）**：官方对特定印刷指定"赛制标记视作 X"的 card_id 级规则（如"天空之柱"CSM2D-339/342 视作 B）[^13^]。
- **商品编号**：卡面印刷的收录商品代码（如 CSV1C、30th-P）[^1^]。
- **编号外卡**：卡号超出系列分母的 SR/HR/UR/FUR 等卡（如 128/127 中的 128）。
- **完整卡名（name_full）**：含前后缀的卡名（"火箭队的喵喵ex""大师球〔ACE SPEC〕"）。
- **种名（species）**：宝可梦本名（"喵喵"），仅用于检索。
- **规则框（Rule Box）**：ex/超级进化ex/光辉/V 类/GX/V-UNION 等卡面规则文本框；拥有规则框的宝可梦是效果文本中的检索目标。
- **V-UNION**：四张部件卡（左上/右上/左下/右下）组合为一只宝可梦的特殊卡（超梦/甲贺忍蛙/苍响，仅开放赛制）。
- **快照（snapshot）**：某一生效日起的赛制合法性集合（标记 + 能量种类 + 白名单 + 禁卡表 + 视作覆盖）。
- **schema_version**：导出契约的结构版本（SemVer），与数据日历版本（vYYYYMMDD.N）双轨并行（见 FR-6/FR-7）。
- **draft/active**：数据入库两阶段状态。

---

## 6. 功能需求

### FR-1 数据采集（Phase 1a）

- FR-1.1 支持从**主数据源**（tcg.mik.moe `/api/v3/card/*`，D1 = 路线 B）抓取指定系列/全部卡牌，原始响应以 append-only 方式落盘 `raw/`，含 `fetched_at / source / content_hash`。
- FR-1.2 **降级与交叉源**：官方小程序接口数据最全但有 JWT+AES+签名四层防护（M0 实测不可得，D1 已否决抓包路线）；卡级字段**无可用第二结构化源**（v1.5 调研确认：TCGdex zh-cn 仅系列壳、卡级 0%，52poke 维基非结构化），卡级校验以 DB vs raw 同源自验（FR-2.3）+ A2/A3 人工卡面比对替代；**系列级跨源对账**（TCGdex zh-cn 系列壳：系列名 + 卡数）自 Phase 2 起落地。
- FR-1.3 限速（默认 ≥1s/请求）、失败重试（指数退避、最多 3 次）、断点续传（按 card 级任务粒度）。
- FR-1.4 **三清单日志**（借鉴 type-null/PTCG-database[^9^]）：每次抓取产出 `scraped`（成功）/ `question`（可疑：字段缺失、解析异常）/ `missing`（应有但未抓到）三份清单并记入 `scrape_runs`；`question` 清单必须人工归零后方可置 active。

### FR-2 标准化与校验（Phase 1a）

- FR-2.1 原始 JSON → Pydantic 模型 → 字段归一（能量符号、罕贵度、赛制标记、卡号格式）。
- FR-2.2 入库两阶段：先入 `status=draft`，通过全部校验后置 `active`。
- FR-2.3 校验规则（任一失败即阻断并出报告）：
  - 必填字段非空（卡名、卡号、赛制标记、卡牌种类、text_raw）。**豁免**：基本能量的 regulation_mark 可空（卡面本就无标记）；源数据本身缺失时（先例：SSP-195 洗翠的沉重球 mik description 为空——单卡源数据缺口，非管线丢失）DB 忠实反映源数据、记 note 不判失败，报告中如实列明卡号；
  - 枚举值合法（属性、卡牌种类、罕贵度在词表内）；
  - 能量成本符号合法且保序；
  - 按系列对账（**条目自身 setCode 归属 + `(setCode, cardIndex)` 全局去重**口径）：mik 会把产品附赠能量卡在多个系列的 cards 列表重复列出，但条目 setCode 指向其原生系列（如 CS1DC/CS3DC 列表中的 8 张基本能量 setCode='CSAC'）——按目录 cardsNum 直接对账会产生假缺口（M1 实测 15 个），必须按去重口径：期望数 = 去重后条目数，入库数 == 期望数（M1 实测 12,420 == 12,420，129 系列 100% 通过）；
  - 特殊组合完整性（V-UNION 4 部件齐全、方位互斥；同名多组按 card_id 每 4 件切组——M1 实测 CSEC 莫鲁贝可V-UNION 两组 8 件）；
  - 抽样比对（每系列 ≥5% 抽样，卡名+HP+招式名一致率 100%）：多源时为与降级源跨源比对；**本期（D1=路线 B 单源）为 DB vs raw 同源自验**，报告中如实注明；**系列级跨源对账**（TCGdex zh-cn 系列壳）自 Phase 2 起补齐，卡级跨源待 TCGdex zh-cn 实装（v1.5 调研：当前卡级 0%）。
- FR-2.4 派生计算：name_group 归组、evolution_chain_id、has_rule_box、is_tera、is_basic_energy、mentions / union_part_of 关系抽取（见 6.3）。

### FR-3 合法性引擎（Phase 1b）

- FR-3.1 支持按**日期 + 赛制（standard/open，开放字符串兼容历史第三赛制）**查询合法卡池：`legal_at(date, format) -> card_id 集合`。返回语义：赛制标记合法的卡返回其 card_id；白名单卡按 `name_group` 匹配，返回该名下**全部入库印刷行**的 card_id（消费方如需唯一代表文本，用 `effective_text()` 解析到最新印刷）。
- FR-3.2 合法性判定顺序（任一命中即定）：
  1. **禁卡表**（按名称+特性/招式名匹配）→ 不合法；
  2. **白名单**（按 `name_group` 匹配，按赛制各自独立清单）→ 合法；
  3. **赛制标记"视作"覆盖**（`mark_overrides`，按 card_id 精确匹配，如天空之柱 CSM2D-339 视作 B）→ 以覆盖后的标记继续第 4 步判定；
  4. **赛制标记 ∈ 快照 `allowed_marks`** → 合法；
  5. **基本能量**：`is_basic_energy=TRUE` 且能量种类 ∈ 快照 `allowed_basic_energy_types`（当前 standard 8 种；open 9 种含妖[^13^]）→ 合法。
  基本能量不走赛制标记路径，种类合法性完全由快照维护，**不做全局特判**（妖能量为标准赛制反例）。
- FR-3.3 白名单旧卡使用时，文本按"最新描述"解析：提供 `effective_text(card_id, date)`，返回最新印刷文本 ∪ 生效勘误。`latest_text_overrides` 仅随**当前快照**维护（维护时机见 FR-5.1 后处理步骤）；**历史快照的 override 一经生成即冻结**，保证 S5 历史回放不漂移。
- FR-3.4 同名计数规则引擎（v1.7 形式化）：输入卡表（card_id 列表，可重复），逐条判定输出结构化违规（供 CLI 与 SDK 双后端复用的纯函数核）：
  1. **deck_size**：卡表总数 ≠ 60 → `deck_size` 违规（detail 记实际数）；
  2. **name_limit 双层判定**：① 单 card_id 数量 ≤ 其 `deck_limit`；② 同 name_group 总数 ≤ **组上限**——组上限 = 4（组内含 V-UNION 部件时）否则 max(成员 deck_limit)。普通卡 4/4；◇ 卡（deck_limit=1）同名 ≤1（不同名 ◇ 可共存，无全局限制）；V-UNION 部件各 ≤1 且组总 ≤4。**基本能量（`is_basic_energy`）不受同名上限约束**（官方规则：基本能量不列入 4 张限制）；
  3. **ace_spec_limit**：全卡组 `is_ace_spec` 卡总数 ≤ 1（跨卡名全局约束）；
  4. **radiant_limit**：全卡组 `rule_box_type=radiant`（光辉）卡总数 ≤ 1（跨卡名全局约束）；
  5. 跨插画同名（"博士的研究"/"老大的指令"）经 name_group 归组后按 ② 计数——归组规则按简中官方赛制页注释维护[^1^]。注：繁中赛制页另有"寶可裝置3.0 與 寶可齒輪3.0 視同名"规则[^8^]，系繁中朱&紫起译名变更所致；**简中不存在该译名对，此规则不适用**，不进入简中归组规则表。

### FR-4 查询 CLI（Phase 1a 起）

```
ptcgdb search --name 喵喵 --mark G,H,I
ptcgdb get CSV1C-009
ptcgdb legal --date 2026-08-01 --format standard
ptcgdb export --out dist/            # 导出七件套（见 FR-7）
ptcgdb stats                         # 各系列/标记卡数对账
```

### FR-5 更新机制（Phase 1c）

- FR-5.1 **L0 新卡**：每日总量探测（系列应有卡数 vs 当前数），有增量触发抓取 → draft → 校验 → active。合入后执行两个后处理：①刷新当前快照的 `latest_text_overrides`（白名单旧卡 → 最新印刷 card_id）；②增量重建 name_group / mentions 等派生关系。cron 漏跑（如机器未开机）不做逐日补偿，下次运行时幂等补齐即可。
- FR-5.2 **L1 赛制**：每日对赛制页、公告列表页、**开放赛制"特别的卡牌"外链页**做**正文提取后**的 hash 快照比对（剔除页脚/时间戳等动态区块，避免假阳性）；变更 → 抓新内容 → 自动生成结构化**变更提案** `proposals/YYYYMMDD_*.yaml`（解析出的标记集合/能量种类/白名单/禁卡表/视作覆盖/生效日期 + 原文链接）→ 人工确认 → `apply` 生成新快照。**旧快照永不删除**。
- FR-5.3 **L2 勘误/规则**：人工维护 YAML（errata、rules_documents），导入脚本入库；每次新包发售后 2 周内主动检查一次勘误公告。
- FR-5.4 赛季日历：每 2~3 个月赛季开启时强制全量对账（库内合法性判定结果 vs 赛制页**按赛制分别**逐卡核对——标准白名单 26 种 / 开放白名单 32 种各自核对）。
- FR-5.5 变更通知：本地桌面通知（必选），webhook（可选），附 diff 摘要。

### FR-6 版本化与回滚（Phase 1b）

- FR-6.1 **双轨版本化**（对齐 MTGJSON[^17^]）：数据版本 = `vYYYYMMDD.N`（每次合入递增，写入 CHANGELOG.md 与 manifest）；结构版本 = `schema_version`（SemVer，存 `meta` 表与 manifest.json）。每次合入生成 manifest（来源、时间、变更卡数、DB hash）。
- FR-6.2 **字段纪律**：导出契约与 SDK 返回模型**只加字段、不改语义、不删字段**；破坏性变更必须升 schema major，并在 CHANGELOG 四段式（Added / Changed / Deprecated / Removed）中以 Deprecated 段**提前一个版本预告**。
- FR-6.3 回滚 = 切换到上一版本 DB 文件；raw 层只追加不覆盖，清洗逻辑可整体重跑。
- FR-6.4 schema 演进用 **`PRAGMA user_version` + `migrations/` 顺序编号 SQL 脚本**（轻量、与 raw 可重跑互补）；Alembic 延后至 schema 真正频繁演进时再引入。

### FR-7 导出契约（Phase 1b）

dist/ **七件套**（对齐 MTGJSON/Scryfall 惯例[^17^]）：

```
dist/
├── manifest.json      # {version: "v20260801.1", schema_version: "1.0.0", built_at,
│                      #  db_sha256, counts: {cards, sets, snapshots, relations}}
├── cards.jsonl        # 一行一卡，cards 表全字段（含 text_raw）
├── sets.jsonl         # 系列表全字段（下游按系列过滤必需）
├── relations.jsonl    # card_relations + name_groups + cards_name_group（进化链/同名/mentions/union）
├── legality.json      # {meta, data: {snapshots: [...], errata: [...]}} 全部快照：标记集/
│                      # 能量种类/白名单/禁卡表/mark_overrides/生效期（"赛制=卡池集合+规则覆写"
│                      # 结构，借鉴 ryuu-play[^20^]）+ 勘误表（供 JSONL 后端 effective_text）
├── ptcg-cn.db         # 只读 SQLite 快照（WAL checkpoint 后复制；可以 immutable 模式打开）
├── checksums.sha256   # 上述全部文件的 SHA-256（完整性校验）
└── schema.md          # 字段字典：由 Pydantic 模型半自动生成（model_json_schema）+ 人工注释，
                       # CI 做一致性检查防漂移
```

- 文件级 meta 约定：`legality.json` 顶层为 `{meta: {schema_version, built_at}, data: {...}}`；JSONL 文件首行可选 meta 注释行。
- Phase 2 扩展（v1.10，只加不删）：追加**赛事三件套** `tournaments.jsonl` / `decks.jsonl` / `deck_cards.jsonl`（deck_cards 行附 `group_key` / `stat_scope` 冗余列，JSONL 消费方免联表）；manifest.counts 加三项；schema.md 附统计 canonical SQL 全文与复算示例（FR-9.6/9.7）。
- Phase 4 起可选增出 `cards.parquet`（胜率统计 OLAP 下游，DuckDB 直读）。
- 消费指引（写入 schema.md）：JSONL 适合全量灌库/流式分析；**规则语义（legal_at / effective_text / validate_deck）请走 SDK**（FR-8），避免下游自行实现导致语义漂移。

### FR-8 下游 SDK（Phase 1b 起）

`ptcgdb.sdk`：**SQLite 与 JSONL 双后端、同一接口**（对齐 TCGdex"静态数据与 API 同数据"思路[^18^]）。

```python
from ptcgdb.sdk import open_db, open_jsonl

db = open_db("data/ptcg-cn.db")          # 或 open_jsonl("dist/")
db.schema_version                         # -> "1.0.0"；下游启动时断言主版本兼容

# —— 点查与检索 ——
db.get_card("CSV1C-009")                  # -> Card | None
db.search_cards(name="喵喵",               # 模糊匹配 name_full / species
                marks=("G", "H", "I"),
                card_type="pokemon",
                has_rule_box=True,
                is_tera=True,
                set_ids=("CSV10C",),
                limit=100)                # -> list[Card]
db.get_set("CSV10C")                      # -> Set
db.list_sets(era="朱&紫")                 # -> list[Set]

# —— 合法性（一等公民，纯函数语义）——
db.legal_at(date="2026-08-01", format="standard")   # -> LegalityPool
#    LegalityPool: card_ids: frozenset[str]; snapshot_id: str;
#                  by_name_group: dict[str, list[str]]
db.effective_text("CSM2D-339", date="2026-08-01")   # -> EffectiveText
#    解析优先级：勘误（最新生效）> 最新印刷 > text_raw

# —— 版本与历史 ——
db.snapshots(format="standard")           # -> list[Snapshot]；S5 历史回放入口
db.changelog(since="2026-07-01")          # -> list[ChangeEntry]

# —— 卡组校验（v1.12 实装，task 026；双后端同一契约）——
db.validate_deck(deck=[...60 个 card_id], date="2026-08-01", format="standard")
#    -> DeckReport: ok: bool; deck_size: int; format: str; date: date;
#                   snapshot_id: str; violations: list[Violation]
#    Violation: kind ∈ {deck_size, unknown_card, not_legal, banned,
#                       name_limit, ace_spec_limit, radiant_limit,
#                       evolution_chain}; detail: str; cards: list[str];
#                  count: int | None（实际数量，供 AI 策略消费）
#    合法性层：banned / not_legal 互斥（禁卡优先），按 card_id 逐卡报告，
#    count = 卡表内 copies 数；无覆盖快照抛 LookupError

# —— 赛事统计（v1.10，FR-9.7，task 029；薄封装 canonical SQL）——
db.stats_usage(date_from="2026-05-01", date_to="2026-08-01", as_of="2026-08-01",
               scope=("pokemon", "supporter", "stadium"), division="master",
               usage_basis="decks", min_n=5)     # -> list[CardStat]
db.stats_winrate(..., layer="auto", mirror="exclude")
db.stats_wws(..., k_a=20, k_b=10)
db.stats_card("沙奈朵ex")                        # 单卡逐赛事钻取
#    CardStat: group_key: str; display_name: str; value: float; n: int;
#              basis: str; layer: str; low_confidence: bool（frozen）
```

**Violation 语义全集（v1.7 定死）**：

| kind | 判定规则 |
|---|---|
| `deck_size` | 卡表总数 ≠ 60（FR-3.4 ①） |
| `unknown_card` | card_id 不在库（v1.7 新增，additive） |
| `not_legal` | 卡不在该日期/赛制合法卡池内（且未命中禁卡表） |
| `banned` | 命中快照禁卡表（名称 + 特性/招式名限定匹配，FR-3.2 第 1 步）——与 `not_legal` 互斥，禁卡优先报告为 `banned` |
| `name_limit` | 违反 FR-3.4 ② 双层计数（单 card_id 超 deck_limit，或同名组超组上限） |
| `ace_spec_limit` | 违反 FR-3.4 ③（ACE SPEC 全卡组 >1） |
| `radiant_limit` | 违反 FR-3.4 ④（光辉全卡组 >1；v1.7 新增，additive） |
| `evolution_chain` | **预留类型**——官方卡组构筑规则无进化链完整性要求，当前规则集不产生该违规；保留枚举供未来赛制/特殊规则启用，`validate_deck` 默认不返回 |

设计原则：

1. **返回类型一律 frozen Pydantic model**，不暴露 ORM 对象与 session——schema 演进不 break 下游的关键。
2. **规则语义只由 SDK 实现**，SQLite/JSONL 双后端行为一致（同一查询集跑两遍的契约测试保证）。
3. 校验类接口返回**结构化 Violation 列表而非抛异常**——AI 模拟器需要把违规原因喂给策略。
4. `schema_version` 显式暴露，下游一行断言即可防御不兼容升级。

**卡表输入格式（v1.12 新增，task 026；CLI `ptcgdb deck-check --file` 消费）**：YAML 单文件——

```yaml
format: standard        # 可选；CLI --format 覆盖，默认 standard
date: 2026-08-01        # 可选；CLI --date 覆盖，默认当天
cards:                  # 必填：card_id → 数量映射，展开后总数应 = 60
  CSM1aC-001: 4
  CSV10C-025: 2
```

退出码契约：ok 退出 0，有违规退出 1，输入/快照错误退出 2。

### FR-9 赛事卡组与统计基建（Phase 2 扩展，v1.8 新增，task 027 起）

- FR-9.1 **采集范围**：CN 主源 = mik.moe 赛事 API（2023 广州大师赛以来官方积分赛：城市赛/高级赛/超级赛/大师赛，组别 Master/Senior/Junior）；EN 辅源 = Limitless TCG 官方 API（线上赛）+ 主站 HTML（官方大赛上位卡组）；JP 壳源 = players.pokemon-card.com（名次 + 卡组码，卡表渲染后置）。**只入能映射到简中环境的卡组**：CN 源卡标识 = setCode+cardIndex 与本库主键一致（零映射成本）；EN/JP 卡组按卡名映射率分档 `mapping_status`（full ≥95% / partial <95% / unmapped 0%），统计层仅消费 full。
- FR-9.2 **数据模型**：§7.5 tournaments / decks / deck_appearances / deck_cards 四表。**mik deckId 实测为内容实体**（同一套 60 张清单按内容去重，可被多名选手/多场赛事共用）——内容（decks）与出战条目（deck_appearances）分表，名次/积分/选手/A 层战绩挂出战条目（v1.10 续，task 027 实测订正）。卡组构成**保真全量存 60 张**（含能量，供 `validate_deck` 复用做真值校验）；`card_id` 可空 + `raw_name` 保真，映射不上的卡不猜测。
- FR-9.3 **统计范围（硬约束）**：使用率/胜率统计**仅含宝可梦、支援者、竞技场**（card_type / trainer_subtype 判定）；**能量、物品、宝可梦道具不进统计**。统计粒度 = **name_group**（跨印刷同名合并，与 FR-3.4 计数口径一致）。
- FR-9.4 **统计指标体系（v1.9 定稿）**：三指标，统计单元 = **name_group × 时间窗**（默认滚动赛季），仅消费 `stat_scope ∈ {pokemon, supporter, stadium}` 且 `mapping_status='full'` 的卡组。公共权重：
  - **卡组名次权重** w_d：官方积分优先（mik points / Limitless points），无则 1/rank；赛事内份额化 w̃_d = w_d / Σ_{d∈t} w（跨赛事可比）；
  - **赛事权重** W_t = tier 系数（开放词表 `config/vocabularies/tournament_tiers.yml`：大师赛/PJCS=4、超级赛/CL=2、高级赛/Regional=1.5、城市赛=1）× log10(参赛人数) × 时间衰减（半衰期 90 天：0.5^(天数/90)）。
  1. **加权出场率 WUR**：`WUR(c) = Σ_t W_t·Σ_{d∋c} w̃_d / Σ_t W_t`——该卡在加权卡组中的出场份额。主口径 = 携带卡组数（**出战条目数 deck_appearances**——同一内容多套出战按多次计，与 mik deck-static-by-tour 的 variant count 口径一致、可直接对账）；副口径按 count 张数加权（报告注明）。
  2. **胜率 WR（按数据可得性分层）**：**A 层**（Limitless，有 record/pairings）：`WR(c) = (wins + 0.5·ties) / (wins + losses + ties)`（携带 c 的卡组逐局战绩）；pairings 可得时**剔除镜像对局**（双方同含 c）并注明口径。**B 层**（mik，无逐局对阵——swiss 端点仅赛事进行中可用）：**代理胜率 = top-cut 转化率** `CR(c) = 加权 top-cut 携带 / 加权总携带`，与 `deck-static-by-tour` 的 topcutTimes/share 抽样对账。
  3. **加权胜率 WWS**：`WWS(c) = WUR(c) × WR_adj(c)`——WR_adj 为**贝叶斯收缩胜率**：A 层 `(W + k·0.5)/(N + k)`（k=20 等效局数，向 50% 收缩）；B 层 `(T + k·q0)/(U + k)`（q0 = 赛事基准转化率 = topcut 名额/参赛人数，k=10 等效卡组）。低样本卡向基准收缩，出场率叠加后突出"高出场 × 高胜率"的环境核心卡；业务解释 = **该卡对环境胜利的贡献份额**。
  每个指标输出附带**样本量 n 与口径标签**（A/B 层、镜像口径、主/副口径）；n 低于阈值（词表定）打 `low_confidence` 标记。**模拟对战结果永远落独立库**（既有红线），赛事统计派生表在主库。
- FR-9.5 **采集纪律**：mik 2s/请求，只拉上位卡组（rank-individual 默认 64/页与 top64 对齐）；Limitless 匿名额度 50req/5min 内；players 壳数据低频、卡表渲染单独评估。**隐私最小化**：player_ref 只存官方选手编号（pinCode），不存昵称等个人信息。
- FR-9.6 **可复算性契约（v1.10，task 029 设计）**：任何对外公布的统计指标，必须能由**库存事实 + 公开公式**复算——"metrics are derived, never stored as truth"。
  - **事实完整性**：权重全部输入落库——tournaments 存 tier_coef（物化自词表）/ participant_count / topcut_slots / date，decks 存 rank / points / record 三列，deck_cards 存 count / stat_scope 并可联 cards_name_group 得 group_key；SQL 消费方**不读词表文件**即可完成复算。
  - **派生非真相**：统计结果只以**视图/查询**形态存在；未来若加缓存表必须标注 derived 且支持一键重建。既有红线不变：模拟对战结果永远落独立库。
  - **canonical SQL 单一事实源**：三指标的标准参数化 SQL 存 `ptcgdb/stats/sql/*.sql`（`:as_of` / `:date_from` / `:date_to` / `:scope` 等命名参数），CLI、SDK、schema.md 附录三处共用同一文件；下游 SQL 用户复制即得与官方一致的口径。
  - **口径版本化**：meta 表记录 `name_group_rules_hash` 与 `tournament_tiers_hash`（词表 SHA-256 前 12 位），manifest.json 同步——跨库比对复算结果先核对口径版本。
  - **as_of 回显**：时间衰减依赖查询时点，一切统计输出（CLI/JSON/SDK）的 meta 必须回显 as_of、窗口、scope、division、口径标签、词表 hash，保证结果可原样重放。
  - **数据质量门（入库即强制）**：①deck_cards 的 count 合计 = 60（is_team/异常赛制登记豁免名单）；②(deck_id, card_id, raw_name) 唯一；③tournament_id / deck_id 采用 `{source}:{源侧id}` 口径防跨源碰撞；④mapping_status 阈值固化（full ≥95%）；⑤导出前 `PRAGMA foreign_key_check` + `integrity_check` 通过。
  - **精度约定**：计算全链 float64；CLI 表格展示四舍五入 4 位，JSON/CSV 输出全精度。
- FR-9.7 **统计与查询接口（v1.10）**：
  - **物化视图**（随迁移落库，导出 DB 自带）：`v_stat_deck_cards`（deck_cards ⋈ decks ⋈ deck_appearances ⋈ tournaments 四表联查 + 范围过滤[`mapping_status='full'` ∧ stat_scope 三类] + group_key 预联，行粒度 = 出战条目 × 卡）、`v_tournament_weights`（赛事静态权重件 tier_coef × log10(participant_count)；衰减因子由查询参数 as_of 计算）。视图只封装过滤与连接，**不含业务公式**——公式只在 canonical SQL。
  - **CLI**（`stats` 升级为子命令组，裸 `ptcgdb stats` 兼容旧对账行为）：
    ```
    ptcgdb stats overview                        # 原"各系列/标记卡数对账"（兼容）
    ptcgdb stats usage   [--as-of D] [--from D --to D | --window-days 90]
                         [--scope pokemon,supporter,stadium] [--tier ...] [--division master]
                         [--usage-basis decks|copies] [--min-n 5] [--format table|json|csv]
    ptcgdb stats winrate [--layer auto|a|b] [--mirror exclude|include] [公共参数同上]
    ptcgdb stats wws     [--k-a 20] [--k-b 10] [公共参数同上]
    ptcgdb stats card <卡名>                      # 单卡钻取：逐赛事出场/名次/转化历史
    ptcgdb query "<SELECT ...>" [--format table|json|csv] [--limit 500]
    ```
    `ptcgdb query` 以 SQLite 只读 URI（`mode=ro`）打开，仅放行 SELECT/WITH 语句（拒绝写操作与 ATTACH），是下游"像写 SQL 一样查库"的官方入口。
  - **默认口径**：`division=master`、排除 is_qual / is_team 场次（`--include-qual` / `--include-team` 显式放开）；scope 默认三类全含。
  - **SDK**（FR-8 Phase 2 追加，见 FR-8 接口草图）：`db.stats_usage() / stats_winrate() / stats_wws() / stats_card(name)` 薄封装同一 canonical SQL。
  - **导出追加**：见 FR-7（赛事三件套，只加不删）。

## 6.2 同名归组规则（name_group，数据建模硬约束）

以下全部视为**不同名**：ex 后缀（獒教父 vs 獒教父ex）、ACE SPEC 标志（大师球 vs 大师球 ACE SPEC）、owner 前缀（喵喵 vs 火箭队的喵喵）。
以下视为**同名**：不同插画/人物的"博士的研究"、"老大的指令"[^1^]。
归组 key = 规范化完整卡名；`species` 单列用于检索。归组规则表人工维护、可追加。
V-UNION：4 个部件卡面同名（如"超梦V-UNION"），归同 name_group，但 deck_limit 按部件各 1 另计（部件间关系见 6.3 `union_part_of`）。

## 6.3 卡牌关系（card_relations）

`relation_type ∈ {evolves_from, evolves_to, mentions, reprint_of, union_part_of, name_group}`。
- evolves_*：由 evolves_from_text 解析生成。**训练家宝可梦（owner）进化链内部封闭**——同 owner 宝可梦只能由同 owner 宝可梦进化而来（火箭队的/莉莉艾的/竹兰的/玛俐的/N的 等所有 owner 组均适用，不限火箭队）[^16^]，校验器依赖此约束。
- mentions：卡名词典全文扫描自动生成 + 抽样人工审核，服务于 AI 检索 combo。
- reprint_of：跨系列同名卡归组。
- union_part_of：V-UNION 部件 → 组合体（配合 `union_position` 方位字段，4 部件齐全性见 FR-2.3）。

## 6.4 效果文本策略（本期边界）

- `text_raw` 逐字保留，**绝不做术语规范化**（朱紫起"气绝"改"昏厥"，新旧卡用词不同）；检索层另建同义词索引。
- 本期仅叠加**粗粒度标签**（抽牌/检索/铺伤/控制/回复…，词表 ≤20，自动标注 + 人工抽检），不做效果 DSL。谜之化石类"训练家卡当宝可梦"等特殊行为卡以 effect_tags 标注。
- 效果 DSL 属于下游规则引擎职责，与静态数据分离（TCG ONE 先例[^19^]）。

---

## 7. 数据模型（Phase 1 全量）

设计原则：①合法性 = 赛制标记 + 快照动态判定，不落布尔值；②原文与派生分层；③同卡多印刷独立成行；④枚举一律开放字符串 + 词表文件，不写死（超级进化ex、FUR 罕贵度等新机制直接进库）；⑤导出与 SDK 字段只加不删（FR-6.2）。

### 7.1 `sets` 系列表

简中商品编号体系多样：CS（日月/剑盾）、CSV（朱紫）、独占编号（收集啦151 旅）、CSVH（嗨皮组合）、CBB（宝石包）、SM-P/SV-P/30th-P（特典）等；"30周年庆典"简中版未划分系列[^15^]，`era` 词表需可追加（含"未划分"取值）。

**主键口径（M1 实测）**：mik 源对特典系列（SMP/SSP/SVP/30thP）的 product 级 `setCode='PROMO'`（内部分组值），与目录 setId 及卡级 setCode 不一致；**sets 行主键一律用目录 set_id**（= 卡级 setCode，如 `30thP`），否则 sets 行与 cards.set_id 错位、对账必炸。mik 垃圾占位日期 `0001-01-01` 归一为 NULL（迁移 003）。

| 字段 | 类型 | 说明 |
|---|---|---|
| set_id | TEXT PK | 商品编号，如 CSV1C（= 朱&紫"亘古开来"） |
| name_zh | TEXT | 系列名（"亘古开来""共逐荣光"等） |
| era | TEXT | 太阳&月亮 / 剑&盾 / 朱&紫 / 特典 / 未划分（开放词表） |
| release_date | DATE | 发售日 |
| regulation_mark | TEXT | 该系列卡牌的赛制标记 |
| expected_count | INT NULL | 官方公布收录数（对账用）。mik 源口径 = `cardsNum` = **含编号外卡的全量数**（M1 实测 CSM2aC=194 = 编号内 171 + 编号外 SR 23）。**注意：cardsNum ≠ 卡面分母**（v1.11 task 030，A2 实测翻案：CS4DaC cardsNum=441 vs 卡面分母 414），卡面分母见 `card_face_total` |
| expected_secret_count | INT NULL | 官方公布的编号外卡数（SR/HR/UR/FUR 等超出分母部分）；mik 源无拆分数据**留 NULL** |
| card_face_total | INT NULL | **卡面分母（种子口径，v1.11 新增）** = 商品主列表收录数。来源优先级：①人工实测（A2 比对数据点）② TCGdex zh-cn 壳 `cardCount.official`（过 sanity 门才播种）③ CBB* 宝石包按包播种（PPNN 复合编号，分母=包内卡数）。种子文件 `config/set_card_face_totals.yml`；未覆盖系列留 NULL（不猜测） |
| source / fetched_at | TEXT | 溯源 |

### 7.2 `cards` 卡牌主表

**编号与主键规则**：
- `card_id = {set_id}-{number}`；`number` 为纯序号（保留前导零，如 `009`；编号外卡用官方实际印刷序号，如 `128`），印刷分母另存 `number_display`（如 `009/127`）。
- 特典卡：`set_id` 取卡面商品编号（如 `30th-P`），`number` 取 PROMO 序号（如 `001`），即 `30th-P-001`。
- 同 `set_id + number` 撞车（同号异画/促销复刻）：`card_id` 追加 `-a`/`-b` 后缀并人工登记原因（罕见情况）。
- 白名单旧卡：每次历史印刷独立成行、归属其原系列；合法性按名称归组判定而非 card_id（见 FR-3.1）。

| 字段 | 类型 | 说明 |
|---|---|---|
| card_id | TEXT PK | `{set_id}-{number}`，如 CSV1C-009 |
| set_id | TEXT FK | |
| number | TEXT | 纯序号（保留前导零，如 009） |
| number_display | TEXT | 卡面印刷编号展示（如 009/127、PROMO_001/30th-P）。**v1.11 口径**：分母 = `sets.card_face_total`（种子覆盖系列，= 卡面分母）；种子未覆盖系列**只显示分子不带分母**（不再用 mik cardsNum 伪装卡面口径）；CBB* 宝石包按包分母（PPNN/包内卡数）。分子始终 = cardIndex 逐字 |
| name_full | TEXT | 完整卡名（含 ex/火箭队的前后缀） |
| species | TEXT NULL | 宝可梦种名（检索用） |
| owner | TEXT NULL | 训练家宝可梦归属（"火箭队""莉莉艾""竹兰""玛俐""N"等，开放词表） |
| card_type | TEXT | pokemon / trainer / energy |
| regulation_mark | TEXT | G/H/I…（卡面原值；"视作"覆盖不走本字段，见 mark_overrides） |
| rarity | TEXT | 罕贵度（开放词表，兼容 FUR 等新罕贵） |
| stage | TEXT NULL | 基础/1阶/2阶/超级进化/VMAX…（开放） |
| hp | INT NULL | |
| types | JSON | 属性数组（通常为 1 个，前瞻兼容双属性；词表含 草/火/水/雷/超/斗/恶/钢/妖/龙/无） |
| evolves_from_text | TEXT NULL | 卡面印刷原文 |
| evolves_from_id | TEXT NULL FK | 解析出的卡牌引用 |
| evolution_chain_id | TEXT NULL | 派生：同链共享 ID |
| rule_box_type | TEXT NULL | ex / gx / tag_team_gx / radiant / v / vmax / vstar / v_union / mega_ex（前瞻）…（开放词表） |
| has_rule_box | BOOL | 派生查询位 |
| is_tera | BOOL | 太晶/星晶宝可梦标志（ex 的附加属性，rule_box_type 维持 ex 不变）。**v1.11 派生口径**：mik 源无太晶信号（task 020 实测翻案 v1.4 ⑤旧注），走 mapping 层富化——`external_ids(mik_en)` 印刷级桥 → ptcd EN 卡 `subtypes` 含 `Tera`（CLI `map-tera`，幂等可重跑）；无桥/未解析入清单不猜。太晶"备战区不受招式伤害"规则文**不在 text_raw**（mik 源不含规则框文本），结构化归 Phase 3 |
| union_position | TEXT NULL | V-UNION 部件方位：左上/右上/左下/右下；部件组合关系见 card_relations.union_part_of |
| prize_cards | INT | 昏厥时对手获得奖赏卡数，默认 1（ex=2；TAG TEAM GX=3、V-UNION=3〔仅开放赛制〕；超级进化ex=3〔前瞻，简中尚未发售〕） |
| deck_limit | INT | 卡面/机制固有上限：默认 4；ACE SPEC=1；光辉=1；V-UNION 部件各=1（以卡面规则框为准）。赛制级禁限（禁卡=0 张）由快照叠加判定，不改写本字段 |
| is_ace_spec | BOOL | |
| abilities | JSON | [{name, text}] 数组（兼容一卡多特性） |
| attacks | JSON | [{name, cost:[{type,count}] 保序, cost_modifier NULL/"+"（v1.4 增量）, damage_base INT NULL, damage_modifier NULL/+/-/×, effect_text}] |
| weakness | JSON NULL | {type, value} |
| resistance | JSON NULL | {type, value}（可空） |
| retreat_cost | INT NULL | |
| trainer_subtype | TEXT NULL | 物品/支援者/竞技场/宝可梦道具 |
| provides | JSON NULL | 能量卡：提供的能量类型数组（特殊能量含效果文本于 text_raw） |
| is_basic_energy | BOOL | 派生：基本能量（草/火/水/雷/超/斗/恶/钢/妖；妖仅日月时代发行）。合法性按快照 `allowed_basic_energy_types` 判定（FR-3.2），**无全局特判** |
| text_raw | TEXT | 卡面文字逐字保留（特性/招式/训练家效果文）。**不含规则框文本**（mik 源不提供；GX/V/ex/太晶等规则框机制由 `rule_box_type`/`prize_cards`/`is_tera` 结构化承载） |
| effect_tags | JSON NULL | 粗粒度标签（6.4） |
| alias_of | TEXT NULL FK | **v1.11 新增**：mik 双重列示别名指向正本 card_id（实测 16 张字母编号基本能量 = 同系列数字编号条目的 raw 逐字段全等重复列示，卡面以数字编号为准；CS4DaC/CSVL1C 各 8）。alias 行保留（主键与总数口径不动），统计/去重场景应跟随正本 |
| name_en / name_ja / name_zh_tw | TEXT NULL | 跨语言映射（Phase 2 填充；name_en 来源 mik raw 英文桥 + TCGdex 交叉校验，name_ja 来源 dexId 链日文物种名 + 形态/机制词表（v1.6，v1.5 同 ID 共构作废）+ pokemon-card.com 抽样核对；**name_zh_tw 预留不填充**，v1.5 取消繁中方向） |
| source | TEXT | official_miniprogram / mik_moe / manual… |
| fetched_at | DATETIME | |
| status | TEXT | draft / active / deprecated |

**JSON 字段语义示例**（`attacks` / `weakness` / `resistance`，以本节为准）：

```json
"attacks": [
  {"name": "喷射火焰", "cost": [{"type": "火", "count": 2}, {"type": "无", "count": 1}],
   "cost_modifier": null, "damage_base": 90, "damage_modifier": null, "effect_text": ""},
  {"name": "猛撞", "cost": [{"type": "无", "count": 1}],
   "cost_modifier": null, "damage_base": 20, "damage_modifier": "+",
   "effect_text": "掷1次硬币若为正面，追加20点伤害。"},
  {"name": "双重爆发GX", "cost": [{"type": "水", "count": 2}, {"type": "无", "count": 1}],
   "cost_modifier": "+", "damage_base": 50, "damage_modifier": null,
   "effect_text": "追加1个任意属性能量时，追加50点伤害。（TAG TEAM GX 追加费用形态，卡面印刷 WWC+）"}
]
"weakness": {"type": "水", "value": "×2"}
"resistance": {"type": "斗", "value": "-30"}
```

- `damage_base` 为卡面固定伤害数值；无固定伤害时（如"造成附加能量数×30 点伤害"）为 NULL，`damage_modifier` 取 `+` / `-` / `×`，具体数值由 `effect_text` 表达，本期不做结构化。
- `cost_modifier`（v1.4 增量字段，字段只加不删）：cost 尾部 `"+"` = 追加费用标记（TAG TEAM GX 实测形态 "WWC+"，追加能量触发追加效果），无追加费用时为 NULL；非尾部 "+" 属未知形态，解析器抛错不猜测（M1 实测口径，task 005）。
- `weakness.value` / `resistance.value` 按卡面原样存字符串（"×2" / "-30"）。

### 7.3 其余表

```sql
card_relations(card_id, related_card_id, relation_type, confidence, source,
               PRIMARY KEY(card_id, related_card_id, relation_type));
-- relation_type ∈ {evolves_from, evolves_to, mentions, reprint_of, union_part_of, name_group}

name_groups(group_key PK, display_name, rule_note);          -- 同名归组 + 特殊规则注释
cards_name_group(card_id, group_key);

legality_snapshots(                                           -- 环境快照
  snapshot_id PK, format TEXT,            -- standard / open（开放字符串，兼容历史第三赛制）
  effective_from DATE, effective_to DATE NULL,
  allowed_marks JSON,                     -- ["G","H","I"]
  allowed_basic_energy_types JSON,        -- ["草","火","水","雷","超","斗","恶","钢"]；开放赛制含"妖"
  whitelist_cards JSON,                   -- [{name_full, note}]（按赛制独立）
  banned_cards JSON,                      -- [{name, ability_or_attack, note}]
  mark_overrides JSON,                    -- [{card_id, mark, note}] 卡级"视作"覆盖（天空之柱视作B）
  latest_text_overrides JSON,             -- 白名单旧卡 → 最新文本 card_id（历史快照冻结）
  source_url TEXT, created_at DATETIME);

errata(errata_id PK, card_id FK, effective_from DATE,
       corrected_text TEXT, notice_url TEXT);                 -- 不覆盖 text_raw

rules_documents(doc_id PK, title, version_label, effective_from,
                source_url, local_path, note);                -- 规则书/赛场规则/公告

scrape_runs(run_id PK, source, started_at, finished_at,
            card_count, ok_count, question_count, missing_count,
            lists_path, status, manifest_hash);               -- 三清单日志（FR-1.4）+ manifest

external_ids(card_id FK, system TEXT, external_id TEXT,
             PRIMARY KEY(card_id, system));                   -- Phase 2 跨语言对齐（v1.5）：
                                                              -- system ∈ {mik_en, tcgdex, pokemon_card_jp}

meta(key PK, value);                                          -- schema_version 等库级元信息（FR-6.1）
```

**索引**（服务 S1 检索场景）：`cards(name_full)`、`cards(set_id)`、`cards(regulation_mark)`、`cards(species)`、`cards(status)`、`cards(is_basic_energy)`、`cards(is_tera)`；`card_relations(related_card_id)`；`legality_snapshots(format, effective_from)`。

### 7.4 规模估算

简中至今全卡池（含多罕贵复刻、编号外卡、基本能量的全部印刷行——基本能量按全量印刷入库并以 `is_basic_energy` 标记）**实测 12,420 张行**（M1 对账，条目 setCode 去重口径；129 系列），standard（G/H/I + 白名单）合法子集**实测 5,320 张**、open 12,413 张（M2 `legal_at('2026-08-01')`）；纯文本形态下 SQLite 数据库与 JSONL 导出合计 <100MB，SQLite 无压力。

---

### 7.5 赛事卡组（Phase 2 扩展，v1.8 新增，FR-9）

```sql
tournaments(
  tournament_id  TEXT PRIMARY KEY,   -- {source}:{源侧id} 口径（mik: tournamentId；limitless: id；pcc: event_holding_id），防跨源碰撞（FR-9.6）
  source         TEXT NOT NULL,      -- mik_moe / limitless / pokemon_card_jp
  series_id      TEXT,               -- mik 系列 id（可空）
  name           TEXT NOT NULL,
  tier           TEXT,               -- city/advanced/super/master/cl/pjcs/regional…（开放词表 config/vocabularies/tournament_tiers.yml）
  tier_coef      REAL,               -- 物化自词表的 tier 系数（FR-9.6 事实完整性：SQL 消费方免读词表）
  division       TEXT,               -- master/senior/junior/无（开放词表）
  date           DATE,               -- 举办日
  location       TEXT,
  participant_count INTEGER,
  topcut_slots   INTEGER,            -- 淘汰赛名额（B 层 q0 = topcut_slots / participant_count 的分子）
  format         TEXT,               -- standard / open
  regulation_mark TEXT,              -- 赛制标记区间（GHI…）→ 直连合法性快照判定语境
  format_end     TEXT,               -- 截止系列（CSV10C）
  is_qual        BOOLEAN,            -- 预赛场次（统计默认排除，--include-qual 放开）
  is_team        BOOLEAN,            -- 双卡组/团体赛制（统计默认排除，--include-team 放开）
  official_url   TEXT,               -- 官方公告链接（交叉核对）
  fetched_at     DATETIME);

decks(
  deck_id        TEXT PRIMARY KEY,   -- {source}:{源侧id} 口径；**卡组内容实体**（同一套 60 张清单全源一行：
                                     -- mik deckId 按内容去重，可被多名选手/多场赛事共用——v1.10 续实测订正）
  archetype_id   TEXT,               -- variantId / 自动归类 id（内容级：mik deck/detail 的 variant 字段）
  archetype_name TEXT,               -- 卡组归类名（沙奈朵…）
  deck_code      TEXT,               -- 小程序分享码（可空）
  mapping_status TEXT NOT NULL,      -- full(≥95%) / partial / unmapped（FR-9.1）
  mapped_ratio   REAL,
  source         TEXT NOT NULL,
  fetched_at     DATETIME);

deck_appearances(                    -- 出战条目：一套内容在一次赛事取得的一个名次（统计"卡组数"的口径单元）
  deck_id        TEXT NOT NULL REFERENCES decks(deck_id),
  tournament_id  TEXT NOT NULL REFERENCES tournaments(tournament_id),
  rank           INTEGER NOT NULL,
  points         REAL,
  player_ref     TEXT,               -- 官方选手编号（pinCode；隐私最小化，不存昵称）
  record_wins    INTEGER,            -- A 层逐局战绩（Limitless standings 按 选手×赛事；可空 = 源无此数据）
  record_losses  INTEGER,
  record_ties    INTEGER,
  source         TEXT NOT NULL,
  fetched_at     DATETIME,
  PRIMARY KEY(deck_id, tournament_id, rank));

deck_cards(
  deck_id        TEXT NOT NULL REFERENCES decks(deck_id),
  card_id        TEXT REFERENCES cards(card_id),  -- 可空：映射不上不猜
  count          INTEGER NOT NULL,
  raw_name       TEXT NOT NULL,      -- 源侧原始卡名（保真）
  stat_scope     TEXT NOT NULL,      -- pokemon / supporter / stadium / other（派生过滤位，FR-9.3）
  PRIMARY KEY(deck_id, card_id, raw_name));
```

- 物化视图（v1.10，FR-9.7）：`v_stat_deck_cards`（四表联查[deck_cards ⋈ decks ⋈ deck_appearances ⋈ tournaments] + 统计范围过滤 + group_key 预联，行粒度 = 出战条目 × 卡）、`v_tournament_weights`（赛事静态权重件）随迁移落库、导出 DB 自带；视图只封装过滤与连接，业务公式只在 canonical SQL（`ptcgdb/stats/sql/`）。
- 派生统计（task 028+）：按 name_group × 赛事/时间窗聚合的使用率、名次加权分、top-cut 转化率；只消费 `stat_scope ∈ {pokemon, supporter, stadium}` 且 `mapping_status='full'` 的卡组（"卡组数" = 出战条目数，见 deck_appearances）。
- `deck_cards` 保真全量（60 张）落库——validate_deck 真值校验（task 026）与统计复用同一事实源；统计层的范围过滤只发生在聚合查询。

## 8. 架构与管线

```
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ tcg.mik.moe   │   │ 官方小程序    │   │ 赛制页/公告页/    │
│ (主源, D1=B)  │   │ (不可得, P2)  │   │ "特别的卡牌"外链  │
└──────┬───────┘   └──────┬───────┘   └──────┬───────────┘
       ▼                  ▼                  ▼
┌─────────────────────────────────────────────────┐
│ raw/  append-only 原始层（JSON/HTML + manifest）  │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ normalize/  Pydantic 校验 + 字段归一 + 派生计算    │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ SQLite（WAL）  draft → 校验 → active              │
│ migrations/ = PRAGMA user_version + 顺序 SQL     │
└──────┬───────────────────────────────┬──────────┘
       ▼                               ▼
┌──────────────┐              ┌─────────────────────┐
│ CLI (typer)  │              │ dist/ 导出（七件套）  │
└──────┬───────┘              │ manifest.json       │
       ▼                      │ cards/sets/         │
┌──────────────┐              │ relations.jsonl     │
│ ptcgdb.sdk   │              │ legality.json       │
│ open_db /    │              │ ptcg-cn.db (ro)     │
│ open_jsonl   │              │ checksums.sha256    │
└──────────────┘              │ schema.md           │
                              └─────────────────────┘
┌─────────────────────────────────────────────────┐
│ monitor/  每日 cron：总量探测 + 页面hash → 变更提案 │
└─────────────────────────────────────────────────┘
```

**技术栈**：Python 3.12；httpx（HTTP）+ tenacity（重试）；**Pydantic v2**（管线校验 + SDK 返回模型）；**SQLAlchemy 2**（持久层——持久层与校验层语义分离，不采用 SQLModel，避免与 Pydantic 版本耦合的已知问题）；schema 迁移 = `PRAGMA user_version` + 顺序 SQL 脚本（FR-6.4）；Typer（CLI）；pytest + 契约测试 + 双后端一致性测试；ruff；sqlite-utils（Ad-hoc 辅助，可选）。无外部服务依赖，全本地运行。

**目录结构**：

```
ptcg-cn-db/
├── pyproject.toml
├── ptcgdb/
│   ├── orm/             # SQLAlchemy 2 表定义（持久层）
│   ├── schemas/         # Pydantic 模型（校验层 + SDK 返回模型，frozen）
│   ├── scrapers/        # miniprogram.py / mikmoe.py / regulation.py
│   ├── normalize/       # 字段归一、能量符号、归组、进化链/太晶/能量派生
│   ├── validate/        # 对账与校验规则
│   ├── legal/           # 合法性引擎（快照判定、视作覆盖、同名计数）
│   ├── monitor/         # L0/L1 监控与提案生成
│   ├── export/          # 七件套导出 + checksums
│   ├── sdk/             # open_db / open_jsonl 双后端（FR-8）
│   ├── migrations/      # 顺序编号 SQL 迁移脚本
│   └── cli.py
├── data/
│   ├── raw/             # append-only 原始响应
│   ├── ptcg-cn.db
│   ├── snapshots/       # DB 版本快照
│   └── proposals/       # L1 变更提案
├── config/
│   ├── vocabularies/    # 属性/罕贵度/标签/owner 词表
│   ├── name_group_rules.yml
│   └── legality/        # 人工维护的快照 YAML
├── tests/
└── CHANGELOG.md         # 四段式：Added / Changed / Deprecated / Removed
```

---

## 9. 更新机制细则（对应 FR-5）

### 9.1 三级自动化

| 级 | 对象 | 流程 | 人工量 |
|---|---|---|---|
| L0 | 新卡 | 每日总量探测 → 增量抓取 → draft → 校验（含三清单归零）→ active | 每包 ~30 分钟确认 |
| L1 | 赛制 | 页面 hash 监控（赛制页 + 公告列表页 + **开放赛制"特别的卡牌"外链页**）→ 提案 YAML → **人工 review** → apply 新快照 | 每次 ~10 分钟 |
| L2 | 勘误/规则 | 人工 YAML → 导入 → 校验 | 每次 ~15 分钟 |

### 9.2 变更提案格式（L1 产物示例）

```yaml
proposal_id: 2026-09-16-standard-rotation
detected_at: 2026-09-16T08:00:00+08:00
source_url: https://www.pokemon.cn/tcg-rules-regulation
parsed:
  format: standard
  effective_from: 2026-09-16
  allowed_marks: [H, I, J]
  allowed_basic_energy_types: [草, 火, 水, 雷, 超, 斗, 恶, 钢]
  whitelist_added: [...]
  whitelist_removed: [...]
  banned_changes: []
  mark_override_changes: []        # 视作覆盖的增删（card_id 级）
raw_excerpt: <赛制页正文节选>
status: pending_review
```

### 9.3 规则文档版本化

规则书/赛场规则/规则调整公告 → `rules_documents` 表（版本标签、生效日、原文路径）。规则引擎（Phase 3+）按规则版本参数化。勘误经 `errata` 表按生效日叠加，`effective_text()` 统一解析优先级：**勘误（最新生效）> 最新印刷文本 > 原始 text_raw**。

### 9.4 失败与降级

- 主源（mik.moe）改版/停服 → 降级人工导入 / 寻求第二镜像；官方小程序接口有四层防护（M0 实测），不作为降级指望。解析器配**契约测试**（固定字段断言），静默失败视为事故。
- 数据冲突仲裁：官方源 > 社区镜像 > 人工录入；每条数据带 `source + fetched_at` 溯源。
- 新弹发售前预读官方商品页，提前扩充词表（罕贵度、rule_box_type、owner），避免新机制入库即校验失败（如 30周年庆典的 FUR 罕贵[^15^]）。

---

## 10. 验收标准（Phase 1a/1b/1c）

| # | 标准 | 度量 |
|---|---|---|
| A1 | 覆盖完整 | G/H/I 全部系列 + 开放赛制涉及系列入库，系列级对账（含 expected_secret_count）100% 通过；白名单逐卡核对无缺（标准：18 特典 + 26 旧卡 + 8 能量；开放：32 旧卡 + 9 能量，分赛制核对） |
| A2 | 字段正确 | 抽样 100 张与官方小程序卡面逐字段比对，字段级准确率 100%（text_raw 逐字一致） |
| A3 | 机制字段 | ex/特性/规则框/ACE SPEC/**owner（5 组训练家宝可梦）/V-UNION 部件**/进化链字段覆盖抽样 50 张特殊卡全部正确；**太晶：简中暂无样本（M1 全量实测未触发），样本出现后补验**；prize_cards 与官方规则一致（ex=2；TAG TEAM GX=3、V-UNION=3 用开放赛制样卡核对；**超级进化ex=3 为前瞻规则，简中发售后补验**） |
| A4 | 合法性引擎 | `legal_at('2026-08-01', standard)` 结果与赛制页逐卡一致；构造用例 ≥12 组全部通过（含：博士的研究跨插画、ACE SPEC、各 owner 前缀、**妖能量：standard 不合法 / open 合法**、**视作B 覆盖：天空之柱 CSM2D-339 合法而同名其他印刷不合法**、开放赛制 32 种白名单抽样） |
| A5 | 更新机制 | 模拟一次赛制页变更 → 提案生成 → apply → 新快照生效；旧快照可查询；历史快照 override 冻结验证 |
| A6 | 回滚 | 故意制造一次脏合入 → 一键回滚至上一版本，数据无损 |
| A7 | 导出契约 | dist/ 七件套生成；`checksums.sha256` 校验通过；`manifest.json` 含双轨版本号；JSONL 可被下游脚本流式读取 |
| A8 | SDK 契约 | `open_db` 与 `open_jsonl` 双后端对同一查询集（含 `legal_at` / `effective_text`）返回一致结果（契约测试）；返回类型不暴露 ORM 对象；`schema_version` 可读 |

**测试策略**：pytest 单测（归一/归组/合法性判定）+ 契约测试（解析器）+ **SDK 双后端一致性测试** + 黄金样本（20 张手工核对的卡牌 JSON 做回归基线，覆盖 ex/太晶/ACE SPEC/V-UNION/妖能量/视作覆盖卡各至少 1 张）。

---

## 11. 里程碑

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M0 | D1 决策 + 主源接口可行性验证（抓包 1 个接口跑通） | 1 天 |
| M1 (1a) | schema + raw 层 + 首批全量入库 + 校验报告 | 3~4 天（主源走通时）；若 M0 否决小程序路线、改走 mik.moe 镜像为主源，+1~2 天 |
| M2 (1b) | 环境快照 + 合法性引擎 + 版本化/回滚 + 导出七件套 + SDK 基础 | 3~4 天 |
| M3 (1c) | L0/L1 监控管线 + 提案生成 + 通知 | 2 天 |
| M4 | 验收（A1~A8）+ 文档收尾 | 1 天 |
| M5 (P2) | 数据质量收口（先行部分）：derive 跨系列进化解析（技术债） | 1 天 |
| M6 (P2) | 跨语言映射 EN+JP：EN 桥提取 + TCGdex 接入/系列级对账 + JP 填充与官方抽样核对（v1.5，不做繁中） | 2~3 天 |
| M7 (P2) | 同名计数引擎 + 卡组校验器 SDK（`validate_deck` 双后端）+ 验收 | 2~3 天 |
| M8 (P2) | A2/A3 卡面人工比对（需用户在场，收尾做）+ Phase 2 收官文档 | 0.5~1 天 |
| M9 (P2 扩展，v1.8/v1.10 拆分) | 赛事卡组管线 + 统计基建（FR-9）：**M9-1** CN mik 采集入库（task 027）→ **M9-2** 统计与查询层：迁移 004（三表 + 视图）+ canonical SQL + `stats` 子命令组 + `query` 只读 SQL + 导出三件套（task 029）→ **M9-3** EN Limitless 接入与映射过滤（task 028）；JP 壳可选后置；统计范围 = 宝可梦/支援者/竞技场 | 3~4 天 |

---

## 12. 风险登记册

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 小程序接口有签名/风控，抓包失败 | 中 | 高 | M0 先做可行性验证；降级 tcg.mik.moe 全量镜像（其数据同源自官方[^7^]） |
| 抓包小程序接口违反其服务条款 | — | — | **D1 已否决该路线（M0）**，风险不成立；若未来重估抓包路线，须重新显式权衡：仅只读抓取 + 严格限速，被限制即退回镜像路线 |
| 官网改版导致解析器失效 | 中 | 中 | 契约测试 + 告警；raw 层可重放 |
| 漏看勘误/赛制公告 | 低 | 高（污染模拟结论） | hash 监控（含"特别的卡牌"外链）+ 赛季日历全量对账双保险 |
| 数据字段与卡面不符（源站自身错误，有先例[^9^]） | 中 | 中 | 双源交叉校验 + 三清单日志 + A2 抽验 |
| 版权问题 | — | — | 卡面文本版权归宝可梦（上海）/TPC；**仅限本地研究与工具自用，数据库不公开分发**（本项目不采集卡图） |
| 简中套装结构与国际版不一致导致映射错位 | 高 | 低（Phase 2 才用） | 卡级桥字段逐卡对齐（mik 英文桥）天然免疫套装结构差异；external_ids + 置信度分档 + TCGdex 交叉校验 + 官方 JP 抽样核对 |
| 新弹引入简中首次出现的机制（30周年庆典：超级进化/FUR 罕贵/GX 复刻[^15^]） | 高 | 低 | schema 开放字符串 + 词表可追加；发售前预读商品页扩词表（9.4） |
| TCGdex 实装 zh-cn 卡级数据（已收录全部系列壳、set_id 与本库一致，卡级 0%——2026-08-01 实测）[^11^]，自建数据层价值下降 | 低 | 中 | 持续跟踪；届时可转为"消费 TCGdex + 自维护简中合法性/赛制差异层"——合法性引擎与 SDK 是本项目的差异化价值，不受影响 |

---

## 13. 附录 A：当前赛制白名单快照（官方赛制页，2026-07-16 版）[^1^]

**标准赛制标记**：G、H、I + **8 种**基本能量卡（草/火/水/雷/超/斗/恶/钢）。
**开放赛制**：太阳&月亮/剑&盾/朱&紫全系列 + 特典 + **9 种**基本能量（含妖）[^13^]。

**特典卡（18 种，30th-P）**：妙蛙种子 001、小火龙 002、杰尼龟 003、菊草叶 004、火球鼠 005、小锯鳄 006、草苗龟 010、小火焰猴 011、波加曼 012、藤藤蛇 013、暖暖猪 014、水水獭 015、木木枭 019、火斑喵 020、球球海狮 021、敲音猴 022、炎兔儿 023、泪眼蜥 024（PROMO_xxx/30th-P）。

**过去系列卡牌（标准赛制 26 种 + 各种基本能量）**：宝可梦捕捉器、宝可梦交替、宝可装置3.0、宝可梦中心的姐姐、博士的研究、裁判、超级球、巢穴球、反击捕捉器、反击增幅器、粉碎之锤、改造之锤、高级球、活力头带、讲究腰带、精灵球、老大的指令、能量回收、能量输送、能量再利用、能量转移、朋友手册、伤药、神奇糖果、西餐厨师、学习装置、各种基本能量卡。

**过去系列卡牌（开放赛制 32 种）**：在标准 26 种基础上多出捕虫少年、离洞绳、谜之化石、模仿少女、能量签、千金小姐 共 6 种（2026-08-01 按赛制页正文逐名核定；种子文件 `config/legality/open-2026-07-16.yml` 为结构化事实来源）。

**特殊同名规则**：博士的研究、老大的指令 —— 不同人物/插画均视同名。

**赛制标记"视作"覆盖（已知先例）**：天空之柱（CSM2D 339/342）赛制标记视作 B[^13^]；完整清单以赛制页"特别的卡牌"外链为准。

**开放赛制禁卡表（同日版）**：玛夏多（特性：破罐破摔）、阿塞萝拉、全满药（按名称+特性/招式名匹配生效）。

## 14. 决策记录

- **D1 数据源路线**：✅ 已定（2026-08-01，M0/task 001）= **路线 B：tcg.mik.moe 为主源**。依据：官方小程序接口有 JWT 登录态 + 请求/响应 AES 加密 + 签名四层防护，还原需反编译 wxapkg，超出 M0 验证标准且有服务条款风险；mik.moe `/api/v3/card/*` 无鉴权明文 JSON、字段完整（含 effectId 归组、regulationLegal 交叉校验、英文映射等意外收获）。接口文档见 `docs/data-sources.md`。

（原 D2 存储位置已确定为项目内 `data/`，不再是待决策项。）

## 15. 参考来源

[^1^]: 宝可梦中国官网 · 赛制（更新日期 2026-07-16）：https://www.pokemon.cn/tcg-rules-regulation
[^2^]: 宝可梦卡牌简中首次禁牌公布（2023-05）：https://www.iyingdi.com/tz/post/5260892
[^3^]: 关于宝可梦卡牌赛制调整和规则调整的说明（2025-12-07）：https://www.pokemon.cn/tcg/other/19843.html
[^4^]: 简中PTCG更新解析（什么值得买，2026-07-01）：https://post.smzdm.com/p/axkge7z3
[^5^]: 宝可梦中国官网 · 集换式卡牌游戏产品页：https://www.pokemon.cn/category/tcg/product
[^6^]: 卡表公开！宝可梦卡牌官方小程序"宝可梦卡牌会员"（2026-03-10）：https://www.pokemon.cn/tcg/other/post_15.html
[^7^]: Cryst's Cards Database · 关于我们：https://tcg.mik.moe/about
[^8^]: 繁中训练家网站 · 赛制：https://asia.pokemon-card.com/tw/rules/regulation/
[^9^]: GitHub · type-null/PTCG-database（EN/JP/繁中爬虫，明确亚洲站不含简中）：https://github.com/type-null/PTCG-database
[^10^]: GitHub · PokemonTCG/pokemon-tcg-data：https://github.com/PokemonTCG/pokemon-tcg-data
[^11^]: GitHub · tcgdex/cards-database（10+ 语言、MIT；zh-cn 列入路线图）：https://github.com/tcgdex/cards-database
[^12^]: 神奇宝贝百科 · 赛制标记H的卡牌：https://wiki.52poke.com/wiki/Category:赛制标记H的卡牌
[^13^]: 宝可梦中国官网 · 2023-11-06 赛制公告（开放赛制 9 种基本能量含妖；"天空之柱"赛制标记视作 B）：https://www.pokemon.cn/tcg/other/2023110601.html
[^14^]: 宝可梦中国官网 · 2024-05-19 公告（太阳&月亮限定赛制）：https://www.pokemon.cn/tcg/other/17158.html
[^15^]: 神奇宝贝百科 · 30周年庆典（2026-09-16 全球同步，新罕贵度 FUR，历史卡复刻）：https://wiki.52poke.com/wiki/30%E5%91%A8%E5%B9%B4%E5%BA%86%E5%85%B8%EF%BC%88TCG%EF%BC%89
[^16^]: 神奇宝贝百科 · 朱&紫系列（简中太晶/古代未来/ACE SPEC/训练家宝可梦收录进度）：https://wiki.52poke.com/wiki/%E6%9C%B1%26%E7%B4%AB%E7%B3%BB%E5%88%97%EF%BC%88TCG%EF%BC%89
[^17^]: MTGJSON v5 Changelog（多形态导出、双轨版本化、checksums、四段式变更日志）：https://mtgjson.com/changelogs/mtgjson-v5/
[^18^]: TCGdex 开发者文档（REST/SDK/Query 构建器、静态数据与 API 同数据）：https://tcgdex.dev/
[^19^]: GitHub · axpendix/tcgone-engine-contrib（TCG ONE 效果 DSL 实现，静态数据与效果分离先例）：https://github.com/axpendix/tcgone-engine-contrib
[^20^]: GitHub · keeshii/ryuu-play（赛制 = 卡池集合 + 规则覆写的声明式建模）：https://github.com/keeshii/ryuu-play

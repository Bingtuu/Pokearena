# STATUS.md — 开发进展

> 每次工作会话开始时先读本文件；完成阶段性工作后更新。
> 最近更新：2026-08-01

## 当前状态

**阶段：M5 ✅ 完成（goal 驱动，2026-08-02）** —— task 019 归档：derive 跨系列进化解析技术债清偿（未解析 401→5，全库回退 + 链根跨库续走，31 系列重 ingest skipped=0，FR-2.3 六规则全过，A3 复跑豁免 386→5）；169 测试全绿。下一步 M6 跨语言映射 EN+JP（task 022~024）。M8（A2/A3 人工比对，需用户在场）收尾做。

## 入口

| 内容 | 位置 |
|---|---|
| 产品需求与技术方案（权威设计） | `docs/简中PTCG卡牌数据库_PRD与技术方案.md`（v1.5） |
| 工程约定 | `AGENTS.md` |
| 任务队列（开发标准循环） | `tasks/`（规范见 `tasks/README.md`，归档在 `tasks/done/`） |
| **主源接口文档** | `docs/mikmoe-api.md`（task 001 产物，M1 采集层必读） |
| 代码 | `ptcgdb/`（orm/schemas/migrations/cli + scrapers/normalize/validate + legal（引擎/种子/版本化）+ monitor（L0/L1/提案）+ export/sdk + accept（验收）） |
| 数据 | `data/ptcg-cn.db`（schema user_version=3；**12,420 张去重卡 active**；2 条环境快照）、`data/raw/mikmoe/`（全量 raw + manifest）、`dist/`（导出七件套，gitignore）、`reports/`（校验报告，git 跟踪） |
| 合法性种子 | `config/legality/`（standard/open 双赛制快照种子，官方赛制页 2026-07-16 版） |

## 里程碑（PRD 第 11 章）

- [x] **M0** D1 决策 + 主源接口可行性验证（1 天）—— **2026-08-01 完成（task 001），D1 = 路线 B**
- [x] **M1 (Phase 1a)** schema + raw 层 + 首批全量入库 + 校验报告（3~4 天；**走镜像路线，按 PRD 预算 +1~2 天 → 4~6 天**）—— **2026-08-01 完成（task 002~006）**：129 系列 / 12,420 张去重卡 active，六规则全过
- [x] **M2 (Phase 1b)** 环境快照 + 合法性引擎 + 版本化/回滚 + 导出七件套 + SDK 基础（3~4 天）—— **2026-08-01 完成（task 007~011）**：双赛制快照入库、`legal_at`/`effective_text`（A4 用例 24 组）、apply/冻结/回滚（A5/A6）、dist 七件套（A7）、SDK 双后端一致（A8）
- [x] **M3 (Phase 1c)** L0/L1 监控管线 + 提案生成 + 通知（2 天）—— **2026-08-01 完成（task 013~015）**：L0 全链路（探测→抓取→校验→active→快照后处理，真实 dry-run 零增量）；L1 三页监控（基线建立、零假阳性、提案=SnapshotSeed 超集被 legal-apply 直接消费、needs_manual 不猜测）；桌面/webhook 通知 + 提案闭环（applied 回写）+ L2 勘误导入（`legal-errata`，effective_text 联测）
- [x] **M4** 验收 A1~A8 + 文档收尾（1 天）—— **2026-08-01 完成（task 016~018）**：验收 runner 一键全过（A1 standard 55/55、open 61/61；A4/A5/A6/A7/A8 证据报告六项 PASS）、A2 抽样 100 张清单 + A3 自动校验 5,122 项次全过、AGENTS/README/PRD/CHANGELOG 状态一致
- [x] **M5 (Phase 2)** derive 跨系列进化解析（task 019）—— **2026-08-02 完成**：全库回退解析，未解析 401→5（仅剩化石无收录豁免），31 系列重 ingest skipped=0，FR-2.3 六规则全过，A3 复跑 5,122 项次全过
- [ ] **M6 (Phase 2)** 跨语言映射 EN+JP（task 021~024；v1.5 定：EN 桥 + TCGdex 同 ID 共构取 JP，不做繁中）
- [ ] **M7 (Phase 2)** 同名计数引擎 + 卡组校验器 SDK `validate_deck`（task 025~026）
- [ ] **M8 (Phase 2)** A2/A3 卡面人工比对 + Phase 2 收官（task 020，需用户在场，收尾做）

## 决策日志

| 日期 | 决策 | 状态 |
|---|---|---|
| 2026-08-01 | 数据形态为纯文本/结构化数据，不采集卡图 | ✅ 已定 |
| 2026-08-01 | 数据存储于项目内 `data/`（原 D2） | ✅ 已定 |
| 2026-08-01 | SQLAlchemy 2 替代 SQLModel；PRAGMA user_version 替代 Alembic | ✅ 已定（v1.3） |
| 2026-08-01 | **Python 环境定为 3.14.6**（用户安装；`.venv` 已用 3.14 重建，deps/pytest/ruff/init-db 全验证通过）。`requires-python = ">=3.12"` 收回 PRD 口径。原 3.11 暂行决策作废（task 002 后记） | ✅ 已定 |
| 2026-08-01 | **D1 = 路线 B：tcg.mik.moe 为主源**。理由：小程序接口有 JWT 登录态 + 请求/响应 AES 加密 + 签名四层防护（还原需反编译 wxapkg，超 M0 标准）；mik.moe `/api/v3/card/*` 无鉴权明文 JSON、字段完整且有意外收获（effectId 归组、regulationLegal 交叉校验、英文映射）。详见 `docs/mikmoe-api.md` 与 `tasks/done/001` | ✅ 已定 |
| 2026-08-01 | **跨语言映射 = EN 桥 + TCGdex，取消繁中、新增日文原版（PRD v1.5，task 021）**。依据：raw 自带英文桥字段（`setCodeEn/cardIndexEn/nameEn`）；TCGdex 英/日卡级 100% 覆盖且同 card ID 多语言共构，JP 零爬虫可得；繁中站采集成本高于收益。校验源矩阵：TCGdex zh-cn 已收录全部系列壳但卡级 0% → 系列级跨源对账落地，卡级跨源仍待实装；`name_zh_tw` 预留不填充；`external_ids.system ∈ {mik_en, tcgdex, pokemon_card_jp}` | ✅ 已定 |

## 已知临近事件

- **2026-09-16**：补充包"30周年庆典"全球同步发售（新罕贵度 FUR、可能引入超级进化/GX 复刻机制）——发售前需预扩词表（PRD 9.4）。
- TCGdex 已收录全部简中系列壳（set_id 与本库一致）但卡级数据 0%（2026-08-01 实测）；系列级跨源对账已列入 task 023，卡级实装持续跟踪（PRD 风险登记册）。

## 已知技术债 / 待立项

- ~~derive 跨系列进化解析缺口~~：**已清偿（task 019，2026-08-02）**——`resolve_evolution` 全库回退解析，401 → 5（仅剩化石道具库内无收录的合理豁免；另修正 10 条原误判豁免：化石道具卡在 SVP 有收录）。收敛报告 `reports/task019-evolution-resolution-20260802.md`。
- **A2/A3 卡面人工比对（M8）**：清单已就绪（`reports/sampling-a2-20260801.md` 100 张 / `sampling-a3-20260802.md` 50 张——A3 清单已随 task 019 复跑刷新），需用户在场比对（小程序无 API），另约协作 session。

## 进展日志

- **2026-08-01**：PRD 迭代至 v1.3（评审修订 + 外部调研：简中赛制核查、开源对标、数据基建接口设计）；建立 AGENTS.md / STATUS.md；确立 tasks/ 任务工作循环（`tasks/README.md`）。
- **2026-08-01**：**task 001 完成（M0 ✅）**。mitmproxy 抓包官方小程序 → 判定路线 A 不可行（JWT+加密+签名四层防护）→ 验证 tcg.mik.moe `/api/v3/card/*` JSON API 完全可行 → **D1 = 路线 B（mik.moe 主源）**。产物：`docs/mikmoe-api.md`、`tools/capture/`（可复用抓包环境）、API 样例。M1 预算调整为 4~6 天。
- **2026-08-01**：**task 002 完成（M1-1 ✅）**。项目骨架落地：pyproject + `.venv`、`ptcgdb/` 包（11 表 ORM 与 PRD §7 逐字段一致、PRAGMA user_version 幂等迁移、frozen Pydantic 核心模型、4 个初始词表、`ptcgdb init-db`）；pytest 2 绿、ruff 通过。下一步 task 003：mik.moe 采集器 + raw 层。
- **2026-08-01**：Python 环境收口 3.14.6（`requires-python >=3.12` 收回 PRD 口径）。**启动 goal：完成 M1**（采集→入库→校验报告，限速红线 2s/请求+熔断，按任务循环自动 commit+push）。
- **2026-08-01**：**task 003 完成（M1-2 ✅）**。采集层全链路：限速 HTTP 层（2s/请求、退避、三路熔断）、mik.moe 三端点、append-only raw 层（sha256 manifest）、card 级断点续传、三清单+scrape_runs 落库、CLI `scrape sets/cards`。CSM1aC 211 张实测 7 分钟跑通，resume 重跑零请求；16 测试全绿（零网络）。发现并修复 product-list data 包装层偏差（文档已同步）。下一步 task 004：normalize + 入库管线。
- **2026-08-01**：**task 004 完成（M1-3 ✅）**。normalize + 入库管线落地：字段形态调查覆盖 211 张全部 distinct 取值（核证 N=龙/C=无，发现词表外罕贵度 S/SSR 已补词表）；fields/derive/ingest 三层 + `config/name_group_rules.yml`（§6.2 数据化）+ CLI `ptcgdb ingest --set`；CSM1aC 211 张全部入库 draft（skipped=0，抽查 10/10），31 测试全绿（7 张黄金样本 fixtures 逐字段断言，零网络）。疑点如实记录：特殊能量 provides 未结构化（question）、系列内赛制标记混合（sets 存 "A,B"）。下一步 task 005：校验 draft→active + 校验报告。
- **2026-08-01**：**task 005 完成（M1-4 ✅）**。全量抓取 + 全量入库：129 系列 raw 齐（7 小时、限速 2s、零熔断），**按条目 setCode + 全局去重口径 12,420 张唯一卡全部入库 draft，skipped=0、对账 100%**。关键口径发现：附赠能量卡跨系列列表重复列出、按条目自身 setCode 归属（目录口径会产生 15 个假缺口，task 006 对账必须用去重口径）。实测驱动修复全链路：V/VMAX/VSTAR/V-UNION/TAG TEAM GX/战斗流派/Radiant/朱紫 ex/古代·未来/ACE SPEC（新增 NON_RULE_BOX_MECHANICS）+ 罕贵度词表补全（无标记/S/SSR/A/宝石包符号 ●◆★/ACE）+ eras 补 30th→特典；64 测试全绿（黄金样本逐字段断言）。全量形态调查收敛：简中暂无太晶卡样本。详见 `tasks/done/005` 完成总结。下一步 task 006：全量 validate + 校验报告 + draft→active。
- **2026-08-01**：**task 006 完成（M1-5 ✅）→ M1（Phase 1a）完成**。FR-2.3 全量校验落地：六规则全过（12,420 张、抽样 689 张一致率 100%），**12,420 张卡全部 draft→active**，报告 `reports/validation-20260801T124141Z.md`（git 跟踪）。全量首跑修复 4 处：对账改条目 setCode+去重口径、raw 全局索引定位（跨目录能量卡）、V-UNION 同名多组按 4 件切组（CSEC 莫鲁贝可两组）、规则 1 源数据缺失豁免（SSP-195 mik description 为空，如实注明）；64 测试全绿、ruff 通过。详见 `tasks/done/006`。
- **2026-08-01**：**启动 goal：完成 M2**（环境快照 + 合法性引擎 + 版本化/回滚 + 导出七件套 + SDK 基础，task 007~011，TDD，纯本地不请求主源）。**task 007 完成（M2-1 ✅）**：官方赛制页逐名核定 → 双赛制快照种子（`config/legality/*.yml`）+ `ptcgdb/legal/seed.py` upsert 入库 + CLI `legal-seed`；standard（G/H/I + 8 能量 + 44 白名单）/ open（A~I + 9 能量含妖 + 50 白名单 + 3 禁卡 + 视作覆盖 CSM2DC-339→B）入库；白名单 94 名称库内全命中。修正 PRD 数据错误：开放白名单 34→32 种（PRD 升 v1.4）；发现 J 标记 18 张 = 30thP 特典卡本体。67 测试全绿、ruff 全净（顺手修了 tools/capture 两处 E501 遗留）。详见 `tasks/done/007`。
- **2026-08-01**：**task 008 完成（M2-2 ✅）**。合法性引擎落地：`ptcgdb/legal/engine.py`（快照选择 + FR-3.2 五步判定 + `effective_text` 勘误>最新印刷>原文三级解析），schemas 新增 `LegalityPool`/`EffectiveText`，CLI `ptcgdb legal --date --format`。A4 构造用例 24 组全过（博士的研究跨插画、妖能量双赛制、视作B 覆盖正反、禁卡优先两级、禁卡特性限定等）。真实库验证：standard 5,320 张 / open 12,413 张；open 排除恰好 7 张=禁卡表全命中（玛夏多只禁破罐破摔那张）；30thP 18 张走白名单入 standard。91 测试全绿、ruff 通过。详见 `tasks/done/008`。
- **2026-08-01**：**task 009 完成（M2-3 ✅）**。版本化与回滚落地：`ptcgdb/legal/versions.py`（apply_snapshot 备份→关旧开新→自动刷新 latest_text_overrides→双轨版本号→CHANGELOG 四段式；历史快照冻结守卫；rollback 一键还原）+ CLI `legal-apply`/`rollback`。A5/A6 测试 8 个全过；真实库副本演练：模拟赛制变更 apply→历史回放不漂移→冻结守卫拦截→rollback 复原。99 测试全绿、ruff 通过。详见 `tasks/done/009`。
- **2026-08-01**：**task 010 完成（M2-4 ✅）**。导出七件套落地：`ptcgdb/export/exporter.py`（Pydantic 模型序列化、WAL checkpoint 后复制 DB、checksums 不自签、schema.md 半自动生成）+ CLI `ptcgdb export --out`。A7 测试 8 个全过；真实导出 `dist/`：12,420 卡/129 系列/2 快照/21,818 关系，checksums 全部通过。107 测试全绿、ruff 通过。详见 `tasks/done/010`。
- **2026-08-01**：**task 011 完成（M2-5 ✅）→ M2（Phase 1b）完成**。SDK 双后端落地：`ptcgdb.sdk`（CardDatabase ABC + DbBackend/JsonlBackend + `open_db`/`open_jsonl`；schema_version/get_card/search_cards/sets/legal_at/effective_text/snapshots，frozen Pydantic 返回）；引擎抽纯函数核供双后端复用；legality.json 增 errata 键（additive，PRD §FR-7 同步）；`apply_migrations` 幂等写 meta.schema_version。A8 契约测试 + 真实库双后端全等（standard 5,320 / open 12,413 / search 喵喵 26 张）。121 测试全绿、ruff 通过。详见 `tasks/done/011`。**M2 goal 完成，待验收（M4）与 M3 监控管线。**
- **2026-08-01**：**task 012 完成（PRD v1.4 统一修订 ✅，goal 驱动）**。M1/M2 实测偏差 7 项全部并入 PRD：对账去重口径、attacks `cost_modifier`、PROMO setCode 主键口径、FR-2.3 规则 6/规则 1 豁免、太晶暂无样本、M2 已并入项核对、D1 决策结果全文同步（含 §7.4 规模改实测值）。一致性核验发现导出 schema `Attack` 模型缺 `cost_modifier`（导出/SDK 静默丢字段）——按 goal 停止规则报告、**用户放行并入**：补字段 + 导出断言。PRD 升 v1.4（修订记录完整），121 测试全绿、ruff 通过。详见 `tasks/done/012`。
- **2026-08-01**：**task 013 完成（M3-1 ✅）**。L0 新卡增量管线全链路：总量探测（cardsNum 比对）→ 抓新卡 → 校验 → active → 快照后处理（data_version 递增、附赠能量跨系列补齐）；CLI `monitor l0 [--dry-run]`；真实库 dry-run 零增量。详见 `tasks/done/013`。
- **2026-08-01**：**task 014 完成（M3-2 ✅）**。L1 赛制监控：官网三页正文提取 + hash 比对（基线建立、二轮零假阳性）；变更提案 = SnapshotSeed 超集，被 `legal-apply` 直接消费；不确定项 needs_manual 不猜测。PRD v1.4 续：实测订正"特别的卡牌"页为特殊机制说明页。详见 `tasks/done/014`。
- **2026-08-01**：**task 015 完成（M3-3 ✅）→ M3（Phase 1c）完成**。通知与闭环：桌面/webhook 通知、提案 applied 回写闭环（`monitor proposals`）、L2 勘误导入（`legal-errata`，effective_text 联测）。150 测试全绿。详见 `tasks/done/015`。
- **2026-08-01**：**task 016 完成（M4-1 ✅）**。验收基建：A1 白名单分赛制逐卡核对器（standard 55/55、open 61/61 全过）+ 一键验收 runner（A1/A4/A5/A6/A7/A8）+ CLI `ptcgdb accept`；真实库证据报告 `reports/acceptance-20260801.md` 六项全 PASS（A6 脏合入/回滚实验只在副本库，真实库只读）。详见 `tasks/done/016`。
- **2026-08-01**：**task 017 完成（M4-2 ✅）**。A2/A3 抽样比对工具 + CLI `ptcgdb sample`：A2 随机 100 张 × 11 字段人工比对清单（seed 可复现）、A3 特殊卡 DB-vs-raw 自动校验真实库 **5,122 项次全过**（修正校验器两个错误假设：ACE SPEC 含特殊能量、化石宝可梦进化来源豁免）。发现 derive 跨系列进化解析缺口（记"已知技术债"，待立项）。165 测试全绿。详见 `tasks/done/017`。
- **2026-08-01**：**task 018 完成（M4-3 ✅）→ M4 完成，Phase 1 全部收官**。文档收尾：AGENTS.md 常用命令补全 + 当前状态/技术栈更新（Python 3.14）、README badge/亮点/Roadmap/CLI 示例同步、PRD 状态行更新、新建 CHANGELOG.md（四段式，v20260801.0 首批发布）、进展日志补齐 task 013~018。165 测试全绿、ruff 通过。详见 `tasks/done/018`。
- **2026-08-01**：**task 021 完成（PRD v1.5 ✅）**。外部调研（校验源 + 映射源）驱动修订：跨语言映射**取消繁中、新增日文原版**——链路 = mik raw 英文桥 → EN（TCGdex 交叉校验）→ TCGdex 同 ID 多语言共构取 JP（零爬虫），pokemon-card.com 仅作抽样权威核对；校验源矩阵更新：TCGdex zh-cn 已收录全部简中系列壳（set_id 一致）但卡级 0% → 系列级跨源对账落地（FR-1.2/FR-2.3 规则 6），卡级跨源仍待实装；mik.moe 赛事数据库列为 validate_deck 真实卡组源；`external_ids.system` 枚举改 `{mik_en, tcgdex, pokemon_card_jp}`；README/AGENTS/STATUS 同步，里程碑表补 M5~M7。详见 `tasks/done/021`。
- **2026-08-02**：**task 019 完成（M5 ✅，goal 驱动）**。derive 跨系列进化解析技术债清偿：`resolve_evolution` 加全库回退（系列内优先、无命中回退 db_cards 索引、链根跨库续走、本系列旧行排除）；真实库未解析 **401→5**——386 条跨系列全解析，另修正 10 条原误判"化石豁免"（化石道具卡 SVP 有收录，如 SSP-186 化石翼龙→SVP-015）；最终 5 条为化石道具库内无收录的合理豁免。31 系列重 ingest skipped=0，FR-2.3 六规则全过，A3 复跑（同 seed）5,122 项次全过、豁免 386→5。新增 3 单测，169 测试全绿、ruff 通过。收敛报告 `reports/task019-evolution-resolution-20260802.md`。详见 `tasks/done/019`。

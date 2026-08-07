# CHANGELOG

四段式：Added / Changed / Deprecated / Removed。
版本双轨（PRD §FR-7）：数据用日历版本 `vYYYYMMDD.N`，schema 用 SemVer（破坏性变更升 major 并提前一个版本在此预告）。

## [Unreleased]

### Added

- validate 三维度校验扩展（code review，2026-08-04）：regulation_mark 格式（单个大写字母）/ HP 范围 [10, 340]（仅宝可梦卡）/ evolves_from_id FK 有效性（含跨系列全库兜底）；SDK `search_cards` 增 `limit`/`offset` 分页参数（默认 limit=100，不传时行为不变）；CLI `legal`/`validate`/`deck-check`/`stats`/`query`/`export` 对不存在的数据库报友好错误并退出码 2
- 赛区旋转日历种子 `config/tournament_envs.yml`（task 028 设计段收尾，PRD v1.13 续 FR-9.1b）：EN 2025-04-11 G/H/I → 2026-04-10 H/I/J；JP 2025-01-24 G/H/I、过渡期 2025-12-19~2026-01-22 G~J、2026-01-23 H/I/J（均附官方公告 source_url）；CN 复用合法性快照种子不另维护；append-only，官方旋转公告核实后追加新段；`tournaments.env` 由赛事日期∩日历段推导（migration user_version 8 实现时落列）+ 卡组最大赛制标记交叉校验（不符告警不拒收）
- 任务文档 `tasks/031` 立项（TODO）：赛事数据刷新管线——mapping_status 随卡库重算钩子 + monitor tourneys 增量子命令 + EN 赛后约 7 天重抓 + tier 词表变更触发物化视图重建（task 028 设计段审查发现的持续更新缺口）
- EN/JP 赛事卡组调研与对齐窗口设计（task 028 设计段，PRD v1.13）：FR-9.1a 对齐与筛选口径——内容时代对齐（对齐窗口 = 国际 G/H/I 赛季 2025-04~2026-04-09 为成本先验，卡级映射 full 为最终判据）+ 质量筛选（官方系列赛 Regional/IC/Special/League Cup≥32 人 Master 组；名次 Top Cut/Cup Top 8；pairings 逐局全量保留；`basis=intl_aligned` 不与 CN 混同）；`docs/data-sources.md` 增 §7b TopDeck.gg（免费 API，rounds 逐桌含局分）/ §7c RK9.gg（对账源）/ §8b JP 卡组聚合站（PokecaBook/ポケカ飯/pokecardlab，JP 对齐二期候选）+ §2 pokemon.cn 无机读赛果确认 + §7 历史深度实测
- FR-8 卡组校验器 `validate_deck`（M7-2，task 026，PRD v1.12）：`ptcgdb/legal/deck.py` 纯函数核 `validate_deck`（组合 build_pool + check_counts；合法性层 banned/not_legal 互斥禁卡优先，按 card_id 逐卡报告附 copies 数）；`DeckReport` frozen schema；SDK `validate_deck(deck, date, format)` 双后端同一契约（无覆盖快照抛 LookupError）；CLI `ptcgdb deck-check --file deck.yml [--date] [--format]`（ok 退出 0 / 有违规 1 / 输入错误 2）；卡表 YAML 输入格式（cards = card_id → 数量映射）
- A2 比对三件技术债修复（task 030，PRD v1.11）：migration 007（user_version=7）——`sets.card_face_total`（卡面分母种子，F-01）+ `cards.alias_of`（mik 双重列示别名，F-02）；种子文件 `config/set_card_face_totals.yml`（实测 5 例 > TCGdex zh-cn 壳 official[sanity 门] > CBB 按包，41 套 total 型 + 1 套 packs 型播种，6 项冲突未播种如实入报告）；CLI `seed-face-totals` / `mark-aliases` / `map-tera`；`ptcgdb/mapping/tera.py`（ptcd EN 卡 subtypes 'Tera' 印刷级识别，is_tera 166 张，确诊 3 例全中、猛雷鼓ex 不误判）+ `ptcgdb/normalize/face_totals.py` / `aliases.py`；报告 `reports/mapping-tera-20260803.md`
- 赛事卡组管线 CN mik 全链路（M9-1，task 027）：mik 赛事四端点采集器（series-list → list → rank-individual top64 → deck/detail，限速 2s、断点续传、进行中赛事 MikMoeNotReadyError 优雅跳过）+ `scrape tourneys` / `ingest-tourneys` CLI；赛事四表 tournaments / decks（卡组内容实体）/ deck_appearances（出战条目，deck_id+tournament_id+rank 复合主键）/ deck_cards（migration 004/005，user_version=5）；真实采集 3 批 1,327 raw 文件 → 26 赛 / 1,252 卡组内容 / 1,396 出战 / 38,105 卡表行（blocked=0 / unknown=0）；stat_scope 六组合派生；tier/division 开放词表 `config/vocabularies/tournament_tiers.yml`
- 对账工具 `tools/reconcile_variant_share.py`：deck-static 全量口径 vs top64 口径 + variantIcon 最长前缀 rollup 粒度归并（full-coverage 2/2 精确一致）；验收报告 `reports/task027-ingest-20260802.md`
- 统计可复算性与查询层（M9-2，task 029）：migration 006 物化视图 `v_stat_deck_cards` / `v_tournament_weights`（user_version=6）；`ptcgdb/stats/` 新包——canonical SQL 五文件（wur / winrate_a / winrate_b / wws / card_drilldown，公式单一事实源）+ 引擎（layer A/B/auto，meta 回显 as_of/窗口/口径/词表 hash）+ `caliber.py` 口径 hash + `jsonldb.py` JSONL 内存复算；CLI `stats usage/winrate/wws/card` 子命令组（裸调用兼容旧对账）+ `query` 只读 SQL（mode=ro，拒非 SELECT 与 ATTACH，默认 LIMIT 500）；SDK `stats_usage/stats_winrate/stats_wws/stats_card` 双后端 + `CardStat`/`StatsResult`/`DrilldownResult` frozen schema；导出追加 tournaments / decks / deck_appearances / deck_cards 四 JSONL（七件套 → 十二件套，deck_cards 附 group_key/stat_scope 冗余列）+ manifest.caliber + schema.md canonical SQL 附录；黄金数据集三指标容差 1e-9 对平
- 赛事卡组数据源调研与设计（M9 设计段，task 027）：mik.moe 赛事 API 端点文档化（`docs/data-sources.md` §1 赛事 API）；EN Limitless TCG / JP players.pokemon-card.com 源评估入档（§7/§8）；PRD §7.5 tournaments/decks/deck_cards 三表设计
- FR-3.4 同名计数引擎（M7-1，task 025）：`ptcgdb/legal/deck.py` 纯函数核 `check_counts`（deck_size / 同名组双层上限 / ACE SPEC 与光辉全卡组 ≤1 / V-UNION 部件各 1 / 基本能量豁免）；`Violation` frozen schema（kind 全集含 additive 新增 `unknown_card` / `radiant_limit`）
- 跨语言映射（M6，task 022~024）：`name_en` 填充 12,337/12,420（99.3% = raw 英文桥上限）+ `external_ids(system='mik_en')`；EN 桥 → TCGdex card ID 解析 12,322（99.88%）+ 系列级跨源对账；`name_ja` 名字级映射 9,480（76.8%，dexId 链 + 开放词表）+ `external_ids(system='tcgdex')` 12,331；pokemon-card.com 官方抽样核对 31 张一致率 100%
- 跨语言词表：`config/vocabularies/ja_name_rules.yml`（前后缀/后缀修饰/归属/能量/TAG TEAM 连接符）、`config/tcgdex_set_map_overrides.yml`（套映射覆盖）
- CLI：`map-en` / `map-tcgdex` / `map-ja [--fetch]`（`ptcgdb/mapping/` 新包）
- derive 跨系列进化解析（M5，task 019）：`resolve_evolution` 全库回退（系列内优先/链根跨库续走），未解析 401→5
- 数据源文档 `docs/data-sources.md`：全部数据源获取方式汇总（由 mikmoe-api.md 扩编重命名）

### Changed

- **code review 全量修复（2026-08-04，提交 f608478）**：28 项 HIGH 清零——P0 数据安全：导出 WAL checkpoint 验证 + 导出前 integrity_check / foreign_key_check（失败拒绝导出）；normalize `_to_int`/`_to_float` 非数值输入返回 None 不再抛异常；L0 `expected_count` 更新移至 activate 成功后（修复 validate 失败导致增量信号丢失/draft 卡孤立）；增量采集 cardsNum 与缓存条目数对账不符自动重抓；`seed_snapshots` 对已冻结快照拒绝覆盖（FrozenSnapshotError）；◇ 计数改跨 name_group 全局检查（修复同名组内检查漏判不同名 ◇ 组合）；deck_cards 可空 PK 按 (deck_id, raw_name) 去重防唯一约束冲突。P1 运行时：mapping 四文件 `engine.dispose()` 移入 finally（commit 失败不再泄露连接）；赛事 schema `fetched_at` 改 Optional；macOS osascript / Windows pwsh 通知内容转义（防注入与 KeyError）；JSONL 后端 v_stat_deck_cards 视图对齐迁移 006（补 cards_name_group JOIN）；MEDIUM 批量：is_qual/is_team default=False、除零守卫、YAML 静默吞错改告警、accept 冻结守卫 old_id 空指针 + V-UNION 计数虚高修复等。测试 327→416 全绿，ruff 全净
- **赛事卡组范围收口（2026-08-04 拍板，PRD v1.13 续 FR-9.1b）**：收集与维护以当前简中比赛环境（standard 2026-07-16 起 G/H/I）为起点，历史赛事不回填、历史日历段不补录；task 026 遗留「历史环境快照补录（988 条出战）」按拍板关闭，维持 no_snapshot 如实分档；EN 对齐窗口（2025-04~2026-04-09）属当前环境参照数据保留采集，随简中环境演进滚动前移
- PRD 升 v1.13（task 028 设计段）：FR-9.1a 新增（见 Added）+ FR-9.1 EN 备选源 TopDeck.gg / JP 对齐候选 PokecaBook 入档 + M9-3 描述改「对齐窗口接入」；任务文档 `tasks/028` 立项（TODO，待拍板实现）
- PRD 升 v1.12（task 026）：FR-8 `validate_deck` 实装（见 Added）+ 卡表 YAML 输入格式 + DeckReport.date 类型定死为 date（与 LegalityPool 一致，原示意注记 str 作废）；`legal/engine.py` 禁卡判定 `_is_banned` 改公开 `is_banned`（build_pool 与 validate_deck 共用，语义不变）
- **number_display 分母口径变更（F-01，破坏性语义修正）**：分母由 mik cardsNum（≠卡面分母，A2 实测翻案）改为种子口径 `sets.card_face_total`；种子未覆盖系列**只显示分子不带分母**；CBB* 宝石包按包分母（PPNN/包内卡数）。分子（cardIndex 逐字）始终不变，主键与映射不受影响
- **is_tera 派生口径变更（F-03）**：v1.4⑤「简中暂无太晶卡样本」结论推翻——mik 源无太晶信号（判据永假），改走 mapping 层 ptcd EN 卡 subtypes 富化（`map-tera`）；rule_box_type 维持 ex 不变；text_raw 口径订正为**不含规则框文本**（mik 源不提供）
- 16 张字母编号基本能量条目标记 `alias_of` → 数字编号正本（F-02：CS4DaC/CSVL1C 各 8，raw 逐字段全等的 mik 双重列示；alias 行保留，12,420 总数与主键口径不变）；CSVH5C `NaN1` 等无数字孪生条目如实保留入 questions
- ingest 重入库保留富化字段（is_tera/alias_of/name_ja/card_face_total，task 013 status 保留同款）；修复重入库跨系列反向关系（evolves_to 回指行）两处缺陷——按方向精确删除（他系列自建 evolves_from 前向行不动）+ 他系列指向本系列的 evolves_to 反向行补写（修复前重入库结果与系列顺序相关，实测丢行 151 条）
- PRD 升 v1.11（task 030）：§7.1 card_face_total + §7.2 number_display/alias_of/is_tera/text_raw 口径 + 修订记录；任务文档 `tasks/030`
- PRD 升 v1.10 续（task 027 真实数据订正）：真实采集实证 deckId = 卡组**内容实体**（多名选手/多场赛事共用、同赛事可多个名次）→ §7.5 拆表 decks（内容：variant/deck_code/mapping_status）/ deck_appearances（出战：rank/points/player_ref/record 三列）；mik `type` 实测词表（Great=super / City=city / Ultra=advanced）；id 参数必须 int 形态
- PRD 升 v1.10（task 029 设计）：FR-9.6 可复算性契约 + FR-9.7 统计与查询接口（见 Added）；§7.5 修订（tournaments 加 topcut_slots/tier_coef、decks 加 record 三列、主键 {source}:{源侧id} 口径）；FR-7 导出追加赛事三件套；FR-8 SDK 追加 stats_*；M9 拆分 M9-1/2/3
- PRD 升 v1.9（task 027 统计指标定稿）：FR-9.4 展开为三指标体系——①加权出场率 WUR（卡组名次权重 w̃_d × 赛事权重 W_t[tier 系数 × log₁₀参赛人数 × 半衰期 90 天时间衰减]，统计单元=name_group × 滚动赛季窗）；②胜率 WR 分层（A 层 Limitless 真实胜率含镜像对局剔除；B 层 mik 无逐局数据时用 top-cut 转化率代理并与 deck-static 端点对账）；③加权胜率 WWS = WUR × 贝叶斯收缩胜率（A 层 k=20 等效局/B 层 k=10 等效卡组、收缩基准 q0=赛事基准转化率而非 0.5）；每指标附样本量 + 口径标签 + low_confidence 低样本标记
- PRD 升 v1.8（task 027 设计）：新增 FR-9 赛事卡组与统计基建（范围限定=可映射简中环境的卡组；统计范围=宝可梦/支援者/竞技场，能量/物品/道具不进统计；胜率=名次加权使用率/top-cut 转化率代理指标）+ §7.5 三表 + 数据源矩阵加 Limitless/players + 里程碑 M9
- PRD 升 v1.7（task 025）：FR-3.4 形式化计数语义（含基本能量豁免）+ FR-8 Violation 语义全集（evolution_chain 定死为预留类型）+ DeckReport 字段定稿
- PRD 升 v1.6：§2.4 跨语言映射由「TCGdex 同 ID 共构取 JP」（前提证伪）改为「名字级 dexId 链」
- 官方小程序验证信息收敛为结论性说明（接口细节不公开），测试记录显式 gitignore
- ruff 排除 `.scratch/`；`.scratch/pcc-*` 逆向中间产物入 gitignore

### Deprecated

### Removed

## [v20260801.0] - 2026-08-01 · schema 1.0.0

首批发布（Phase 1 全部完成，M4 验收 A1~A8 全过）。

### Added

- 首批全量入库：129 系列 / 12,420 张去重卡 active（D1 主源 tcg.mik.moe，FR-2.3 六规则校验全过）
- 双赛制环境快照种子：standard（G/H/I + 8 能量 + 44 白名单）/ open（A~I + 9 能量 + 32 白名单 + 3 禁卡 + 视作覆盖），官方赛制页 2026-07-16 版（`config/legality/`）
- 合法性引擎 `legal_at` / `effective_text`（勘误 > 最新印刷 > 原文）、快照版本化/冻结/回滚（`legal-apply` / `rollback`）
- 导出七件套（manifest / cards / sets / relations.jsonl / legality.json / 只读 SQLite / checksums，双轨版本化）与 SDK 双后端（`open_db` / `open_jsonl` 同一接口）
- 监控管线：L0 新卡增量（探测→抓取→校验→active→快照后处理）、L1 赛制页监控（hash 比对 → 变更提案 → `legal-apply` 闭环）、L2 勘误导入（`legal-errata`）
- 验收基建：A1 白名单分赛制逐卡核对器、一键验收 runner（A1/A4/A5/A6/A7/A8，`ptcgdb accept`）、A2/A3 抽样比对工具（`ptcgdb sample`）；证据报告 `reports/acceptance-20260801.md` 六项全 PASS

### Changed

### Deprecated

### Removed

---

数据版本说明：当前库 meta 尚无 data_version（L0 零增量、从未实际合入），export manifest 显示 fallback `v20260801.0`；自 L0 首次实际合入增量起按日历版本递增。

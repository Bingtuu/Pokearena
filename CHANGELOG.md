# CHANGELOG

四段式：Added / Changed / Deprecated / Removed。
版本双轨（PRD §FR-7）：数据用日历版本 `vYYYYMMDD.N`，schema 用 SemVer（破坏性变更升 major 并提前一个版本在此预告）。

## [Unreleased]

### Added

- 赛事卡组数据源调研与设计（M9 设计段，task 027）：mik.moe 赛事 API 端点文档化（`docs/data-sources.md` §1 赛事 API）；EN Limitless TCG / JP players.pokemon-card.com 源评估入档（§7/§8）；PRD §7.5 tournaments/decks/deck_cards 三表设计
- FR-3.4 同名计数引擎（M7-1，task 025）：`ptcgdb/legal/deck.py` 纯函数核 `check_counts`（deck_size / 同名组双层上限 / ACE SPEC 与光辉全卡组 ≤1 / V-UNION 部件各 1 / 基本能量豁免）；`Violation` frozen schema（kind 全集含 additive 新增 `unknown_card` / `radiant_limit`）
- 跨语言映射（M6，task 022~024）：`name_en` 填充 12,337/12,420（99.3% = raw 英文桥上限）+ `external_ids(system='mik_en')`；EN 桥 → TCGdex card ID 解析 12,322（99.88%）+ 系列级跨源对账；`name_ja` 名字级映射 9,480（76.8%，dexId 链 + 开放词表）+ `external_ids(system='tcgdex')` 12,331；pokemon-card.com 官方抽样核对 31 张一致率 100%
- 跨语言词表：`config/vocabularies/ja_name_rules.yml`（前后缀/后缀修饰/归属/能量/TAG TEAM 连接符）、`config/tcgdex_set_map_overrides.yml`（套映射覆盖）
- CLI：`map-en` / `map-tcgdex` / `map-ja [--fetch]`（`ptcgdb/mapping/` 新包）
- derive 跨系列进化解析（M5，task 019）：`resolve_evolution` 全库回退（系列内优先/链根跨库续走），未解析 401→5
- 数据源文档 `docs/data-sources.md`：全部数据源获取方式汇总（由 mikmoe-api.md 扩编重命名）

### Changed

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

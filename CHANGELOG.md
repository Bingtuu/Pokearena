# CHANGELOG

四段式：Added / Changed / Deprecated / Removed。
版本双轨（PRD §FR-7）：数据用日历版本 `vYYYYMMDD.N`，schema 用 SemVer（破坏性变更升 major 并提前一个版本在此预告）。

## [Unreleased]

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

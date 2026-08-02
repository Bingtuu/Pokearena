# AGENTS.md — ptcg-cn-db

简中 PTCG 标准环境卡牌数据库。本地 SQLite 卡牌库 + 数据管线 + 更新机制，为下游（规则引擎 / AI 对战模拟 / 胜率统计）提供数据基建。

**权威文档**：`docs/简中PTCG卡牌数据库_PRD与技术方案.md`（v1.10）——一切设计以它为准。
**进展记录**：`STATUS.md`——当前阶段、里程碑、决策日志，开始工作前先读。
**数据源**：`docs/data-sources.md`——全部数据源的获取方式与端点约定（mik.moe 主源 / 官网赛制页 / TCGdex / ptcd / PokéAPI / pokemon-card.com 抽样核对）。

## 当前状态

Phase 1 全部完成（2026-08-01，M4 验收 A1~A8 全过）：1a 首批入库 129 系列 / 12,420 张；1b 合法性引擎 + 导出七件套 + SDK 双后端；1c L0/L1 监控管线。D1 = 路线 B（tcg.mik.moe 主源，PRD 第 14 章）。Phase 2 进行中：M5 进化解析（task 019）、M6 跨语言映射 EN+JP（task 022~024，name_en 12,337 / name_ja 9,480）、M7-1 同名计数引擎（task 025，PRD v1.7）已完成；下一步 task 026 validate_deck SDK + M7 验收。
代码结构已按 PRD 第 8 章落地：`ptcgdb/`（orm/schemas/migrations/scrapers/normalize/validate/legal/monitor/export/sdk/accept/mapping），不要自行发明布局。

## 技术栈与约束

- Python 3.14（开发环境 3.14.6，`requires-python >= 3.12`）；Pydantic v2（校验层 + SDK 返回模型，frozen）；SQLAlchemy 2（持久层，**不用 SQLModel**）；Typer（CLI）；httpx + tenacity；pytest；ruff。
- schema 迁移 = `PRAGMA user_version` + `migrations/` 顺序 SQL 脚本（不用 Alembic）。
- 无外部服务依赖，全本地运行。

## 硬性规矩（来自 PRD，改动前必须确认有充分理由）

- `text_raw` 逐字保留，**绝不做术语规范化**；原文与派生字段分层。
- 合法性不落布尔值：赛制标记 + 快照动态判定；旧快照永不删除，历史快照 override 冻结。
- raw 层 append-only，清洗逻辑可整体重跑。
- 枚举一律开放字符串 + 词表文件（`config/vocabularies/`），不写死。
- 导出契约与 SDK 返回模型**字段只加不删**；破坏性变更升 schema major 并提前一个版本在 CHANGELOG 预告。
- 采集只读、限速 ≥1s/请求；不采集/存储/分发卡图；数据库不公开分发。
- pokemon-card.com 只用于小样本抽样核对（≤35 请求、≥2s/请求，站方 WAF 严格），绝不做批量采集。
- 官方小程序接口细节（端点/参数/加密形态）不写入任何入库文档；测试记录仅存本机 `data/raw/capture/`（gitignore）。
- 卡牌主库对下游只读；模拟结果永远落独立库。

## 常用命令

```bash
# 测试与检查（Windows Git Bash）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -X utf8 -m pytest -q
.venv/Scripts/ruff.exe check .

# 数据管线（.venv/Scripts/ptcgdb.exe）
ptcgdb init-db                                  # 建库/迁移
ptcgdb scrape sets | scrape cards [--set X]     # 采集 mik.moe → raw（限速 2s/请求）
ptcgdb ingest --set <setId>                     # raw → draft 入库
ptcgdb validate [--set X] / activate            # FR-2.3 六规则校验 → active
ptcgdb legal --date 2026-08-01 --format standard  # 指定日期的合法卡池
ptcgdb legal-seed                               # 快照种子入库（config/legality/）
ptcgdb legal-apply --proposal p.yml             # 应用赛制变更提案
ptcgdb legal-errata / rollback                  # L2 勘误导入 / 回滚
ptcgdb export --out dist/                       # 导出七件套
ptcgdb monitor l0 [--dry-run]                   # L0 新卡增量管线
ptcgdb monitor l1 [--baseline] / proposals      # L1 赛制监控 / 提案列表
ptcgdb accept                                   # 一键验收 A1/A4/A5/A6/A7/A8
ptcgdb sample [--a2 | --a3] [--seed N]          # A2/A3 抽样比对清单
ptcgdb map-en / map-tcgdex / map-ja [--fetch]   # 跨语言映射：EN 桥 / TCGdex ID / JP 名
```

## 工作方式

- **任务循环**：开发按 `tasks/` 目录的标准循环执行——先写任务文档再写代码，完工归档 `tasks/done/` 并同步 `STATUS.md`（不进 README.md）。规范见 `tasks/README.md`。
- 变更数据模型、合法性语义、导出契约前，先改 PRD 并保持代码与 PRD 同步。
- CHANGELOG.md 四段式：Added / Changed / Deprecated / Removed。
- 任务提交信息前缀 `task(NNN):`。

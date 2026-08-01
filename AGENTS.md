# AGENTS.md — ptcg-cn-db

简中 PTCG 标准环境卡牌数据库。本地 SQLite 卡牌库 + 数据管线 + 更新机制，为下游（规则引擎 / AI 对战模拟 / 胜率统计）提供数据基建。

**权威文档**：`docs/简中PTCG卡牌数据库_PRD与技术方案.md`（v1.3）——一切设计以它为准。
**进展记录**：`STATUS.md`——当前阶段、里程碑、决策日志，开始工作前先读。

## 当前状态

项目尚未开工（Phase 0）。待决策项 D1（主数据源路线，见 PRD 第 14 章）确认后进入 M0。
代码结构按 PRD 第 8 章目录结构创建，不要自行发明布局。

## 技术栈与约束

- Python 3.12；Pydantic v2（校验层 + SDK 返回模型，frozen）；SQLAlchemy 2（持久层，**不用 SQLModel**）；Typer（CLI）；httpx + tenacity；pytest；ruff。
- schema 迁移 = `PRAGMA user_version` + `migrations/` 顺序 SQL 脚本（不用 Alembic）。
- 无外部服务依赖，全本地运行。

## 硬性规矩（来自 PRD，改动前必须确认有充分理由）

- `text_raw` 逐字保留，**绝不做术语规范化**；原文与派生字段分层。
- 合法性不落布尔值：赛制标记 + 快照动态判定；旧快照永不删除，历史快照 override 冻结。
- raw 层 append-only，清洗逻辑可整体重跑。
- 枚举一律开放字符串 + 词表文件（`config/vocabularies/`），不写死。
- 导出契约与 SDK 返回模型**字段只加不删**；破坏性变更升 schema major 并提前一个版本在 CHANGELOG 预告。
- 采集只读、限速 ≥1s/请求；不采集/存储/分发卡图；数据库不公开分发。
- 卡牌主库对下游只读；模拟结果永远落独立库。

## 常用命令

```bash
# 待代码落地后补充：pytest / ruff / ptcgdb CLI
```

## 工作方式

- **任务循环**：开发按 `tasks/` 目录的标准循环执行——先写任务文档再写代码，完工归档 `tasks/done/` 并同步 `STATUS.md`（不进 README.md）。规范见 `tasks/README.md`。
- 变更数据模型、合法性语义、导出契约前，先改 PRD 并保持代码与 PRD 同步。
- CHANGELOG.md 四段式：Added / Changed / Deprecated / Removed。
- 任务提交信息前缀 `task(NNN):`。

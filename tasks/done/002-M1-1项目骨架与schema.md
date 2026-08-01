# 002 · M1-1 项目骨架 + 数据模型 schema + 迁移脚本

| 项 | 内容 |
|---|---|
| 状态 | DONE |
| 关联 | PRD §7 数据模型、§8 架构与目录结构、里程碑 M1（Phase 1a）、AGENTS.md 技术栈红线 |
| 预估 | 1 天 |

## 目标

按 PRD 第 7/8 章建立可运行、可测试的项目骨架：Python 包结构、ORM 全表 schema、`PRAGMA user_version` 迁移机制、核心 Pydantic 模型、初始词表、冒烟测试。**不做采集逻辑**（那是 task 003）。

## 环境约束（本任务的新决策）

- 本机仅有 Python 3.11.9，PRD 写 3.12。暂行：`requires-python = ">=3.11"`，安装 3.12 后再收紧（记入完成总结与 STATUS 决策日志）。

## 步骤

- [x] `pyproject.toml`（依赖：pydantic v2 / sqlalchemy 2 / typer / httpx / tenacity / pyyaml；dev：pytest / ruff）
- [x] 项目根 `.venv` + `pip install -e .[dev]`
- [x] `ptcgdb/` 包骨架：orm/ schemas/ scrapers/ normalize/ validate/ legal/ monitor/ export/ sdk/ migrations/ + cli.py（按 PRD §8 目录结构）
- [x] `orm/` SQLAlchemy 2 表定义：sets / cards / card_relations / name_groups / cards_name_group / legality_snapshots / errata / rules_documents / scrape_runs / external_ids / meta（字段严格按 PRD §7，含全部索引）
- [x] `migrations/`：001_init.sql + 迁移执行器（PRAGMA user_version 顺序执行、幂等）
- [x] `schemas/` 核心 frozen Pydantic 模型（Card / Set / LegalitySnapshot 等，SDK 返回类型基础）
- [x] `config/vocabularies/` 初始词表：energy_types / rarities / rule_box_types / owners（按 PRD 调研结论预填）
- [x] `cli.py`：typer 骨架，`ptcgdb init-db`（执行迁移建库到 `data/ptcg-cn.db`）
- [x] `tests/`：冒烟测试（建库→插入系列+卡→读回）、迁移幂等测试

## 验收标准

- [x] `pytest` 全绿（2 passed）
- [x] `ptcgdb init-db` 生成 `data/ptcg-cn.db`，`PRAGMA user_version = 1`，11 表 + 9 索引存在；重复执行无副作用（上级复核确认）
- [x] `ruff check` 通过（上级复核确认）
- [x] schema 与 PRD §7 逐字段一致，v1.3 新增字段全部覆盖（cards 39 列，上级用 PRAGMA 逐项核对无缺失）

## 完成总结

**做了什么**：pyproject.toml + `.venv`（pip install -e .[dev]）；ptcgdb 包骨架（8 个子包 + cli.py）；SQLAlchemy 2 全 11 表 ORM（Mapped/mapped_column 现代写法，JSON 列用 SA JSON 类型）；migrations/001_init.sql（由 ORM metadata 生成，CreateTable/CreateIndex + if_not_exists，与 ORM 零漂移）+ PRAGMA user_version 幂等迁移执行器；frozen Pydantic 核心模型（Card/Set/LegalitySnapshot/Attack 等，可直接 `model_validate(from_attributes=True)`）；4 个初始词表 yml；`ptcgdb init-db` 命令；冒烟 + 迁移幂等测试。实现由 coder 子代理完成，上级逐条复核验收全过。

**与预估的偏差**：无（半天内完成）。

**决策与偏差记录**：
1. Python 3.11 暂行（`requires-python = ">=3.11"`），安装 3.12 后收紧——已记 STATUS 决策日志；
2. PRD 自身不一致处照原文保留：`sets.fetched_at` TEXT vs `cards.fetched_at` DATETIME，未擅自统一（后续如需统一走 schema minor 演进）；
3. `cards_name_group` 复合主键 `(card_id, group_key)` 为合理补全（PRD 未写明）。

**遗留问题**：词表 energy_types.yml 中龙/无的 mik.moe 单字母码为 null 占位，待 task 003 采集多样本后核证；scrapers/normalize 等子包为空壳，task 003 填充。

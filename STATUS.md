# STATUS.md — 开发进展

> 每次工作会话开始时先读本文件；完成阶段性工作后更新。
> 最近更新：2026-08-01

## 当前状态

**阶段：M1（Phase 1a）进行中** —— task 002 完成（项目骨架 + schema + 迁移可用），下一步 **task 003（mik.moe 采集器 + raw 层）**。主源接口文档见 `docs/mikmoe-api.md`。

## 入口

| 内容 | 位置 |
|---|---|
| 产品需求与技术方案（权威设计） | `docs/简中PTCG卡牌数据库_PRD与技术方案.md`（v1.3） |
| 工程约定 | `AGENTS.md` |
| 任务队列（开发标准循环） | `tasks/`（规范见 `tasks/README.md`，归档在 `tasks/done/`） |
| **主源接口文档** | `docs/mikmoe-api.md`（task 001 产物，M1 采集层必读） |
| 代码 | `ptcgdb/`（骨架已建：orm/schemas/migrations/cli，其余子包空壳） |
| 数据 | `data/ptcg-cn.db`（schema 已建，user_version=1）、`data/raw/capture/`（本地样例） |

## 里程碑（PRD 第 11 章）

- [x] **M0** D1 决策 + 主源接口可行性验证（1 天）—— **2026-08-01 完成（task 001），D1 = 路线 B**
- [ ] **M1 (Phase 1a)** schema + raw 层 + 首批全量入库 + 校验报告（3~4 天；**走镜像路线，按 PRD 预算 +1~2 天 → 4~6 天**）
- [ ] **M2 (Phase 1b)** 环境快照 + 合法性引擎 + 版本化/回滚 + 导出七件套 + SDK 基础（3~4 天）
- [ ] **M3 (Phase 1c)** L0/L1 监控管线 + 提案生成 + 通知（2 天）
- [ ] **M4** 验收 A1~A8 + 文档收尾（1 天）

## 决策日志

| 日期 | 决策 | 状态 |
|---|---|---|
| 2026-08-01 | 数据形态为纯文本/结构化数据，不采集卡图 | ✅ 已定 |
| 2026-08-01 | 数据存储于项目内 `data/`（原 D2） | ✅ 已定 |
| 2026-08-01 | SQLAlchemy 2 替代 SQLModel；PRAGMA user_version 替代 Alembic | ✅ 已定（v1.3） |
| 2026-08-01 | **Python 3.11 暂行**（本机无 3.12，`requires-python = ">=3.11"`），安装 3.12 后收紧回 PRD 口径（task 002） | ✅ 已定（暂行） |
| 2026-08-01 | **D1 = 路线 B：tcg.mik.moe 为主源**。理由：小程序接口有 JWT 登录态 + 请求/响应 AES 加密 + 签名四层防护（还原需反编译 wxapkg，超 M0 标准）；mik.moe `/api/v3/card/*` 无鉴权明文 JSON、字段完整且有意外收获（effectId 归组、regulationLegal 交叉校验、英文映射）。详见 `docs/mikmoe-api.md` 与 `tasks/done/001` | ✅ 已定 |

## 已知临近事件

- **2026-09-16**：补充包"30周年庆典"全球同步发售（新罕贵度 FUR、可能引入超级进化/GX 复刻机制）——发售前需预扩词表（PRD 9.4）。
- TCGdex 已把 zh-cn 列入路线图，持续跟踪（PRD 风险登记册）。

## 进展日志

- **2026-08-01**：PRD 迭代至 v1.3（评审修订 + 外部调研：简中赛制核查、开源对标、数据基建接口设计）；建立 AGENTS.md / STATUS.md；确立 tasks/ 任务工作循环（`tasks/README.md`）。
- **2026-08-01**：**task 001 完成（M0 ✅）**。mitmproxy 抓包官方小程序 → 判定路线 A 不可行（JWT+加密+签名四层防护）→ 验证 tcg.mik.moe `/api/v3/card/*` JSON API 完全可行 → **D1 = 路线 B（mik.moe 主源）**。产物：`docs/mikmoe-api.md`、`tools/capture/`（可复用抓包环境）、API 样例。M1 预算调整为 4~6 天。
- **2026-08-01**：**task 002 完成（M1-1 ✅）**。项目骨架落地：pyproject + `.venv`、`ptcgdb/` 包（11 表 ORM 与 PRD §7 逐字段一致、PRAGMA user_version 幂等迁移、frozen Pydantic 核心模型、4 个初始词表、`ptcgdb init-db`）；pytest 2 绿、ruff 通过。新决策：Python 3.11 暂行。下一步 task 003：mik.moe 采集器 + raw 层。

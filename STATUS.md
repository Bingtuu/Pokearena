# STATUS.md — 开发进展

> 每次工作会话开始时先读本文件；完成阶段性工作后更新。
> 最近更新：2026-08-01

## 当前状态

**阶段：M1（Phase 1a）进行中（goal 驱动）** —— task 003 完成（采集器 + raw 层，CSM1aC 211 张实测通过）。正在进行 **task 004（normalize + 入库管线）**。主源接口文档见 `docs/mikmoe-api.md`。

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
| 2026-08-01 | **Python 环境定为 3.14.6**（用户安装；`.venv` 已用 3.14 重建，deps/pytest/ruff/init-db 全验证通过）。`requires-python = ">=3.12"` 收回 PRD 口径。原 3.11 暂行决策作废（task 002 后记） | ✅ 已定 |
| 2026-08-01 | **D1 = 路线 B：tcg.mik.moe 为主源**。理由：小程序接口有 JWT 登录态 + 请求/响应 AES 加密 + 签名四层防护（还原需反编译 wxapkg，超 M0 标准）；mik.moe `/api/v3/card/*` 无鉴权明文 JSON、字段完整且有意外收获（effectId 归组、regulationLegal 交叉校验、英文映射）。详见 `docs/mikmoe-api.md` 与 `tasks/done/001` | ✅ 已定 |

## 已知临近事件

- **2026-09-16**：补充包"30周年庆典"全球同步发售（新罕贵度 FUR、可能引入超级进化/GX 复刻机制）——发售前需预扩词表（PRD 9.4）。
- TCGdex 已把 zh-cn 列入路线图，持续跟踪（PRD 风险登记册）。

## 进展日志

- **2026-08-01**：PRD 迭代至 v1.3（评审修订 + 外部调研：简中赛制核查、开源对标、数据基建接口设计）；建立 AGENTS.md / STATUS.md；确立 tasks/ 任务工作循环（`tasks/README.md`）。
- **2026-08-01**：**task 001 完成（M0 ✅）**。mitmproxy 抓包官方小程序 → 判定路线 A 不可行（JWT+加密+签名四层防护）→ 验证 tcg.mik.moe `/api/v3/card/*` JSON API 完全可行 → **D1 = 路线 B（mik.moe 主源）**。产物：`docs/mikmoe-api.md`、`tools/capture/`（可复用抓包环境）、API 样例。M1 预算调整为 4~6 天。
- **2026-08-01**：**task 002 完成（M1-1 ✅）**。项目骨架落地：pyproject + `.venv`、`ptcgdb/` 包（11 表 ORM 与 PRD §7 逐字段一致、PRAGMA user_version 幂等迁移、frozen Pydantic 核心模型、4 个初始词表、`ptcgdb init-db`）；pytest 2 绿、ruff 通过。下一步 task 003：mik.moe 采集器 + raw 层。
- **2026-08-01**：Python 环境收口 3.14.6（`requires-python >=3.12` 收回 PRD 口径）。**启动 goal：完成 M1**（采集→入库→校验报告，限速红线 2s/请求+熔断，按任务循环自动 commit+push）。
- **2026-08-01**：**task 003 完成（M1-2 ✅）**。采集层全链路：限速 HTTP 层（2s/请求、退避、三路熔断）、mik.moe 三端点、append-only raw 层（sha256 manifest）、card 级断点续传、三清单+scrape_runs 落库、CLI `scrape sets/cards`。CSM1aC 211 张实测 7 分钟跑通，resume 重跑零请求；16 测试全绿（零网络）。发现并修复 product-list data 包装层偏差（文档已同步）。下一步 task 004：normalize + 入库管线。

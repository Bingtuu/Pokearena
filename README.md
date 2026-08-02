<div align="center">

# 🃏 ptcg-cn-db

**简体中文 PTCG 标准环境卡牌数据库 —— 为 AI 对战模拟而生的数据基建**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Phase2进行中·M6跨语言映射完成-brightgreen.svg?style=flat-square)](STATUS.md)
[![PRD](https://img.shields.io/badge/PRD-v1.6-blue.svg?style=flat-square)](docs/简中PTCG卡牌数据库_PRD与技术方案.md)

[产品需求文档](docs/简中PTCG卡牌数据库_PRD与技术方案.md) · [开发进展](STATUS.md) · [工程约定](AGENTS.md)

</div>

---

## 为什么要有这个项目

简中 PTCG 是一个**独立产品池**——套装结构、编号体系、赛制节奏都与国际版不同，任何国际版数据库（pokemon-tcg-data、TCGdex）都不含简中卡级数据（TCGdex 已收录简中系列壳，但卡级 0%）。官方数据锁在微信小程序里（接口带 JWT+AES+签名四层防护），开源世界也一直没有可用的简中卡数据集。好在 [Cryst's Cards Database（tcg.mik.moe）](https://tcg.mik.moe/) 提供了同源的公开 JSON API——本项目以此为**主数据源**，自建覆盖**简中标准赛制全部合法卡牌**的本地数据库与数据管线，作为「AI 模拟对战 + 卡组强度/胜率测试」工具链的第一块基石。

## ✨ 亮点

- **📸 快照化合法性引擎** —— 赛制标记 + 白名单 + 禁卡表 + 视作覆盖 + 能量种类全部按生效日版本化；旧快照永不删除，可回放任意历史环境（`legal_at('2026-01-01', 'standard')`）
- **🌏 三语卡名映射** —— 简中卡 99.3% 挂英文桥（12,337 张），经 TCGdex + pokemon-tcg-data + PokéAPI 链路填充日文名 9,480 张；每条映射带置信度分档，pokemon-card.com 官方抽样 31 张核对一致率 100%
- **🔌 规则语义一等公民的 SDK** —— `legal_at` / `effective_text` 不是让下游自己 join 表，而是开箱即用的纯函数（`validate_deck` 卡组校验规划在 Phase 2）；`open_db` / `open_jsonl` 双后端同一接口
- **📦 七件套导出契约** —— `manifest + cards/sets/relations.jsonl + legality.json + 只读 SQLite + checksums`，双轨版本化（日历版本管数据，SemVer 管 schema），对齐 MTGJSON/Scryfall 惯例
- **🔄 分级自动更新** —— L0 新卡每日增量入库、L1 赛制页变更自动生成提案、L2 勘误人工维护；新包发售 30 分钟内完成更新
- **🛡️ 原文保真** —— `text_raw` 逐字保留绝不规范化，原文与派生字段严格分层；DB vs raw 同源自验 + 三清单日志保证数据质量
- **🔮 机制全覆盖且前瞻** —— ex / 太晶 / ACE SPEC / 训练家宝可梦 / V-UNION / GX，词表开放，超级进化ex 等新机制直接进库

## 🚀 快速预览

> Phase 1（M1~M4）+ Phase 2 跨语言映射（M6）已完成：129 系列 / 12,420 张卡入库、三语卡名映射落地、验收 A1~A8 全过，以下接口均已可用（`validate_deck` 为 Phase 2 剩余目标接口）。

**CLI**

```bash
ptcgdb scrape sets && ptcgdb scrape cards      # 采集（mik.moe 主源，限速 2s/请求）
ptcgdb ingest --set CSV10C                     # 入库（raw → draft）
ptcgdb validate && ptcgdb activate             # FR-2.3 六规则校验 → active
ptcgdb legal --date 2026-08-01 --format standard   # 某日期的合法卡池（standard 5,320 / open 12,413）
ptcgdb legal-seed                              # 环境快照种子入库（config/legality/）
ptcgdb export --out dist/                      # 导出七件套
ptcgdb monitor l0 --dry-run                    # L0 新卡增量探测；monitor l1 赛制页监控 → 提案
ptcgdb accept && ptcgdb sample                 # 一键验收 A1~A8；A2/A3 抽样比对清单
ptcgdb map-en && ptcgdb map-tcgdex && ptcgdb map-ja   # 跨语言映射：EN 桥 → TCGdex ID → JP 名
```

**SDK**

```python
from ptcgdb.sdk import open_db

db = open_db("data/ptcg-cn.db")               # 或 open_jsonl("dist/")，同一接口
pool = db.legal_at(date="2026-08-01", format="standard")   # -> LegalityPool
text = db.effective_text("CSM2DC-339", date="2026-08-01")  # 勘误 > 最新印刷 > 原文
cards = db.search_cards(name="喵喵", marks=("G", "H", "I"))
# Phase 2：db.validate_deck(my_deck, ...) -> DeckReport（结构化违规列表）
```

## 🏗️ 架构

```mermaid
flowchart TB
    subgraph SRC["📥 数据源"]
        A["tcg.mik.moe<br/>主源 · 公开 JSON API（D1=路线B）"]
        B["官网赛制页 / 公告<br/>合法性权威源"]
        C["官方小程序<br/>四层防护不可得 · Phase 2 交叉源"]
        D["TCGdex / pokemon-tcg-data / PokéAPI<br/>跨语言映射源（EN→JA 名字级 dexId 链）"]
        E["pokemon-card.com<br/>官方卡查 · 抽样权威核对"]
    end

    subgraph PIPE["⚙️ 数据管线"]
        RAW[/"raw/ · append-only 原始层"/]
        NORM["normalize<br/>Pydantic 校验 + 字段归一 + 派生计算"]
        MAP["mapping<br/>EN 桥 → TCGdex ID → JP 名（置信度分档）"]
        DB[("SQLite (WAL)<br/>draft → 校验 → active")]
    end

    subgraph OUT["🔌 消费层"]
        CLI["CLI · typer"]
        DIST["dist/ · 七件套导出<br/>manifest / jsonl / legality / checksums"]
        SDK["ptcgdb.sdk<br/>open_db / open_jsonl 双后端"]
    end

    MON["🛰️ monitor<br/>每日 cron · 总量探测 + 页面 hash → 变更提案"]

    A --> RAW
    B --> RAW
    D --> RAW
    RAW --> NORM --> DB
    RAW --> MAP --> DB
    E -.->|抽样核对 31 张 · 一致率 100%| MAP
    DB --> CLI
    DB --> DIST
    CLI --> SDK
    DIST --> SDK
    B -.-> MON
    MON -.->|人工确认 → 新快照| DB

    classDef source fill:#dbeafe,stroke:#3b82f6,color:#1e293b;
    classDef pipe fill:#fef3c7,stroke:#f59e0b,color:#1e293b;
    classDef out fill:#dcfce7,stroke:#22c55e,color:#1e293b;
    classDef mon fill:#f3e8ff,stroke:#a855f7,color:#1e293b;
    class A,B,C,D,E source;
    class RAW,NORM,MAP,DB pipe;
    class CLI,DIST,SDK out;
    class MON mon;
```

## 🗺️ Roadmap

- ✅ **M0** 主数据源决策（D1 = 路线 B：mik.moe 公开 API；小程序接口四层防护否决）
- ✅ **Phase 1a** schema 建库 + 全卡首批入库（129 系列 / 12,420 张）+ 校验报告
- ✅ **Phase 1b** 环境快照 + 合法性引擎 + 版本化/回滚 + 导出七件套 + SDK 双后端
- ✅ **Phase 1c** L0/L1 自动更新管线 + M4 验收 A1~A8 全过（赶在 2026-09-16 新包发售前就位）
- 🔄 **Phase 2** —— ✅ 跨语言映射 M6：EN 桥 12,337（99.3%）→ TCGdex ID 12,322（99.88%）→ JP 名 9,480（官方抽样核对 100%）；⬜ 同名计数引擎 + 卡组校验器 `validate_deck`（M7）
- ⬜ **Phase 3** 效果标签层，配合规则引擎
- ⬜ **Phase 4** 对战模拟与胜率统计（独立库，主库只读）

> ⚠️ 临近事件：**2026-09-16「30周年庆典」全球同步发售**（简中首次同步，新罕贵度 FUR），更新管线将迎来首次实战。

## 📚 文档

| 文档 | 内容 |
|---|---|
| [PRD v1.6](docs/简中PTCG卡牌数据库_PRD与技术方案.md) | 权威设计：赛制调研、数据模型、合法性引擎、导出契约、SDK 设计、跨语言映射（名字级 dexId 链） |
| [主源接口文档](docs/mikmoe-api.md) | tcg.mik.moe `/api/v3/card/*` 端点、字段形态、限速约定 |
| [STATUS.md](STATUS.md) | 当前阶段、里程碑进度、决策日志 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更（四段式，数据日历版本 + schema SemVer 双轨） |
| [AGENTS.md](AGENTS.md) | 工程约定与技术红线（协作者/AI 共读） |

## 🙏 致谢与对标

站在这些项目的肩膀上：[pokemon-tcg-data](https://github.com/PokemonTCG/pokemon-tcg-data) · [TCGdex](https://github.com/tcgdex/cards-database) · [PokéAPI](https://github.com/PokeAPI/pokeapi) · [type-null/PTCG-database](https://github.com/type-null/PTCG-database) · [TCG ONE](https://github.com/axpendix/tcgone-engine-contrib) · [ryuu-play](https://github.com/keeshii/ryuu-play) · [MTGJSON](https://mtgjson.com/) · [Cryst's Cards Database](https://tcg.mik.moe/)

## ⚖️ 合规声明

本项目与 Nintendo、The Pokémon Company、宝可梦（上海）**无任何隶属或背书关系**。卡面文本与卡牌数据版权归宝可梦（上海）/ The Pokémon Company 所有；本项目**不采集、不存储、不分发卡图**，卡牌数据库不进入本仓库、不公开分发，仅限本地研究与工具自用。

## 📄 License

代码与文档基于 [MIT License](LICENSE) 发布（卡牌数据版权见上方声明，不在许可范围内）。

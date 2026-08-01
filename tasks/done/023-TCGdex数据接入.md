# 023 · TCGdex 数据接入与 EN→TCGdex ID 解析

| 项 | 内容 |
|---|---|
| 状态 | DONE |
| 关联 | PRD §2.4（v1.5 修订后）；里程碑 M6；JP 映射前置 |
| 预估 | 1 天 |

## 目标

TCGdex 静态数据（GitHub cards-database / api.tcgdex.net）一次性入 raw 层（append-only + manifest）；建立 mik 英文桥字段（`setCodeEn/cardIndexEn`）→ TCGdex card ID 的解析表；顺带做**系列级跨源对账**（TCGdex zh-cn 系列壳 vs 本库 sets：系列名 + 卡数）。纯本地为主，零限速压力（GitHub 静态下载 + 低频 API）。

## 步骤

- [x] TCGdex 数据获取方式选型（api.tcgdex.net 低频批量 4 端点 + pokemon-tcg-data sets/en.json）并落 raw 层 + manifest
- [x] setCodeEn → TCGdex set id 映射表（名字连接 + 词表覆盖文件兜底）
- [x] 全库解析：12,337 条 mik_en 桥 → TCGdex card ID 覆盖率报告；未解析清单分类
- [x] 系列级对账：TCGdex zh-cn `/v2/zh-cn/sets` vs 本库 sets（名称、total 卡数）
- [x] 对账报告落 reports/，差异项如实记录不猜测

## 验收标准

- [x] EN 桥 → TCGdex ID 覆盖率报告 + 未解析清单全部有归类
- [x] 系列级对账完成，差异清单落报告
- [x] 测试绿、ruff 通过（测试零网络，fixture 数据）

## 完成总结（DONE 时填写）

**实现**：`ptcgdb/mapping/tcgdex.py`（fetch_raw / load_set_map / load_subset_map /
resolve_en / reconcile_sets / names_equivalent）+ CLI `map-tcgdex [--fetch]` +
词表覆盖 `config/tcgdex_set_map_overrides.yml`；报告
`reports/mapping-tcgdex-20260801.md`；tests/test_mapping_tcgdex.py 6 测（零网络 fixture）。

**解析结果（真实库首跑定稿）**：mik_en 12,337 条 → **resolved 12,322（99.88%）**，
unmapped_set 0，missing_card 6，name_mismatch 9。

- 6 张 missing：Fairy Energy ×5（mik `Energy-44`，TCGdex 无对应 EN 印刷）+
  `SVP-190`（mik 桥值 `DRI-1055` 疑为 mik 侧笔误，不猜）。均如实入报告。
- 9 张 name_mismatch：sm5/sm6/sv03 各若干（mik 桥名缺 "ex" 等真实命名缺口），
  ID 链接已落 `tcgdex_ids`，差异留人工裁决。

**实测修正的三类系统性形态**（均已数据驱动处理，无硬猜）：

1. **ptcd id ≠ TCGdex id**（SV 代起分叉：sv2 vs sv02）→ 名字连接
   （ptcd ptcgoCode→name × TCGdex en-sets name→id）；同码主套/子集冲突取最短名，
   子集另落 `load_subset_map`。
2. **编号形态差异**：零填充（`sv01-1` vs `sv01-001`）、字母前缀
   （`SMP-25` vs `smp-SM25`、`SP-17` vs `swshp-SWSH017`，后缀索引无歧义才命中）、
   子集套编号（`SIT-TG2` → `swsh12.5tg-TG02`，主套+子集套 × 原样/两位/三位填充）。
3. **命名惯例差异**（仅校验用豁免）：TCGdex 人物括注尾缀 "(Professor Magnolia)"、
   棱镜星 mik "Prism Star" vs TCGdex "◇"、变音符（Poké/Poke）。
   剩余不一致项不豁免，如实告警。

**系列级对账结论**（TCGdex zh-cn 壳 57 套 vs 本库 129 套）：一致 0、卡数差异 41、
名称差异 1、TCGdex 有壳本库无 15（含繁中命名套如「火箭隊的榮耀」及小写 csm 系
早期壳）、本库有 TCGdex 无壳 88（礼盒/起始卡组/宝石包/收集啦151 等简中独占商品）。
TCGdex zh-cn 壳的 total 口径与本库实际收录数系统性不符（如 CSM1aC 151 vs 211），
证实其 zh-cn 数据覆盖度有限，仅可作壳级参照，不可作卡级校验源。

**重要实测结论（影响 task 024）**：TCGdex EN/JA 卡 id **不共构**（交集仅个位数，
JA 自体系 SV8/S12 等）——PRD v1.5「同 ID 多语言共构取 JP」的前提证伪，
JP 链路需在 task 024 重新设计。

**验证**：pytest 177 全绿、ruff 通过；reports 两份（mapping-tcgdex 定稿 +
mapping-en 继承 task 022）。

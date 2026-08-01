# 023 · TCGdex 数据接入与 EN→TCGdex ID 解析

| 项 | 内容 |
|---|---|
| 状态 | TODO |
| 关联 | PRD §2.4（v1.5 修订后）；里程碑 M6；JP 映射前置 |
| 预估 | 1 天 |

## 目标

TCGdex 静态数据（GitHub cards-database / api.tcgdex.net）一次性入 raw 层（append-only + manifest）；建立 mik 英文桥字段（`setCodeEn/cardIndexEn`）→ TCGdex card ID 的解析表；顺带做**系列级跨源对账**（TCGdex zh-cn 系列壳 vs 本库 sets：系列名 + 卡数）。纯本地为主，零限速压力（GitHub 静态下载 + 低频 API）。

## 步骤

- [ ] TCGdex 数据获取方式选型（repo 克隆 vs API 批量）并落 raw 层 + manifest
- [ ] setCodeEn → TCGdex set id 映射表（词表文件，人工核对 + 实测修正）
- [ ] 全库解析：12,420 张 → TCGdex card ID 覆盖率报告；未解析清单分类（映射表缺 set / 卡号形态差异 / 简中独占无对应）
- [ ] 系列级对账：TCGdex zh-cn `/v2/zh-cn/sets` vs 本库 sets（名称、total 卡数；注意 CSV1C 双条目、CSMPiC total/official 差异等已知形态）
- [ ] 对账报告落 reports/，差异项如实记录不猜测

## 验收标准

- [ ] EN 桥 → TCGdex ID 覆盖率报告 + 未解析清单全部有归类
- [ ] 系列级对账完成，差异清单落报告
- [ ] 测试绿、ruff 通过（测试零网络，fixture 数据）

## 完成总结（DONE 时填写）

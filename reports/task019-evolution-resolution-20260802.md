# task 019 进化解析收敛报告（2026-08-02）

## 背景

`resolve_evolution` 原设计只在本系列 records 内匹配（M1 derive 设计边界），跨系列进化
（SMP 促销/礼盒卡的 pre-evo 在其他系列）解析不出。真实库 401 条未解析（task 017 A3 发现）。

## 改造前分类（401 条）

| 分类 | 数量 | 说明 |
|---|---|---|
| 跨系列可解析 | 386 | pre-evo 同名/同种宝可梦在库内其他系列（SMP/CSMPiC/SSP 等 26 个系列） |
| 化石类（表面豁免） | 15 | 来源为「古老的X化石/秘密琥珀」道具 |

## 改造

- `resolve_evolution(records, questions, db_cards=None)`：系列内优先；无命中回退全库索引
  （by_name/by_species，本系列旧行排除）；同名多印刷取 card_id 最小者（与原语义一致）；
  链根可跨系列续走（db_cards 带 evolves_from_id）；仍无候选 → None + question。
- `ingest_set` 入库前一次性读全库五列构建索引（12,420 行，单次查询）。
- 新增 3 个单测：跨系列回退 / 系列内优先 / 链根跨库续走。

## 结果（真实库，31 个系列重 ingest，skipped=0）

- **401 → 5**。386 条跨系列全部解析；15 条化石类中 **10 条实际可解析**——化石道具卡
  在 SVP 系列有收录（如「古老的秘密琥珀」= SVP-015，SSP-186 化石翼龙正确指向它）——
  原"合理豁免"分类对它们是误判，改造顺带修正。
- 最终 5 条未解析均为化石道具**库内无收录**（古老的头盖/颚之/盾甲/羽毛化石），
  属合理豁免，A3 报告如实记录。
- 指向完整性：evolves_from_id 指向不存在卡的边 = 0。
- FR-2.3 全量重校验：六规则全过（`reports/validation-20260801T164318Z.md`，
  12,420 张 / 129 系列 / 抽样 689 张一致率 100%）。
- A3 复跑（同 seed=20260801）：自动校验 5,122 项次全过；豁免清单 386 跨系列 → 0，
  仅剩 5 条化石豁免（`reports/sampling-a3-20260802.md` 对比 `sampling-a3-20260801.md`）。

## 影响面

- 卡数/系列数不变（12,420 / 129）；重 ingest 保留既有 status（task 013 语义）。
- card_relations 新增跨系列 evolves_from/evolves_to 边（386+10 条级）；evolution_chain_id 更准。
- 数据库备份：`data/versions/ptcg-cn-pre-task019-20260802T004139.db`。

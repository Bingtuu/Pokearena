# task 030 验收报告：A2 比对三件技术债修复（F-01/F-02/F-03）

日期：2026-08-03/04 · 真实库 `data/ptcg-cn.db`（user_version=7）· 全程本地零网络

## 结论

三件技术债全部清偿，另修复一件顺路发现的 ingest 跨系列反向行缺陷。真实库验证全过、pytest 303 全绿、ruff 全净、导出复跑完成。

## F-01 number_display 分母改逐系列种子口径

- migration 007：`sets.card_face_total`；种子 `config/set_card_face_totals.yml`（41 套 total 型 + 1 套 packs 型，TCGdex zh-cn 系列壳 sanity 门生成 + 实测优先）。
- 未播种冲突 6 项如实入清单：CBB2C/3C/4C/5C（tcgdex 缺口 + 包计数与实测不符，疑似同号异画去重缺口，待另立案）+ CBB1C。
- 5 个 A2 实测数据点全部对平：

| 卡 | 卡面分母 | 库内 number_display |
|---|---|---|
| CS1DC-009 | 207 | 009/207 ✅ |
| CS4DaC-431 基本斗能量 | 414 | 431/414 ✅ |
| CSM1cC-212 双重无色能量 | 151 | 212/151 ✅ |
| CSM2.1C-044 基本钢能量 | 045 | 044/45 ✅（前导零规范化） |
| CSV10C-287 尖钉能量 | 222 | 287/222 ✅ |

- 种子未覆盖系列只显示分子不带分母（如 CSVL1C-131 → `131`）；CBB* 宝石包按包分母（CBB3C-2001 → `2001/6`）。

## F-02 字母编号能量卡 alias

- migration 007：`cards.alias_of`；`mark-aliases` 落地 16 张（CS4DaC/CSVL1C 各 8，FIG/MET/WAT/GRA/LIG/PSY/DAR/FAI → 数字正本，raw 逐字段全等的 mik 双重列示）。
- 数字正本可溯（如 CS4DaC-FIG → CS4DaC-431）；12,420 总数与主键口径不变；CSVH5C `NaN1` 等无数字孪生条目保留入 questions。

## F-03 is_tera 走 ptcd subtypes

- `map-tera`：ptcd EN 卡 subtypes 含 'Tera' → is_tera=1，共 166 张。
- 3 个确诊样本全中：CSV5C-162 / CSV9.5C-245 / CSV9C-259（导出复跑后仍为 True）。
- 猛雷鼓ex 全 0（不误判）；太乐巴戈斯印刷级=1；rule_box_type 维持 ex 不变。
- 报告：`reports/mapping-tera-20260803.md`。

## 顺路修复：ingest 跨系列 evolves_to 反向行顺序相关丢行

- 现象：dist/relations.jsonl（task 019 时代）比全量重 ingest 多 63 行 evolves_to；深挖后定位为 ingest 缺陷——删除按 `card_id∈本系列` 会清掉他系列指向本系列的 evolves_to 反向行，而 records 只覆盖本系列卡、不重建，结果与系列入库顺序相关（实测丢 151 行、多 88 行）。
- 修复：`ptcgdb/normalize/ingest.py` 补写「他系列卡 evolves_from_id 指向本系列」的 evolves_to 反向行，单系列重入库结果与顺序无关。
- 验证：全 129 系列重 ingest 后 evolves_from = evolves_to = 3,741（= evolves_from_id 非空卡数），完全对称；回归测试 `test_ingest_cross_set_evolves_to_rerun`（重入库先行侧/后行侧系列双向断言）。
- 澄清：22,514 vs 7,404 的"蒸发"是口径误会——relations.jsonl 含 card_relation(7,404) + name_group(2,690) + cards_name_group(12,420) 三种 kind；mentions/reprint_of 关系从未在任何版本 ingest 中生成（git -S 全史为空）。

## 复跑验证

- `ptcgdb validate`：FR-2.3 六规则 12,420 卡 / 129 系列 0 失败（`reports/validation-20260803T163324Z.md`）；`activate` 全系列已 active。
- pytest 303 passed；ruff all checks passed。
- `ptcgdb export --out dist/`：v20260804.0（fallback 口径不变），relations 22,610 行（card_relation 7,500 = 3,741×2+18），cards/sets/tournaments 等计数与 M9-2 持平。
- ingest 重入库保留富化字段（is_tera/alias_of/name_ja/card_face_total），全量重 ingest 两轮后 16 alias / 166 tera / name_ja 9,480 / name_en 12,337 均无损。

## 已知缺口（另立案候选）

- CBB1C~CBB5C 包计数与实测不符 6 项：疑似同号异画去重缺口，需核查 mik 原始列示。
- 种子未覆盖系列分母待补（TCGdex zh-cn 壳无 official 字段的系列）。

# task 028 Limitless 双通道采集/入库报告（2026-08-08）

范围：FR-9.1a EN 对齐窗口（2025-04-11 ~ 2026-04-09）官方系列赛数据基建。
双通道：API（play.limitlesstcg.com，source=limitless）+ 主站 HTML 人工收录
（limitlesstcg.com，source=limitless_site）。本报告数字均来自真实库实测
（user_version=10），采集与入库命令见末节。

## 1. 采集结果

### 主站通道（limitless_site）

- run_id=20260808T133255Z-8a65c919，status=ok，question=0，missing=0
- accepted=39：regional 26 / special 10 / international 3（逐场取舍见
  data/raw/runs/20260808T133255Z-8a65c919/scraped.json）
- rejected=10（如实记录，均未擅自扩 scope）：
  - World Championships 2025（id=500）：名称未命中官方系列赛模式（"World
    Championships" 不在 SITE_TIER_PATTERNS）——拍板范围外，待立项评审；
  - Singapore/Philippines/Malaysia Master Ball League（id=511/506/505）：
    同上未命中——亚洲联赛系列，二期再议；
  - Korean League S2/S3/S4、Indonesia/Malaysia/Philippines Premier Ball
    League（6 场）：JP/亚洲国内赛事，FR-9.1a 本轮只收 EN 官方系列赛。

### API 通道（limitless，DB 现状 8 场）

- special 2 + league_cup 6（均为 Limitless 平台线上赛，窗口内）；
- topcut_slots 仅 1/8 有值（pairings phase=2 反推），其余无淘汰赛对阵数据；
- 主站 39 场与 API 8 场无重叠（主站为线下官方大赛，API 收录为线上平台赛）。

## 2. 映射修复（ptcd 修饰名 bug，TDD 修复）

- 根因：ptcd 变体名带尾部括号修饰（PAL sv2-172 = "Boss's Orders (Ghetsis)"），
  映射链用 ptcd 定位名走 CN name_en 桥精确匹配失败，误判 unmapped。
- 修复：map_decklist_card 增 paren_strip 回退层——CN 桥 0 命中且名尾带
  " (X)" 时剥修饰重试（ptcd 与 name_fallback 两路径同层；精确命中优先不误剥，
  全链确定性不变）。规则计数名 "paren_strip"。
- 回归测试 4 条（tests/test_ingest_limitless.py）：ptcd 路径 / name_fallback
  路径 / 精确命中不触发 / 剥后仍无候选照旧 unmapped。

### 修复前后对比（真实库，limitless_site）

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| decks full | 371 | 425（+54） |
| decks partial | 552 | 498（-54） |
| 未解析行（deck_cards card_id NULL） | 1697 | 1416（-281） |
| 未解析名数 | 39 | 37 |
| Boss's Orders 未解析 | 280 卡组 | 0（-> CSVH5aC-022） |
| Professor's Research 未解析 | 1 卡组 | 0 |

280 个误伤卡组中 54 个越过 0.95 阈值转 full，其余仍带 Mega 时代未收录卡
保持 partial（分档正确）。paren_strip 层命中 302 条映射调用。

### 映射决策分布（修复后 ingest 输出， mapping_rules 计数）

```
ptcd+env+latest                    24113
ptcd+unique                         1388
name_fallback+env+latest            1284
ptcd+basic_energy_alias+env+latest  1046
ptcd+latest                          310
ptcd+paren_strip+env+latest          302
unmapped                            1616（处理事件计数；DB 唯一行 1416）
```

### 未解析名分类（37 名，全部为 Mega 时代 CN 未收录卡，分档正确不动）

Lillie's Determination 427 / Hilda 124 / Mega Kangaskhan ex 95 / Poké Pad 92 /
Mega Absol ex 85 / Fighting Gong 83 / Genesect ex 72 / Dawn 61 / Jellicent ex 56 /
Mystery Garden 53 / Mega Diancie ex 37 / Premium Power Pro 30 / Mega Mawile ex 26 /
Mega Lopunny ex 25 等（行数 = deck_cards 行，卡组数同行数）。

## 3. 质量门与对账

- 60 张质量门：真实数据 blocked=0（39 场全部卡组 60 张齐）。
- ingest 计数（修复后一轮）：tournaments=39 appearances=1159 deck_cards=29829
  truncated=9521（名次截断：主站全交表收录只入 Top32/Top8 上位）；
  DB 唯一内容卡组 923（full 425 / partial 498）。
- topcut_slots 覆盖：limitless_site 39/39（截断后实际入库名次数物化）。
- NAIC 2025（limitless_site:463，主站 390 行全收录 -> 入库 Top 32）抽对：
  我方 rank 1~12 的 archetype 与主站页面 data-deck 逐一比对 12/12 一致
  （Gardevoir, Gardevoir, Dragapult, Gardevoir, Toedscruel Ogerpon,
  Grimmsnarl Froslass, N's Zoroark, Dragapult, Dragapult Dusknoir,
  Dragapult Charizard, Dragapult Dusknoir, Dragapult Charizard）；
  Top32 分布：Dragapult Dusknoir 8 / Gardevoir 6 / Dragapult 4 /
  Dragapult Charizard 4 / Raging Bolt Ogerpon 4 / Grimmsnarl Froslass 2 /
  其余 4 名各 1。比对页：https://limitlesstcg.com/tournaments/463

## 4. 已知缺口（如实记录）

- pairings：主站通道无 pairings（人工收录只有名次+卡组），pairings 表仍 1184
  行（全部来自 API 通道）；WR A 层对主站数据不可用，走 B 层。
- record 三列主站恒 NULL（不猜）；division 恒 NULL——与「division 未知
  （NULL）不排除」语义叠加后，--division senior 查询会带上主站赛事，如需
  排除暂无 source 过滤参数（待拍板）。
- mik_moe topcut_slots 0/26（历史已知缺口，STATUS 有案）；limitless 1/8。
- World Championships 2025 与亚洲 Master/Premier Ball League 拒收待二期拍板。

## 5. 统计层冒烟

`ptcgdb stats usage --basis intl_aligned --from 2025-04-11 --to 2026-04-09
--division ""` -> n_tournaments=44（API 8 + 主站 39 中静态权重有效者），
meta 回显正常，主站数据已被三指标消费。

## 6. 复算入口

```
ptcgdb scrape limitless-site                 # 主站采集（限速 2.5s/请求）
ptcgdb ingest-limitless-site                 # 入库（幂等）
ptcgdb query "SELECT mapping_status, count(*) FROM decks
              WHERE source='limitless_site' GROUP BY 1"
```

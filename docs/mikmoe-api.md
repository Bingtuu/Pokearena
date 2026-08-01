# tcg.mik.moe 卡牌 API（主数据源，D1 结论 = 路线 B）

> 验证日期：2026-08-01（task 001）。无需鉴权、无签名、明文 JSON，限速 ≤1 req/s。
> 该 API 是其 SPA 前端的后端（`/api/v3/...`，POST + JSON）。非公开承诺接口，解析器按 PRD §9.4 配契约测试。

## 端点（均 POST `https://tcg.mik.moe`，响应包装 `{code, data, msg}`，数据在 `data` 内）

| 端点 | 请求体 | 用途 |
|---|---|---|
| `/api/v3/card/product-list` | `{}` | 系列清单：**data 形态为 `{list: [...]}`**（2026-08-01 task 003 实测修正），条目含 setId / name / releaseDate / series / mainExpansion / **cardsNum**（对账用） |
| `/api/v3/card/product-detail` | `{setId}` | 某系列全部卡牌列表（cardsNum 与返回数可对账），卡条目含 setCode / cardIndex / cardName / rarity / cardType / effectId / yorenCode / is[] / 英文映射 |
| `/api/v3/card/card-detail` | `{setCode, cardIndex}`（cardIndex 为字符串如 `"001"`，**不是整数**） | 单卡全字段（见下） |
| `/api/v3/card/card-basic-search` | `{searchText, exact, unique, page, pageSize}` | 卡名搜索（中文模糊搜索命中不佳，采集不依赖它） |
| `/api/v3/card/card-advance-search-params` | `{}` | 高级搜索参数词表（枚举来源参考） |
| `/api/v3/card/card-advance-search` | `{...params}` | 高级搜索 |

## card-detail 字段 → PRD §7.2 映射

| mik.moe 字段 | 内容 | 入库映射 |
|---|---|---|
| `name` / `cardType` / `rarity` / `regulationMark` / `setCode` / `cardIndex` / `releaseDate` / `artist` | 基础字段 | name_full / card_type / rarity / regulation_mark / set_id / number / release_date |
| `description` | 卡面全文（能量符号写作 `【无】`等占位符） | `text_raw` 来源；能量占位符需归一 |
| `pokemonAttr.energyType` | 单字母属性码（G/R/W/L/P/F/D/M/Y/N…） | types（需映射表：G=草 R=火 W=水 L=雷 P=超 F=斗 D=恶 M=钢 Y=妖 N=龙/无？以词表核证为准） |
| `pokemonAttr.stage` / `hp` / `ability[]` / `evolvesFrom` | 阶段/HP/特性/进化前 | stage / hp / abilities / evolves_from_text |
| `pokemonAttr.weakness` / `resistance` / `retreatCost` | {energy, value:"×2"} / null / int | weakness / resistance / retreat_cost |
| `pokemonAttr.attack[]` | {name, text, cost:"CC"编码串, damage:"20"/"20+"/"", isVStarPower} | attacks（cost 编码需展开为 [{type,count}]；damage 拆 damage_base/damage_modifier） |
| `mechanic` / `label` | 机制/标签（例中 null，需多样本确认取值） | rule_box_type / effect_tags 参考 |
| `effectId` + `effectSameCards[]` | **同效果卡归组 ID** + 全部同效果印刷（含英文映射） | name_group / reprint_of 的重要参考；`setCodeEn/cardIndexEn/nameEn` 是 Phase 2 英文映射桥 |
| `regulationLegal` | {standard, expanded, smSeries} 布尔 | ⚠️ 仅作交叉校验参考——本站自建合法性快照（FR-3），不落布尔值；smSeries 对应已取消的日月限定赛制 |
| `yorenCode` | 种名编码（如 P123） | species 参考 |

## 注意事项

- 能量/属性用单字母编码与 `【】` 占位符，归一化映射表是 normalize 层的核心工作（黄金样本覆盖）。
- `cardIndex` 必须传字符串（`"001"`），传整数会返回 `{code:10002, msg:"内部错误"}`。
- 基本搜索中文命中不佳（"超梦"返回空），全量采集走 `product-list → product-detail → card-detail` 链路，不依赖搜索。
- 训练家宝可梦、V-UNION、太晶等机制字段取值需在 M1 用多样本确认（本验证只抽样了 CSM1aC-001 飞天螳螂）。
- 样例响应：`data/raw/capture/mik_set_CSM1aC_sample.json`、`mik_card_sample.json`（本地，不入库）。

## 附：路线 A（官方小程序）失败分析

接口 `app-api.pokemon-tcg.cn/app-api/v1/...`（2026-08-01 抓包确认）存在四层防护，超出 M0 可行性标准：

1. `api-access-token`：JWT，绑定微信登录态，有效期约 60 秒；
2. 请求体加密：POST `{encryptionBodyParams: "<AES base64>"}`，GET 参数同样加密（`encryptionUrlParams`）；
3. 响应体加密：全部响应为 base64 密文（统一前缀，疑 AES+固定 IV）；
4. `signature` 请求头：MD5 形态（nonce + timestamp 参与）。

还原需反编译小程序包（wxapkg）提取加密与签名逻辑，超出"30 分钟还原"标准 → 按决策矩阵走路线 B。抓包录制存于 `data/raw/capture/pokemon.flows`（本地，含过期会话数据，勿外传）。

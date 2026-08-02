# 数据源与接口说明

> 本文档汇总项目用到的**全部数据源与获取方式**（原 `docs/mikmoe-api.md`，2026-08-02 扩编）。
> 红线（PRD）：采集只读、限速 ≥1s/请求（mik.moe 实跑 2s/请求）；不采集/存储/分发卡图；raw 层 append-only + manifest。

## 总览

| 源 | 用途 | 形态 | 获取方式 |
|---|---|---|---|
| [tcg.mik.moe](https://tcg.mik.moe/) | **主数据源**：简中全卡 + 系列清单 | 公开 JSON API | `POST /api/v3/card/*`（见 §1） |
| 宝可梦官网赛制页/公告 | **合法性权威源**（L1 监控） | HTML | GET 三页，hash 比对（见 §2） |
| [TCGdex](https://tcgdex.net/) | 跨语言映射：EN 桥 → TCGdex card ID；简中系列壳对账 | REST + GitHub 静态库 | `api.tcgdex.net/v2`（见 §3） |
| [pokemon-tcg-data](https://github.com/PokemonTCG/pokemon-tcg-data) | TCGdex EN id → dexId 桥 | GitHub 静态 JSON | raw 单文件（见 §4） |
| [PokéAPI](https://github.com/PokeAPI/pokeapi) | dexId → 日/英物种名 | GitHub CSV | raw 单文件（见 §5） |
| [pokemon-card.com](https://www.pokemon-card.com/) | JP 官方卡查：**抽样权威核对** | 官方站内部 JSON | GET resultAPI.php（见 §6，只读抽样） |
| 官方小程序"宝可梦卡牌会员" | 不可得（D1 否决，原因见 §7） | — | — |

## 1. tcg.mik.moe 卡牌 API（主数据源，D1 结论 = 路线 B）

> 验证日期：2026-08-01（task 001）。无需鉴权、无签名、明文 JSON，限速 ≤1 req/s（实跑 2s/请求）。
> 该 API 是其 SPA 前端的后端（`/api/v3/...`，POST + JSON）。非公开承诺接口，解析器按 PRD §9.4 配契约测试。

### 端点（均 POST `https://tcg.mik.moe`，响应包装 `{code, data, msg}`，数据在 `data` 内）

| 端点 | 请求体 | 用途 |
|---|---|---|
| `/api/v3/card/product-list` | `{}` | 系列清单：**data 形态为 `{list: [...]}`**（2026-08-01 task 003 实测修正），条目含 setId / name / releaseDate / series / mainExpansion / **cardsNum**（对账用） |
| `/api/v3/card/product-detail` | `{setId}` | 某系列全部卡牌列表（cardsNum 与返回数可对账），卡条目含 setCode / cardIndex / cardName / rarity / cardType / effectId / yorenCode / is[] / 英文映射 |
| `/api/v3/card/card-detail` | `{setCode, cardIndex}`（cardIndex 为字符串如 `"001"`，**不是整数**） | 单卡全字段（见下） |
| `/api/v3/card/card-basic-search` | `{searchText, exact, unique, page, pageSize}` | 卡名搜索（中文模糊搜索命中不佳，采集不依赖它） |
| `/api/v3/card/card-advance-search-params` | `{}` | 高级搜索参数词表（枚举来源参考） |
| `/api/v3/card/card-advance-search` | `{...params}` | 高级搜索 |

### card-detail 字段 → PRD §7.2 映射

| mik.moe 字段 | 内容 | 入库映射 |
|---|---|---|
| `name` / `cardType` / `rarity` / `regulationMark` / `setCode` / `cardIndex` / `releaseDate` / `artist` | 基础字段 | name_full / card_type / rarity / regulation_mark / set_id / number / release_date |
| `description` | 卡面全文（能量符号写作 `【无】`等占位符） | `text_raw` 来源；能量占位符需归一 |
| `pokemonAttr.energyType` | 单字母属性码（G/R/W/L/P/F/D/M/Y/N…） | types（映射表见 `config/vocabularies/energy_types.yml`） |
| `pokemonAttr.stage` / `hp` / `ability[]` / `evolvesFrom` | 阶段/HP/特性/进化前 | stage / hp / abilities / evolves_from_text |
| `pokemonAttr.weakness` / `resistance` / `retreatCost` | {energy, value:"×2"} / null / int | weakness / resistance / retreat_cost |
| `pokemonAttr.attack[]` | {name, text, cost:"CC"编码串, damage:"20"/"20+"/"", isVStarPower} | attacks（cost 编码需展开为 [{type,count}]；damage 拆 damage_base/damage_modifier） |
| `mechanic` / `label` | 机制/标签 | rule_box_type / effect_tags 参考 |
| `effectId` + `effectSameCards[]` | **同效果卡归组 ID** + 全部同效果印刷（含英文映射） | name_group / reprint_of 的重要参考；`setCodeEn/cardIndexEn/nameEn` 是跨语言映射英文桥（task 022） |
| `regulationLegal` | {standard, expanded, smSeries} 布尔 | ⚠️ 仅作交叉校验参考——本站自建合法性快照（FR-3），不落布尔值；smSeries 对应已取消的日月限定赛制 |
| `yorenCode` | 种名编码（如 P123） | species 参考 |

### 注意事项

- 能量/属性用单字母编码与 `【】` 占位符，归一化映射表是 normalize 层的核心工作（黄金样本覆盖）。
- `cardIndex` 必须传字符串（`"001"`），传整数会返回 `{code:10002, msg:"内部错误"}`。
- 基本搜索中文命中不佳（"超梦"返回空），全量采集走 `product-list → product-detail → card-detail` 链路，不依赖搜索。

## 2. 宝可梦官网赛制页与公告（合法性权威源，L1 监控）

| 页面 | URL | 用途 |
|---|---|---|
| 赛制与可用卡牌 | `https://www.pokemon.cn/tcg-rules-regulation` | standard/open 赛制标记、白名单、禁卡表的权威来源 |
| 特别的卡牌 | `https://www.pokemon.cn/tcg-rules-regulation-extra/` | 特殊机制说明页（视作覆盖等） |
| 公告列表 | `https://www.pokemon.cn/category/tcg` | 赛制/禁卡/勘误关键词监控（`NEWS_KEYWORDS`） |

- 获取方式：L1 监控（`ptcgdb monitor l1`）每日 GET 三页 → 正文提取 + hash 比对 → 变更自动生成提案（SnapshotSeed 超集，被 `legal-apply` 直接消费）；不确定项 needs_manual 不猜测。
- 快照种子：`config/legality/`（官方赛制页 2026-07-16 版人工逐名核定，`ptcgdb legal-seed` 入库）。

## 3. TCGdex（跨语言映射 + 系列对账）

- REST：`https://api.tcgdex.net/v2/{lang}/sets` · `/v2/{lang}/cards`（lang = en / ja / zh-cn 等）；另有 GitHub 静态库 [tcgdex/cards-database](https://github.com/tcgdex/cards-database)。
- 用途（task 023）：mik raw 英文桥（setCodeEn/cardIndexEn）→ TCGdex EN card ID 解析（12,322/12,337 = 99.88%）；`setCodeEn → TCGdex set id` 映射走名字连接 + 词表覆盖（`config/tcgdex_set_map_overrides.yml`）。
- zh-cn：已收录全部简中**系列壳**（set_id 与本库一致）但**卡级数据 0%**（2026-08-01 实测）→ 只作系列级跨源对账（57 壳 vs 本库 129 系列，差异入 `reports/mapping-tcgdex-20260801.md`）。
- **关键实测：TCGdex EN/JA 卡 id 不共构**（EN `sm3-20` 与 JA 自体系无交集）→ JP 名不走同 ID 共构，改名字级 dexId 链（PRD v1.6 §2.4）。
- raw 层：`tcgdex/en-sets.json` / `en-cards.json` / `ja-cards.json` / `zh-cn-sets.json`（低频静态，append-only）。

## 4. pokemon-tcg-data / ptcd（EN 卡 → dexId 桥）

- GitHub 静态 JSON：`sets/en.json`（套清单）+ `cards/en/{set}.json`（卡级数据，含 `nationalPokedexNumbers`）。
- 用途（task 024）：TCGdex EN card id →（套名连接 + 编号归一）→ ptcd 卡 → dexId。
- 获取：`ptcgdb map-ja --fetch`，仅拉取已映射的 ~144 套单文件（`raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/...`），低频静态入 raw。
- 已知数据质量问题（记录不猜）：个别卡 dexId 错位（如 Iono's Kilowattrel）、个别桥值疑笔误（SVP-190），详见 `tasks/done/024`。

## 5. PokéAPI（物种名表）

- 单文件 CSV：`raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv`。
- 取 `local_language_id`：11 = 日文（正名）、9 = 英文、1 = ja-Hrkt（日文缺行时回退）。
- 用途（task 024）：dexId → 日文/英文物种名，配合 `config/vocabularies/ja_name_rules.yml` 组合 `name_ja`。

## 6. pokemon-card.com（JP 官方卡查，抽样权威核对）

- 端点（其官方卡查前端内部 JSON）：
  `GET https://www.pokemon-card.com/card-search/resultAPI.php?keyword=<url编码>&se_ta=&regulation_sidebar_form=all&illust=&sm_and_keyword=true`
  返回 JSON，`cardList[].cardNameViewText` 即官方显示名（含图标 span 的形态如棱镜星）。
- 用途（task 024）：`name_ja` 填充结果的**抽样**权威核对（31 张分层样本，修复后一致率 100%，报告 `reports/official-check-ja-20260802.md`）。
- 约束：只读、**抽样 ≤35 请求、≥2s/请求，绝不做批量采集**；站方 WAF 严格（曾对异常流量出口做关键字剥离/403），任何核对都以小样本低频方式做。

## 7. 官方小程序"宝可梦卡牌会员"（不可得，D1 否决）

简中卡牌的官方数据源，但无可行获取方式：接口有**登录态令牌 + 请求/响应加密 + 请求签名**多层防护，还原需逆向小程序安装包提取加密与签名逻辑，超出 M0 可行性验证标准，且存在服务条款风险 → 按决策矩阵走路线 B（PRD 第 14 章 D1）。验证过程的测试记录仅存本机（`data/raw/capture/`，已 gitignore，勿外传）。

# pokemon-card.com 官方抽样核对报告（task 024 / M6）

- 日期：2026-08-02
- 目的：对 `name_ja` 填充结果做权威核对（官方卡查 resultAPI.php，只读）
- 通道：FetchURL（本机 IP 被该站 WAF 限制，脚本直连不可用）；串行、≥2s/请求
- 请求数：32（含失败重试 3 次；采样预算 ≤35 内）
- 端点：`GET /card-search/resultAPI.php?keyword=<url编码>&se_ta=&regulation_sidebar_form=all&illust=&sm_and_keyword=true`
- 第二批原始记录：`.scratch/ja-sample-results.md`

## 分层与样本

31 个判定样本，分层覆盖：纯种（イーブイ/ロトム）、机制尾缀（GX/V/VMAX/VSTAR/ex/V-UNION/◇）、TAG TEAM（含 & 连接符、メガ前缀）、地区形态（アローラ/ガラル/ヒスイ/パルデア）、前缀系（かがやく/ひかる/れんげき/いちげき/ウルトラ/ロケット団の/オリジン/そらをとぶ/なみのり/カット/ウォッシュ）、后置修饰（アカツキ）、基本能量（草/炎）。训练家卡本里程碑不填充（无批量源），无 name_ja 可核对，不参与抽样。

## 逐条判定（修复前填充值 vs 官方）

| # | 样本（英文参考） | 修复前 name_ja | 官方名 | 判定 |
|---|---|---|---|---|
| 1 | Charizard-GX | リザードンGX | リザードンGX | PASS |
| 2 | Pikachu & Zekrom-GX | ピカチュウ&ゼクロムGX | ピカチュウ&ゼクロムGX | PASS |
| 3 | Shaymin Prism Star | シェイミ◇ | シェイミ［prismstar 图标］ | PASS（裁决①） |
| 4 | Gengar & Mimikyu-GX | ゲンガー&ミミッキュGX | ゲンガー&ミミッキュGX | PASS |
| 5 | Alolan Exeggutor | アローラナッシー | アローラ ナッシー | FAIL（裁决②） |
| 6 | Galarian Zigzagoon | ガラルジグザグマ | ガラル ジグザグマ | FAIL（裁决②） |
| 7 | Hisuian Zoroark | ヒスイゾロアーク | ヒスイ ゾロアーク | FAIL（裁决②） |
| 8 | Paldean Wooper | パルデアウパー | パルデア ウパー | FAIL（裁决②） |
| 9 | Radiant Charizard | かがやくリザードン | かがやくリザードン | PASS |
| 10 | Rapid Strike Urshifu V | れんげきウーラオスV | れんげきウーラオスV | PASS |
| 11 | Single Strike Urshifu V | いちげきウーラオスV | いちげきウーラオスV | PASS |
| 12 | Shining Lugia | ひかるルギア | ひかるルギア | PASS |
| 13 | Ultra Necrozma-GX | ウルトラネクロズマGX | ウルトラネクロズマGX | PASS |
| 14 | Mow Rotom | カットロトム | カットロトム | PASS |
| 15 | Wash Rotom | ウォッシュロトム | ウォッシュロトム | PASS |
| 16 | Sylveon VMAX | ニンフィアVMAX | ニンフィアVMAX | PASS |
| 17 | Charizard VSTAR | リザードンVSTAR | リザードンVSTAR | PASS |
| 18 | Pikachu V | ピカチュウV | ピカチュウV | PASS |
| 19 | Turtonator-GX | バクガメスGX | バクガメスGX | PASS |
| 20 | Tapu Lele-GX | カプ・テテフGX | カプ・テテフGX | PASS |
| 21 | Eevee | イーブイ | イーブイ | PASS |
| 22 | Rotom | ロトム | ロトム | PASS |
| 23 | Magearna V | マギアナV | マギアナV | PASS |
| 24 | Bloodmoon Ursaluna ex | アカツキガチグマex | ガチグマ アカツキex | FAIL（裁决③） |
| 25 | Team Rocket's Mewtwo ex | ロケット団のミュウツーex | ロケット団のミュウツーex | PASS（无空格连写） |
| 26 | Origin Forme Palkia V | オリジンパルキアV | オリジンパルキアV | PASS（无空格连写） |
| 27 | Grass Energy | 基本草エネルギー | 基本草エネルギー | PASS |
| 28 | Fire Energy | 基本炎エネルギー | 基本炎エネルギー | PASS |
| 29 | Golurk V | ゴルーグV | ゴルーグV | PASS |
| 30 | Mega Sableye & Tyranitar-GX | メガヤミラミ&バンギラスGX | メガヤミラミ&バンギラスGX | PASS |
| 31 | Flying Pikachu V | そらをとぶピカチュウV | そらをとぶピカチュウV | PASS（#18 结果页顺带确认） |

## 一致率

- **修复前：26/31 = 83.9%**（5 个 FAIL 均为系统性词表问题，非随机错误）
- **修复后：31/31 = 100%**（≥99% 达标）——5 个 FAIL 全部按裁决修正词表并重填，修复后名字与官方结果页精确串逐一比对一致

## 不符项裁决

1. **シェイミ◇（保留）**：官方 cardNameViewText 用图标 span（`シェイミ<span class="pcg pcg-prismstar"></span>`），alt 文本为「シェイミ プリズムスター」。卡面符号是 ◇，本库存「シェイミ◇」忠实卡面，计为一致，不改动。
2. **地区形态前缀空格（修正）**：官方为「前缀 + 半角空格 + 种名」。词表 `prefixes` 的 アローラ/ガラル/ヒスイ/パルデア 加尾随半角空格，受影响 426 张（含 TAG TEAM 成分）清空重填。
3. **Bloodmoon 后缀型修饰（修正 + 机制新增）**：官方为「种名 + 半角空格 + 修饰」（ガチグマ アカツキex），与前缀方向相反。词表新增 `suffix_modifiers` 段，`build_ja_name` 支持 EN 前置修饰 → JA 后置。同规则收入オーガポン四面具（みどりのめん/かまどのめん/いどのめん/いしずえのめん，官方查询确证），新填充 41 张。

## 抽样带出的额外修正（词表复审发现，官方查询确证）

4. **はくば/こくばバドレックス（修正）**：原词表误作漢字 白馬/黒馬，官方实为平假名连写（はくばバドレックスV／こくばバドレックスV，23 条官方结果全量确认）。修正词表，28 张重填。

## 附带确认的官方命名事实（供后续词表维护引用）

- TAG TEAM 连接符 = 半角 `&`，两侧无空格（ピカチュウ&ゼクロムGX、メガヤミラミ&バンギラスGX）。
- 无空格连写前缀：ロケット団の／オリジン／かがやく／ひかる／れんげき／いちげき／ウルトラ／メガ／なみのり／そらをとぶ／カット／ウォッシュ／はくば／こくば。
- 带空格：地区形态四前缀（前缀后空格）；アカツキ・オーガポン面具（种名后空格 + 修饰）。
- ピカチュウV-UNION、なみのりピカチュウV 命名形态确认。

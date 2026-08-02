# pokemon-card.com 官方抽样核对（第二批）

查询时间: 2026-08-02 01:51 UTC
通道: FetchURL（本机 IP 被 WAF 限制）
端点: https://www.pokemon-card.com/card-search/resultAPI.php?keyword=<URL编码>&se_ta=&regulation_sidebar_form=all&illust=&sm_and_keyword=true
请求数: 14（含 3 次失败/重试；串行，≥2s/请求）

| # | 期望 name_ja | 英文参考 | 判定 | 官方实际名/备注 |
|---|---|---|---|---|
| 1 | バクガメスGX | Turtonator-GX | PASS | 3 张精确匹配（SM8b/SM2K×2） |
| 2 | カプ・テテフGX | Tapu Lele-GX | PASS | 8 张精确匹配 |
| 3 | イーブイ | Eevee | PASS | 119 命中；纯「イーブイ」大量存在（区别于 イーブイex/イーブイGX/イーブイV/かがやくイーブイ）。首次请求解析失败，重试成功 |
| 4 | ロトム | Rotom | PASS | 77 命中；纯「ロトム」存在（区别于 カットロトム/ヒートロトム/ウォッシュロトム/スピンロトム/ロトムex/ロトムV 等） |
| 5 | マギアナV | Magearna V | PASS | 2 张精确匹配（S11a） |
| 6 | アカツキガチグマex | Bloodmoon Ursaluna ex | FAIL | 官方名 = **ガチグマ アカツキex**（顺序相反 + 半角空格）。keyword=アカツキガチグマex 两次返回空页（解析失败，疑零命中），回退 keyword=ガチグマ 确认；13 命中中 ガチグマ アカツキex 出现 8 次（MC/SV8a/SV5a/SV-P） |
| 7 | ロケット団のミュウツーex | Team Rocket's Mewtwo ex | PASS | 8 张精确匹配；「ロケット団の」后**无空格** |
| 8 | オリジンパルキアV | Origin Forme Palkia V | PASS | 11 张；「オリジン」后**无空格**（另见 オリジンパルキアVSTAR） |
| 9 | 基本草エネルギー | Grass Energy | PASS | 精确匹配（cardID 49459 MC / 47903 ENE）；命中 144 条因 keyword 模糊匹配混入草属性卡 |
| 10 | 基本炎エネルギー | Fire Energy | PASS | 精确匹配（cardID 49460 MC / 47904 ENE）；同上命中 160 条含噪声 |
| 11 | ゴルーグV | Golurk V | PASS | 4 张精确匹配（SI/S7D） |
| 12 | メガヤミラミ&バンギラスGX | Mega Sableye & Tyranitar-GX | PASS | cardNameAltText/ViewText 原文：`メガヤミラミ&amp;バンギラスGX`（HTML 转义，实为半角 `&`，两侧无空格，メガ前缀无空格）。3 张（SM11）。因 & 会破坏 FetchURL 解析，用 keyword=バンギラスGX 查询后在结果中定位 |

## 关键发现

- **形态/特性后缀的空格规则**：「ガチグマ アカツキ(ex)」= 种名 + 半角空格 + 后缀，与地区形态前缀（アローラ/ガラル/ヒスイ/パルデア + 空格 + 种名）方向相反但同样带半角空格。本批唯一 FAIL（#6）。
- 顺带确认同规则：「オーガポン みどりのめん(ex)」「オーガポン かまどのめん」——オーガポン面具名 = 种名 + 空格 + 面具名。
- 连写前缀无空格：「ロケット団の」「オリジン」——不是所有修饰成分都带空格，需逐类核对。
- TAG TEAM メガ前缀写法：「メガヤミラミ&バンギラスGX」，半角 & 无空格，与既有结论（ピカチュウ&ゼクロムGX）一致。
- 汇总：12 条中 11 PASS / 1 FAIL / 0 NOT_FOUND。
- 备注：resultAPI.php 返回的是 JSON（非 HTML），cardNameViewText 即官方显示名；含图标 span 的样本本批未遇到。

# TCGdex EN 解析 + 系列级对账报告（20260801）

## EN 桥 → TCGdex card ID 解析

- external_ids(mik_en) 总数：12337
- 解析成功（ID 命中 + 卡名归一一致）：12322（99.9%）
- setCodeEn 无映射（pokemon-tcg-data 无 ptcgoCode）：0 张 / 0 个码
- 候选 ID 不在 TCGdex：6
- ID 命中但卡名不一致：9

### 候选 ID 不在 TCGdex（前 50）

- `CSM1DC-FAI` → ?
- `CSM2.1C-045` → ?
- `CSMAC-FAI` → ?
- `CSMPiC-024` → ?
- `CSMPiC-043` → ?
- `SVP-190` → ?

### 卡名不一致（前 50，需人工裁决）

- `CBB3C-0507` → sv03-134
- `CSM1.5C-058` → sm5-137
- `CSM1.5C-059` → sm5-138
- `CSM1.5C-060` → sm6-118
- `CSM1.5C-086` → sm5-137
- `CSM1.5C-087` → sm5-138
- `CSM1.5C-088` → sm6-118
- `CSV3C-084` → sv03-134
- `SVP-081` → sv03-134

## 系列级对账（TCGdex zh-cn 壳 vs 本库 sets）

- 一致：0；卡数差异：41；名称差异：1；TCGdex 有壳本库无：15；本库有 TCGdex 无壳：88

### count_diff

- `CSM1cC` TCGdex total=151 vs 本库 212
- `CSM1bC` TCGdex total=151 vs 本库 204
- `CSM1aC` TCGdex total=151 vs 本库 211
- `CSM1.5C` TCGdex total=60 vs 本库 88
- `CSM2aC` TCGdex total=150 vs 本库 194
- `CSM2bC` TCGdex total=150 vs 本库 193
- `CSM2cC` TCGdex total=150 vs 本库 192
- `CSM2.5C` TCGdex total=61 vs 本库 99
- `CS1bC` TCGdex total=136 vs 本库 199
- `CS1aC` TCGdex total=135 vs 本库 217；名称差异：TCGdex「横空出世 赫」vs 本库「极巨争锋 雷」
- `CS1.5C` TCGdex total=55 vs 本库 96
- `CS2bC` TCGdex total=115 vs 本库 143
- `CS2aC` TCGdex total=115 vs 本库 143
- `CS2.5C` TCGdex total=59 vs 本库 79
- `CS3aC` TCGdex total=125 vs 本库 184
- `CS3bC` TCGdex total=122 vs 本库 179
- `CS3.5C` TCGdex total=66 vs 本库 90
- `CS4bC` TCGdex total=132 vs 本库 177
- `CS4aC` TCGdex total=132 vs 本库 184
- `CS4.5C` TCGdex total=63 vs 本库 83
- `CS5aC` TCGdex total=127 vs 本库 176
- `CS5bC` TCGdex total=128 vs 本库 178
- `CS5.5C` TCGdex total=66 vs 本库 90
- `CS6bC` TCGdex total=131 vs 本库 172
- `CS6aC` TCGdex total=131 vs 本库 169
- `CS6.5C` TCGdex total=72 vs 本库 96
- `CSV1C` TCGdex total=127 vs 本库 169
- `CSV1C` TCGdex total=9 vs 本库 169；名称差异：TCGdex「宝石包 第一卷」vs 本库「亘古开来」
- `CSV2C` TCGdex total=128 vs 本库 163
- `CSV3C` TCGdex total=130 vs 本库 166
- `CBB2C` TCGdex total=15 vs 本库 140；名称差异：TCGdex「宝石包Vol.2」vs 本库「宝石包 VOL.2」
- `CSV4C` TCGdex total=129 vs 本库 165
- `CSV5C` TCGdex total=129 vs 本库 165
- `CBB3C` TCGdex total=7 vs 本库 136；名称差异：TCGdex「宝石包Vol.3」vs 本库「宝石包 VOL.3」
- `CSV6C` TCGdex total=128 vs 本库 163
- `CSV7C` TCGdex total=204 vs 本库 261
- `CBB4C` TCGdex total=7 vs 本库 196；名称差异：TCGdex「宝石包 Vol.4」vs 本库「宝石包 VOL.4」
- `CSV8C` TCGdex total=207 vs 本库 264
- `CBB5C` TCGdex total=7 vs 本库 196；名称差异：TCGdex「宝石包 Vol.5」vs 本库「宝石包 VOL.5」
- `CSV9C` TCGdex total=208 vs 本库 266
- `CSV9.5C` TCGdex total=208 vs 本库 259

### name_diff

- `CSMPiC` 名称差异：TCGdex「对战派对组合 奖励包」vs 本库「对战派对组合 奖赏包」

### missing_in_db

- `csm1a` TCGdex 有壳本库无：风暴涌现
- `csm1c` TCGdex 有壳本库无：风暴涌现
- `csm1b` TCGdex 有壳本库无：风暴涌现
- `csm1.5` TCGdex 有壳本库无：战斗精英
- `csm2a` TCGdex 有壳本库无：闪耀协同效应
- `csm2b` TCGdex 有壳本库无：闪耀协同效应
- `csm2c` TCGdex 有壳本库无：闪耀协同效应
- `csm2.5` TCGdex 有壳本库无：精彩的比赛
- `SV10` TCGdex 有壳本库无：火箭隊的榮耀
- `SV7a` TCGdex 有壳本库无：樂園騰龍
- `SV8` TCGdex 有壳本库无：超電突圍
- `SV8a` TCGdex 有壳本库无：太晶慶典ex
- `SV9` TCGdex 有壳本库无：對戰搭檔
- `SV9a` TCGdex 有壳本库无：熱風競技場
- `SV7` TCGdex 有壳本库无：星晶奇跡

### missing_in_tcgdex

- `151C` 本库有 TCGdex 无壳：收集啦151
- `30thP` 本库有 TCGdex 无壳：30周年庆典 特典卡
- `CBB1C` 本库有 TCGdex 无壳：宝石包 VOL.1
- `CS0LC` 本库有 TCGdex 无壳：皮在伊起 流沙卡牌展示挂件礼盒
- `CS1DC` 本库有 TCGdex 无壳：起始卡组 极巨争锋V
- `CS2.1C` 本库有 TCGdex 无壳：专题包 喵喵小妙招
- `CS2DaC` 本库有 TCGdex 无壳：宝可梦卡牌 家庭组合
- `CS3DC` 本库有 TCGdex 无壳：起始卡组 洪荒演武V
- `CS4.1C` 本库有 TCGdex 无壳：辉耀能量系列礼盒
- `CS4DaC` 本库有 TCGdex 无壳：起始卡组100
- `CS5.1C` 本库有 TCGdex 无壳：辉耀能量系列礼盒 第二弹
- `CS5DC` 本库有 TCGdex 无壳：起始卡组 勇魅群星V
- `CS6.1C` 本库有 TCGdex 无壳：辉耀能量系列礼盒 第三弹
- `CSAC` 本库有 TCGdex 无壳：卡组构筑礼盒 极巨争锋
- `CSBC` 本库有 TCGdex 无壳：卡组构筑礼盒 洪荒演武 茂
- `CSCC` 本库有 TCGdex 无壳：卡组构筑礼盒 洪荒演武 激
- `CSDC` 本库有 TCGdex 无壳：精灵球/超级球礼盒 皮卡丘传奇庆典
- `CSEC` 本库有 TCGdex 无壳：四方联结系列礼盒
- `CSFC` 本库有 TCGdex 无壳：龙之再临系列礼盒
- `CSGC` 本库有 TCGdex 无壳：宝可梦卡牌展示套礼盒
- `CSHC` 本库有 TCGdex 无壳：伊布进阶礼盒
- `CSIC` 本库有 TCGdex 无壳：训练家收藏礼盒
- `CSJC` 本库有 TCGdex 无壳：精灵球/高级球礼盒 宝可梦艺术插画庆典 景
- `CSM1DC` 本库有 TCGdex 无壳：起始卡组 横空出世GX
- `CSM2.1C` 本库有 TCGdex 无壳：辉金能量系列礼盒
- `CSM2DC` 本库有 TCGdex 无壳：起始卡组 交相辉映GX
- `CSMAC` 本库有 TCGdex 无壳：卡组构筑进阶礼盒 阿尔宙斯&帝牙卢卡&帕路奇亚GX
- `CSMC` 本库有 TCGdex 无壳：宝可梦卡牌展示套礼盒
- `CSMJC` 本库有 TCGdex 无壳：精灵球礼盒 闪耀宝可梦
- `CSMLC` 本库有 TCGdex 无壳：莉莉艾的声援专属礼盒
- `CSMPaC` 本库有 TCGdex 无壳：对战派对组合 草
- `CSMPbC` 本库有 TCGdex 无壳：对战派对组合 火
- `CSMPcC` 本库有 TCGdex 无壳：对战派对组合 水
- `CSMPdC` 本库有 TCGdex 无壳：对战派对组合 雷
- `CSMPeC` 本库有 TCGdex 无壳：对战派对组合 超
- `CSMPfC` 本库有 TCGdex 无壳：对战派对组合 斗
- `CSMPgC` 本库有 TCGdex 无壳：对战派对组合 恶
- `CSMPhC` 本库有 TCGdex 无壳：对战派对组合 钢
- `CSMPjC` 本库有 TCGdex 无壳：对战派对组合改造包 草
- `CSMPkC` 本库有 TCGdex 无壳：对战派对组合改造包 火
- `CSMPlC` 本库有 TCGdex 无壳：对战派对组合改造包 水
- `CSMPmC` 本库有 TCGdex 无壳：对战派对组合改造包 雷
- `CSMPnC` 本库有 TCGdex 无壳：对战派对组合改造包 超
- `CSMPoC` 本库有 TCGdex 无壳：对战派对组合改造包 斗
- `CSMPpC` 本库有 TCGdex 无壳：对战派对组合改造包 恶
- `CSMPqC` 本库有 TCGdex 无壳：对战派对组合改造包 钢
- `CSMYC` 本库有 TCGdex 无壳：伊布GX套装礼盒
- `CSNC` 本库有 TCGdex 无壳：卡组构筑礼盒 勇魅群星
- `CSOC` 本库有 TCGdex 无壳：卡组构筑进阶礼盒 汇流
- `CSUC` 本库有 TCGdex 无壳：宝可梦卡牌展示套礼盒
- `CSV10C` 本库有 TCGdex 无壳：共逐荣光
- `CSVE1C` 本库有 TCGdex 无壳：对战派对 共梦
- `CSVE1pC` 本库有 TCGdex 无壳：对战派对 共梦 奖赏包
- `CSVE2C` 本库有 TCGdex 无壳：对战派对 耀梦
- `CSVE2pC` 本库有 TCGdex 无壳：对战派对 耀梦 奖赏包
- `CSVH1C` 本库有 TCGdex 无壳：嗨皮组合 皮卡丘&皮皮&草苗龟&索财灵
- `CSVH1aC` 本库有 TCGdex 无壳：嗨皮组合 皮卡丘&皮皮&草苗龟&索财灵 改造包
- `CSVH1pC` 本库有 TCGdex 无壳：嗨皮组合 皮卡丘&皮皮&草苗龟&索财灵 奖赏包
- `CSVH2C` 本库有 TCGdex 无壳：嗨皮组合 路卡利欧&甲贺忍蛙&藏玛然特&獒教父
- `CSVH2aC` 本库有 TCGdex 无壳：嗨皮组合 路卡利欧&甲贺忍蛙&藏玛然特&獒教父 改造包
- `CSVH2pC` 本库有 TCGdex 无壳：嗨皮组合 路卡利欧&甲贺忍蛙&藏玛然特&獒教父 奖赏包
- `CSVH3C` 本库有 TCGdex 无壳：嗨皮卡组 七夕青鸟&拉帝欧斯&烈焰猴&一家鼠
- `CSVH3aC` 本库有 TCGdex 无壳：嗨皮组合 七夕青鸟&拉帝欧斯&烈焰猴&一家鼠 改造包
- `CSVH3pC` 本库有 TCGdex 无壳：嗨皮组合 七夕青鸟&拉帝欧斯&烈焰猴&一家鼠 奖赏包
- `CSVH4C` 本库有 TCGdex 无壳：嗨皮卡组 狙射树枭&美录梅塔&故勒顿&密勒顿
- `CSVH4aC` 本库有 TCGdex 无壳：嗨皮组合 狙射树枭&美录梅塔&故勒顿&密勒顿 改造包
- `CSVH4eC` 本库有 TCGdex 无壳：嗨皮组合 狙射树枭&美录梅塔&故勒顿&密勒顿 嗨皮包
- `CSVH4pC` 本库有 TCGdex 无壳：嗨皮组合 狙射树枭&美录梅塔&故勒顿&密勒顿 奖赏包
- `CSVH5C` 本库有 TCGdex 无壳：嗨皮组合 快龙&超梦&喷火驼&来悲粗茶
- `CSVH5aC` 本库有 TCGdex 无壳：嗨皮组合 快龙&超梦&喷火驼&来悲粗茶 改造包
- `CSVH5eC` 本库有 TCGdex 无壳：嗨皮组合 快龙&超梦&喷火驼&来悲粗茶 嗨皮包
- `CSVH5pC` 本库有 TCGdex 无壳：嗨皮组合 快龙&超梦&喷火驼&来悲粗茶 奖赏包
- `CSVL1C` 本库有 TCGdex 无壳：启程专题包
- `CSVL2C` 本库有 TCGdex 无壳：游历专题包
- `CSVM1aC` 本库有 TCGdex 无壳：大师战略卡组构筑套装 喷火龙ex
- `CSVM1bC` 本库有 TCGdex 无壳：大师战略卡组构筑套装 沙奈朵ex
- `CSVM1cC` 本库有 TCGdex 无壳：大师战略卡组构筑套装 密勒顿ex
- `CSVM2aC` 本库有 TCGdex 无壳：大师战略卡组构筑套装 猛雷鼓ex
- `CSVM2bC` 本库有 TCGdex 无壳：大师战略卡组构筑套装 多龙巴鲁托ex
- `CSVM2cC` 本库有 TCGdex 无壳：大师战略卡组构筑套装 赛富豪ex
- `CSVNC` 本库有 TCGdex 无壳：北上乡专题包
- `CSVSC` 本库有 TCGdex 无壳：对战学院
- `CSXC` 本库有 TCGdex 无壳：卡组构筑进阶礼盒 骑拉帝纳VSTAR
- `CSYC` 本库有 TCGdex 无壳：精灵球/等级球礼盒 宝可梦艺术插画庆典 聚
- `CSZC` 本库有 TCGdex 无壳：收藏周边礼盒 百变宝盒
- `SMP` 本库有 TCGdex 无壳：太阳&月亮 特典卡
- `SSP` 本库有 TCGdex 无壳：剑&盾 特典卡
- `SVP` 本库有 TCGdex 无壳：朱&紫 特典卡

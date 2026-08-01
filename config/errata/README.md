# config/errata/ — L2 勘误种子（FR-5.3）

人工维护的官方勘误/卡牌补充说明，每条一个 `*.yml` 文件，`ptcgdb legal-errata` 导入 errata 表（upsert 幂等）。
引擎 `effective_text` 消费优先级：**勘误（最新生效）> 最新印刷文本 > text_raw**。

## 格式

```yaml
errata_id: 2026-09-16-csv10c-001   # 唯一 id，建议 日期-卡号
card_id: CSV10C-001                # 库内 card_id（不存在则跳过并 warning）
effective_from: 2026-09-16         # 勘误生效日
corrected_text: |-                 # 官方公布的正确文本（逐字）
  ……
notice_url: https://www.pokemon.cn/tcg/card/xxxxx.html  # 公告链接（可空）
```

## 维护节奏

每次新包发售后 2 周内主动检查一次官网勘误公告（PRD FR-5.3）；L1 公告监控命中"勘误/规则/调整"关键词时会生成 needs_manual 提案提醒。

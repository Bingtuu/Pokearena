"""Phase 2 跨语言映射（PRD v1.6 §2.4，task 023/024 实测修订）。

链路：CN → mik raw 英文桥 → TCGdex EN id → ptcd dexId → PokéAPI JP 物种名 + 词表。
（task 023 实测：TCGdex EN/JA 卡 id 不共构，v1.5「同 ID 共构」前提已证伪）
置信度由 external_ids.system 编码来源路径：mik_en=bridge / tcgdex=tcgdex-linked。
"""

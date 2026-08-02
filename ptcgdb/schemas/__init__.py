"""Pydantic v2 模型（校验层 + SDK 返回模型，frozen）。

对应 cards 表 JSON 子结构与核心表导出形状；字段只加不删（FR-6.2）。
"""

from ptcgdb.schemas.models import (
    Ability,
    Attack,
    AttackCost,
    Card,
    LegalitySnapshot,
    Resistance,
    Set,
    Weakness,
)
from ptcgdb.schemas.tournaments import (
    AppearanceRecord,
    DeckCardRecord,
    DeckRecord,
    TournamentRecord,
)

__all__ = [
    "Ability",
    "Attack",
    "AttackCost",
    "Card",
    "DeckCardRecord",
    "DeckRecord",
    "AppearanceRecord",
    "LegalitySnapshot",
    "Resistance",
    "Set",
    "TournamentRecord",
    "Weakness",
]

"""SQLAlchemy 2 表定义（持久层）。

字段与 PRD §7 逐字段一致；JSON 字段用 SQLAlchemy JSON 类型。
"""

from ptcgdb.orm.base import Base
from ptcgdb.orm.models import (
    Card,
    CardNameGroup,
    CardRelation,
    Errata,
    ExternalId,
    LegalitySnapshot,
    Meta,
    NameGroup,
    RulesDocument,
    ScrapeRun,
    Set,
)

__all__ = [
    "Base",
    "Card",
    "CardRelation",
    "CardNameGroup",
    "Errata",
    "ExternalId",
    "LegalitySnapshot",
    "Meta",
    "NameGroup",
    "RulesDocument",
    "ScrapeRun",
    "Set",
]

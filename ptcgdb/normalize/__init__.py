"""归一层：字段归一（fields）、派生计算（derive）、入库管线（ingest）。

红线：text_raw 逐字保留绝不规范化；未知枚举零猜测，全部进词表或记 question。
"""

from ptcgdb.normalize.fields import Questions, UnknownEnumError
from ptcgdb.normalize.ingest import IngestResult, ingest_set, normalize_card

__all__ = [
    "IngestResult",
    "Questions",
    "UnknownEnumError",
    "ingest_set",
    "normalize_card",
]

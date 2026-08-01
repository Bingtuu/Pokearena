"""合法性引擎：快照判定、视作覆盖、同名计数（Phase 1b 实现）。"""

from ptcgdb.legal.seed import (
    BannedEntry,
    MarkOverride,
    SnapshotSeed,
    WhitelistEntry,
    load_seeds,
    seed_snapshots,
)

__all__ = [
    "BannedEntry",
    "MarkOverride",
    "SnapshotSeed",
    "WhitelistEntry",
    "load_seeds",
    "seed_snapshots",
]

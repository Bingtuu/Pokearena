"""下游 SDK（task 011，PRD FR-8）：SQLite 与 JSONL 双后端、同一接口。

- 返回类型一律 frozen Pydantic model（schemas/models.py），不暴露 ORM 与 session；
- 规则语义（legal_at / effective_text）只由 legal 引擎纯函数核实现，双后端行为一致；
- schema_version 显式暴露，下游一行断言即可防御不兼容升级。

```python
from ptcgdb.sdk import open_db, open_jsonl

db = open_db("data/ptcg-cn.db")      # 或 open_jsonl("dist/")
db.schema_version                    # -> "1.0.0"
db.legal_at(date="2026-08-01", format="standard")
```
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.legal.deck import validate_deck as _deck_validate
from ptcgdb.legal.engine import build_pool, resolve_text, select_snapshot
from ptcgdb.orm import Card, CardNameGroup, Errata, LegalitySnapshot, Meta, Set
from ptcgdb.schemas.models import (
    Card as CardSchema,
)
from ptcgdb.schemas.models import (
    DeckReport,
    DrilldownResult,
    EffectiveText,
    ErrataRecord,
    LegalityPool,
    StatsResult,
)
from ptcgdb.schemas.models import (
    LegalitySnapshot as SnapshotSchema,
)
from ptcgdb.schemas.models import (
    Set as SetSchema,
)
from ptcgdb.stats import engine as stats_engine
from ptcgdb.stats.jsonldb import build_stats_conn


def _as_date(d: str | date) -> date:
    return date.fromisoformat(d) if isinstance(d, str) else d


def _match(
    card: CardSchema,
    *,
    name: str | None,
    marks: tuple[str, ...] | None,
    card_type: str | None,
    has_rule_box: bool | None,
    is_tera: bool | None,
    set_ids: tuple[str, ...] | None,
) -> bool:
    """search_cards 过滤（双后端同一语义）：name 模糊匹配 name_full / species。"""
    if name and name not in card.name_full and name not in (card.species or ""):
        return False
    if marks is not None and card.regulation_mark not in marks:
        return False
    if card_type is not None and card.card_type != card_type:
        return False
    if has_rule_box is not None and card.has_rule_box != has_rule_box:
        return False
    if is_tera is not None and card.is_tera != is_tera:
        return False
    if set_ids is not None and card.set_id not in set_ids:
        return False
    return True


class CardDatabase(ABC):
    """双后端同一接口。用毕 close()。"""

    @property
    @abstractmethod
    def schema_version(self) -> str: ...

    @abstractmethod
    def get_card(self, card_id: str) -> CardSchema | None: ...

    @abstractmethod
    def search_cards(
        self,
        *,
        name: str | None = None,
        marks: tuple[str, ...] | None = None,
        card_type: str | None = None,
        has_rule_box: bool | None = None,
        is_tera: bool | None = None,
        set_ids: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CardSchema]: ...

    @abstractmethod
    def get_set(self, set_id: str) -> SetSchema | None: ...

    @abstractmethod
    def list_sets(self, era: str | None = None) -> list[SetSchema]: ...

    @abstractmethod
    def legal_at(self, date: str | date, format: str) -> LegalityPool: ...

    @abstractmethod
    def effective_text(self, card_id: str, date: str | date) -> EffectiveText: ...

    @abstractmethod
    def validate_deck(
        self, deck: list[str], date: str | date, format: str
    ) -> DeckReport:
        """FR-8 卡组校验：60 个 card_id（可重复）→ DeckReport（结构化违规，不抛异常）。

        无覆盖日期/赛制的快照时抛 LookupError。
        """
        ...

    @abstractmethod
    def snapshots(self, format: str | None = None) -> list[SnapshotSchema]: ...

    # —— 赛事统计（FR-8 Phase 2 追加，v1.10；薄封装 canonical SQL，双后端一致）——

    @abstractmethod
    def stats_usage(self, **kwargs: Any) -> StatsResult:
        """WUR 加权出场率。参数见 StatsParams（as_of/date_from/date_to/window_days/
        scope/division/tiers/include_qual/include_team/usage_basis/min_n）。"""
        ...

    @abstractmethod
    def stats_winrate(self, **kwargs: Any) -> StatsResult:
        """WR 胜率（layer=auto|a|b，mirror 口径标签）。"""
        ...

    @abstractmethod
    def stats_wws(self, **kwargs: Any) -> StatsResult:
        """WWS 加权胜率（layer=auto|a|b，k_a/k_b 贝叶斯收缩强度）。"""
        ...

    @abstractmethod
    def stats_card(self, name: str, **kwargs: Any) -> DrilldownResult:
        """单卡逐赛事钻取（name = name_group 归组 key）。"""
        ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> CardDatabase:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _row_schema(model, row) -> Any:
    return model.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


# —— 赛事统计共用实现（FR-9.7：双后端薄封装同一 canonical SQL 与 engine）——


def _stats_params(kwargs: dict) -> stats_engine.StatsParams:
    kw = dict(kwargs)
    as_of = kw.pop("as_of", None)
    date_from = kw.pop("date_from", None)
    date_to = kw.pop("date_to", None)
    window_days = kw.pop("window_days", None)
    return stats_engine.resolve_window(as_of, date_from, date_to, window_days, **kw)


def _do_usage(db: Any, kwargs: dict) -> StatsResult:
    data, meta = stats_engine.usage(db, _stats_params(kwargs))
    return StatsResult(meta=meta, data=data)


def _do_winrate(db: Any, kwargs: dict) -> StatsResult:
    kw = dict(kwargs)
    layer = kw.pop("layer", "auto")
    data, meta = stats_engine.winrate(db, _stats_params(kw), layer=layer)
    return StatsResult(meta=meta, data=data)


def _do_wws(db: Any, kwargs: dict) -> StatsResult:
    kw = dict(kwargs)
    layer = kw.pop("layer", "auto")
    data, meta = stats_engine.wws(db, _stats_params(kw), layer=layer)
    return StatsResult(meta=meta, data=data)


def _do_card(db: Any, name: str, kwargs: dict) -> DrilldownResult:
    data, meta = stats_engine.card_drilldown(db, name, _stats_params(kwargs))
    return DrilldownResult(meta=meta, data=data)


def _do_validate_deck(
    cards: list[CardSchema],
    groups: dict[str, set[str]],
    snapshots: list[SnapshotSchema],
    deck: list[str],
    d: date,
    fmt: str,
) -> DeckReport:
    """validate_deck 共用实现（FR-8：双后端同一语义）。

    卡查找用全量卡（库外才报 unknown_card）；合法卡池按 status=active 构建
    （与 legal_at 口径一致）。
    """
    snapshot = select_snapshot(snapshots, fmt, d)
    pool = build_pool([c for c in cards if c.status == "active"], groups, snapshot, fmt, d)
    return _deck_validate(deck, {c.card_id: c for c in cards}, groups, snapshot, pool)


class DbBackend(CardDatabase):
    """SQLite 后端：直接读 ptcg-cn.db。"""

    def __init__(self, db_path: str | Path):
        self._db_path = db_path
        self._engine = create_engine(f"sqlite:///{db_path}")

    @property
    def schema_version(self) -> str:
        with Session(self._engine) as s:
            row = s.get(Meta, "schema_version")
            if row is None:
                raise LookupError("meta 表缺 schema_version")
            return row.value

    def get_card(self, card_id: str) -> CardSchema | None:
        with Session(self._engine) as s:
            row = s.get(Card, card_id)
            return _row_schema(CardSchema, row) if row else None

    def search_cards(
        self,
        *,
        name: str | None = None,
        marks: tuple[str, ...] | None = None,
        card_type: str | None = None,
        has_rule_box: bool | None = None,
        is_tera: bool | None = None,
        set_ids: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CardSchema]:
        with Session(self._engine) as s:
            rows = [_row_schema(CardSchema, c) for c in s.scalars(select(Card))]
        filters = {
            "name": name, "marks": marks, "card_type": card_type,
            "has_rule_box": has_rule_box, "is_tera": is_tera, "set_ids": set_ids,
        }
        matched = [c for c in rows if _match(c, **filters)]
        return sorted(matched, key=lambda c: c.card_id)[offset:offset + limit]

    def get_set(self, set_id: str) -> SetSchema | None:
        with Session(self._engine) as s:
            row = s.get(Set, set_id)
            return _row_schema(SetSchema, row) if row else None

    def list_sets(self, era: str | None = None) -> list[SetSchema]:
        with Session(self._engine) as s:
            rows = [_row_schema(SetSchema, r) for r in s.scalars(select(Set))]
        return sorted((r for r in rows if era is None or r.era == era), key=lambda r: r.set_id)

    def legal_at(self, date: str | date, format: str) -> LegalityPool:
        d = _as_date(date)
        with Session(self._engine) as s:
            snapshots = [
                _row_schema(SnapshotSchema, r) for r in s.scalars(select(LegalitySnapshot))
            ]
            snapshot = select_snapshot(snapshots, format, d)
            cards = [
                _row_schema(CardSchema, c)
                for c in s.scalars(select(Card).where(Card.status == "active"))
            ]
            groups: dict[str, set[str]] = {}
            for cid, gk in s.execute(
                select(CardNameGroup.card_id, CardNameGroup.group_key)
            ):
                groups.setdefault(cid, set()).add(gk)
        return build_pool(cards, groups, snapshot, format, d)

    def effective_text(self, card_id: str, date: str | date) -> EffectiveText:
        d = _as_date(date)
        with Session(self._engine) as s:
            cards = {
                c.card_id: c
                for c in (_row_schema(CardSchema, r) for r in s.scalars(select(Card)))
            }
            snapshots = [
                _row_schema(SnapshotSchema, r) for r in s.scalars(select(LegalitySnapshot))
            ]
            errata = [_row_schema(ErrataRecord, e) for e in s.scalars(select(Errata))]
        return resolve_text(card_id, cards, snapshots, errata, d)

    def validate_deck(
        self, deck: list[str], date: str | date, format: str
    ) -> DeckReport:
        d = _as_date(date)
        with Session(self._engine) as s:
            cards = [
                _row_schema(CardSchema, r) for r in s.scalars(select(Card))
            ]
            snapshots = [
                _row_schema(SnapshotSchema, r) for r in s.scalars(select(LegalitySnapshot))
            ]
            groups: dict[str, set[str]] = {}
            for cid, gk in s.execute(
                select(CardNameGroup.card_id, CardNameGroup.group_key)
            ):
                groups.setdefault(cid, set()).add(gk)
        return _do_validate_deck(cards, groups, snapshots, deck, d, format)

    def snapshots(self, format: str | None = None) -> list[SnapshotSchema]:
        with Session(self._engine) as s:
            rows = [_row_schema(SnapshotSchema, r) for r in s.scalars(select(LegalitySnapshot))]
        return sorted(
            (r for r in rows if format is None or r.format == format),
            key=lambda r: (r.format, r.effective_from),
        )

    def stats_usage(self, **kwargs: Any) -> StatsResult:
        return _do_usage(self._db_path, kwargs)

    def stats_winrate(self, **kwargs: Any) -> StatsResult:
        return _do_winrate(self._db_path, kwargs)

    def stats_wws(self, **kwargs: Any) -> StatsResult:
        return _do_wws(self._db_path, kwargs)

    def stats_card(self, name: str, **kwargs: Any) -> DrilldownResult:
        return _do_card(self._db_path, name, kwargs)

    def close(self) -> None:
        self._engine.dispose()


class JsonlBackend(CardDatabase):
    """JSONL 后端：读 dist/ 导出件（cards/sets/relations/legality + manifest）。"""

    def __init__(self, dist_dir: str | Path):
        dist_dir = Path(dist_dir)
        self._dist_dir = dist_dir
        self._stats_conn = None
        manifest = json.loads((dist_dir / "manifest.json").read_text(encoding="utf-8"))
        self._schema_version = manifest["schema_version"]
        self._cards = [
            CardSchema.model_validate(x)
            for x in self._read_jsonl(dist_dir / "cards.jsonl")
        ]
        self._cards_by_id = {c.card_id: c for c in self._cards}
        self._sets = [
            SetSchema.model_validate(x) for x in self._read_jsonl(dist_dir / "sets.jsonl")
        ]
        self._groups: dict[str, set[str]] = {}
        for r in self._read_jsonl(dist_dir / "relations.jsonl"):
            if r["kind"] == "cards_name_group":
                self._groups.setdefault(r["card_id"], set()).add(r["group_key"])
        legality = json.loads((dist_dir / "legality.json").read_text(encoding="utf-8"))
        self._snapshots = [
            SnapshotSchema.model_validate(x) for x in legality["data"]["snapshots"]
        ]
        self._errata = [
            ErrataRecord.model_validate(x) for x in legality["data"].get("errata", [])
        ]

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def get_card(self, card_id: str) -> CardSchema | None:
        return self._cards_by_id.get(card_id)

    def search_cards(
        self,
        *,
        name: str | None = None,
        marks: tuple[str, ...] | None = None,
        card_type: str | None = None,
        has_rule_box: bool | None = None,
        is_tera: bool | None = None,
        set_ids: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CardSchema]:
        filters = {
            "name": name, "marks": marks, "card_type": card_type,
            "has_rule_box": has_rule_box, "is_tera": is_tera, "set_ids": set_ids,
        }
        matched = [c for c in self._cards if _match(c, **filters)]
        return sorted(matched, key=lambda c: c.card_id)[offset:offset + limit]

    def get_set(self, set_id: str) -> SetSchema | None:
        return next((s for s in self._sets if s.set_id == set_id), None)

    def list_sets(self, era: str | None = None) -> list[SetSchema]:
        return sorted(
            (s for s in self._sets if era is None or s.era == era), key=lambda s: s.set_id
        )

    def legal_at(self, date: str | date, format: str) -> LegalityPool:
        d = _as_date(date)
        snapshot = select_snapshot(self._snapshots, format, d)
        active = [c for c in self._cards if c.status == "active"]
        return build_pool(active, self._groups, snapshot, format, d)

    def effective_text(self, card_id: str, date: str | date) -> EffectiveText:
        return resolve_text(
            card_id, self._cards_by_id, self._snapshots, self._errata, _as_date(date)
        )

    def validate_deck(
        self, deck: list[str], date: str | date, format: str
    ) -> DeckReport:
        return _do_validate_deck(
            self._cards, self._groups, self._snapshots, deck, _as_date(date), format
        )

    def snapshots(self, format: str | None = None) -> list[SnapshotSchema]:
        return sorted(
            (s for s in self._snapshots if format is None or s.format == format),
            key=lambda s: (s.format, s.effective_from),
        )

    def _stats_db(self):
        """懒构建统计内存库（FR-9.7：导出四件套 → 同名视图 → 同一 canonical SQL）。"""
        if self._stats_conn is None:
            self._stats_conn = build_stats_conn(self._dist_dir)
        return self._stats_conn

    def stats_usage(self, **kwargs: Any) -> StatsResult:
        return _do_usage(self._stats_db(), kwargs)

    def stats_winrate(self, **kwargs: Any) -> StatsResult:
        return _do_winrate(self._stats_db(), kwargs)

    def stats_wws(self, **kwargs: Any) -> StatsResult:
        return _do_wws(self._stats_db(), kwargs)

    def stats_card(self, name: str, **kwargs: Any) -> DrilldownResult:
        return _do_card(self._stats_db(), name, kwargs)

    def close(self) -> None:
        if self._stats_conn is not None:
            self._stats_conn.close()
            self._stats_conn = None


def open_db(db_path: str | Path) -> CardDatabase:
    """SQLite 后端：直接打开 ptcg-cn.db。"""
    return DbBackend(db_path)


def open_jsonl(dist_dir: str | Path) -> CardDatabase:
    """JSONL 后端：打开 dist/ 导出目录。"""
    return JsonlBackend(dist_dir)

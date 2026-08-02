"""导出七件套（task 010，PRD FR-7）。

dist/ 布局：manifest.json / cards.jsonl / sets.jsonl / relations.jsonl /
legality.json / ptcg-cn.db / checksums.sha256 / schema.md。
序列化一律经 Pydantic 导出模型（schemas/models.py），与 SDK 返回形状同源。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.orm import (
    Card,
    CardNameGroup,
    CardRelation,
    Deck,
    DeckAppearance,
    DeckCard,
    Errata,
    LegalitySnapshot,
    Meta,
    NameGroup,
    Set,
    Tournament,
)
from ptcgdb.schemas.models import Card as CardSchema
from ptcgdb.schemas.models import ErrataRecord as ErrataSchema
from ptcgdb.schemas.models import LegalitySnapshot as SnapshotSchema
from ptcgdb.schemas.models import Set as SetSchema
from ptcgdb.schemas.tournaments import AppearanceRecord, DeckCardRecord, DeckRecord
from ptcgdb.schemas.tournaments import TournamentRecord as TournamentSchema
from ptcgdb.stats.engine import SQL_DIR

EXPORT_FILES = [
    "manifest.json",
    "cards.jsonl",
    "sets.jsonl",
    "relations.jsonl",
    "legality.json",
    "tournaments.jsonl",
    "decks.jsonl",
    "deck_appearances.jsonl",
    "deck_cards.jsonl",
    "ptcg-cn.db",
    "checksums.sha256",
    "schema.md",
]


def _row_dict(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _dump(model, row) -> dict:
    return model.model_validate(_row_dict(row)).model_dump(mode="json")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_md() -> str:
    """字段字典：由 Pydantic 模型半自动生成（FR-7）。"""
    lines = [
        "# schema.md — 导出契约字段字典",
        "",
        "> 由 Pydantic 模型半自动生成（model_json_schema），请勿手改字段表。",
        "> 消费指引：JSONL 适合全量灌库/流式分析；规则语义（legal_at / effective_text）请走 SDK。",
        "",
    ]
    for model in (CardSchema, SetSchema, SnapshotSchema):
        schema = model.model_json_schema()
        lines.append(f"## {schema['title']}")
        lines.append("")
        lines.append("| 字段 | 类型 | 说明 |")
        lines.append("|---|---|---|")
        for name, prop in schema["properties"].items():
            type_ = prop.get("type") or prop.get("anyOf", [{}])[0].get("type", "?")
            desc = (prop.get("description") or "").replace("|", "\\|")
            lines.append(f"| `{name}` | {type_} | {desc} |")
        lines.append("")
    # FR-9.6/9.7：canonical SQL 附录（单一事实源原文，复制即得官方口径）
    lines += [
        "## 附录：统计 canonical SQL（FR-9.6 可复算性契约）",
        "",
        "以下 SQL 为 WUR / WR / WWS 三指标的唯一权威实现（`ptcgdb/stats/sql/`），",
        "命名参数：`:as_of` `:date_from` `:date_to` `:scope`（逗号串）`:division` `:tiers`",
        "（逗号串或 NULL）`:include_qual` `:include_team` `:usage_basis` `:layer` `:k_a` `:k_b`。",
        "复算示例：sqlite3 打开 dist/ptcg-cn.db，`.parameter set :as_of 2026-08-01` 设参后执行。",
        "",
    ]
    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        lines.append(f"### {sql_file.name}")
        lines.append("")
        lines.append("```sql")
        lines.append(sql_file.read_text(encoding="utf-8").rstrip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def export_all(db_path: Path, out_dir: Path) -> dict:
    """导出全部文件，返回 manifest dict。重跑幂等（覆盖写）。"""
    db_path, out_dir = Path(db_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        meta = {m.key: m.value for m in session.scalars(select(Meta))}
        cards = [_dump(CardSchema, c) for c in session.scalars(select(Card)).all()]
        sets = [_dump(SetSchema, s) for s in session.scalars(select(Set)).all()]
        snapshots = [
            _dump(SnapshotSchema, s) for s in session.scalars(select(LegalitySnapshot)).all()
        ]
        errata = [_dump(ErrataSchema, e) for e in session.scalars(select(Errata)).all()]
        relations: list[dict] = []
        for r in session.scalars(select(CardRelation)).all():
            relations.append({"kind": "card_relation", **_row_dict(r)})
        for g in session.scalars(select(NameGroup)).all():
            relations.append({"kind": "name_group", **_row_dict(g)})
        for m in session.scalars(select(CardNameGroup)).all():
            relations.append({"kind": "cards_name_group", **_row_dict(m)})
        # 赛事四件套（FR-7 追加，只加不删）；deck_cards 附 group_key 冗余列免联表
        tournaments = [
            _dump(TournamentSchema, t) for t in session.scalars(select(Tournament)).all()
        ]
        decks = [_dump(DeckRecord, d) for d in session.scalars(select(Deck)).all()]
        appearances = [
            _dump(AppearanceRecord, a)
            for a in session.scalars(select(DeckAppearance)).all()
        ]
        group_map = dict(
            session.execute(select(CardNameGroup.card_id, CardNameGroup.group_key)).all()
        )
        deck_cards = [
            DeckCardRecord.model_validate(
                {**_row_dict(r), "group_key": group_map.get(r.card_id)}
            ).model_dump(mode="json")
            for r in session.scalars(select(DeckCard)).all()
        ]
    engine.dispose()

    _write_jsonl(out_dir / "cards.jsonl", cards)
    _write_jsonl(out_dir / "sets.jsonl", sets)
    _write_jsonl(out_dir / "relations.jsonl", relations)
    _write_jsonl(out_dir / "tournaments.jsonl", tournaments)
    _write_jsonl(out_dir / "decks.jsonl", decks)
    _write_jsonl(out_dir / "deck_appearances.jsonl", appearances)
    _write_jsonl(out_dir / "deck_cards.jsonl", deck_cards)

    built_at = datetime.now(UTC).isoformat()
    schema_version = meta.get("schema_version", "1.0.0")
    legality = {
        "meta": {"schema_version": schema_version, "built_at": built_at},
        "data": {"snapshots": snapshots, "errata": errata},
    }
    (out_dir / "legality.json").write_text(
        json.dumps(legality, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 只读 DB 快照：WAL checkpoint 后复制（FR-7）
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except sqlite3.Error:
        pass
    shutil.copy2(db_path, out_dir / "ptcg-cn.db")

    (out_dir / "schema.md").write_text(_schema_md(), encoding="utf-8")

    manifest = {
        "version": meta.get("data_version", f"v{date.today():%Y%m%d}.0"),
        "schema_version": schema_version,
        "built_at": built_at,
        "db_sha256": _sha256(out_dir / "ptcg-cn.db"),
        "caliber": {  # FR-9.6 口径版本化：跨库比对复算结果先核对口径版本
            "name_group_rules_hash": meta.get("name_group_rules_hash"),
            "tournament_tiers_hash": meta.get("tournament_tiers_hash"),
        },
        "counts": {
            "cards": len(cards),
            "sets": len(sets),
            "snapshots": len(snapshots),
            "relations": len(relations),
            "tournaments": len(tournaments),
            "decks": len(decks),
            "deck_appearances": len(appearances),
            "deck_cards": len(deck_cards),
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = []
    for name in sorted(EXPORT_FILES):
        if name == "checksums.sha256":
            continue  # 不自签
        lines.append(f"{_sha256(out_dir / name)}  {name}")
    (out_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest

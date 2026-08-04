"""赛事 ingest：raw（mikmoe/tournaments + decks）→ tournaments/decks/deck_appearances/deck_cards。

task 027。口径（PRD FR-9.1/9.2/9.3/9.6 + §7.5 v1.10 续）：
- **decks = 卡组内容实体**（mik deckId 实测按内容去重，多名选手/多场赛事共用）；
  名次/积分/选手挂 deck_appearances 出战条目；同一 deckId 在 N 个名次出现 =
  1 行内容 + N 行出战条目。
- variant 归类 = 内容级属性，取自 deck/detail 的 variant 字段（parse_deck_variant）。
- stat_scope 派生：pokemon→pokemon；trainer 支援者→supporter、竞技场→stadium；
  物品/宝可梦道具/能量→other；未知 card_type/trainer_subtype 组合→other + 警告，不猜。
- card_id 必须能在 cards 表解析，否则置 NULL + raw_name 保真（不猜），入 unknown 清单。
- mapped_ratio = 已解析卡 count 合计 / 全卡组 count 合计（张数口径）；
  mapping_status：full ≥0.95 / partial (0,0.95) / unmapped =0。
- 60 张质量门（FR-9.6 ①）：count 合计 != 60 的卡组整组不入库（内容与出战条目
  都不落），记 blocked 报告。
- 幂等：tournaments/decks merge upsert；deck_cards 按 deck_id 先删后插；
  出战条目按 (deck_id, tournament_id) 先删后插。
- tier_coef 在解析层已从词表物化（FR-9.6 事实完整性），这里原样落库。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.tournaments import (
    VOCAB_DIR,
    load_division_map,
    load_tier_map,
    parse_deck_cards,
    parse_deck_variant,
    parse_rank_entry,
    parse_tournament,
)
from ptcgdb.orm import Card, Deck, DeckAppearance, DeckCard, Tournament
from ptcgdb.schemas import AppearanceRecord, TournamentRecord
from ptcgdb.scrapers.mikmoe import RAW_SUBDIR
from ptcgdb.scrapers.raw_store import read_raw

DECK_SIZE = 60  # 标准卡组 60 张（FR-9.6 数据质量门①；豁免名单本期为空）
FULL_THRESHOLD = 0.95  # mapping_status=full 的映射率阈值（FR-9.1）


@dataclass
class TournamentIngestResult:
    """赛事 ingest 报告：入库计数 + 质量门拦截 + 未解析卡 + 警告。"""

    tournaments: int = 0
    decks: int = 0  # 内容实体行
    appearances: int = 0  # 出战条目行
    deck_cards: int = 0
    blocked: list[dict[str, Any]] = field(default_factory=list)  # 60 张门 / raw 缺失
    unknown_cards: list[dict[str, Any]] = field(default_factory=list)  # card_id 未解析
    warnings: list[str] = field(default_factory=list)  # 未知 tier / subtype 等


def derive_stat_scope(card_type: str | None, trainer_subtype: str | None) -> str:
    """cards 行的 (card_type, trainer_subtype) → stat_scope（FR-9.3）。

    统计仅含宝可梦/支援者/竞技场；能量、物品、宝可梦道具为 other。
    未知组合 → other + warning（开放词表，不猜）。
    """
    if card_type == "pokemon":
        return "pokemon"
    if card_type == "trainer":
        if trainer_subtype == "支援者":
            return "supporter"
        if trainer_subtype == "竞技场":
            return "stadium"
        if trainer_subtype in ("物品", "宝可梦道具"):
            return "other"
    elif card_type == "energy":
        return "other"
    warnings.warn(
        f"未知 card_type/trainer_subtype 组合: ({card_type!r}, {trainer_subtype!r})，"
        "stat_scope 置 other",
        stacklevel=2,
    )
    return "other"


def _fetched_at(doc: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(doc["_meta"]["fetched_at"])


def _load_list_index(
    base: Path, result: TournamentIngestResult
) -> dict[str, tuple[dict[str, Any], str]]:
    """tournaments/list/{seriesId}/page-*.json → {tournamentId 字符串: (条目, seriesId)}。

    实测（2026-08-02 校准）list 条目主键字段为 `id`（不是 tournamentId），且不
    自带 seriesId——从 raw 目录名（采集上下文）取。
    """
    index: dict[str, tuple[dict[str, Any], str]] = {}
    list_dir = base / "list"
    if not list_dir.is_dir():
        return index
    for path in sorted(list_dir.glob("*/*.json")):
        doc = read_raw(path)
        if doc is None:
            result.warnings.append(f"raw 缺失或 hash 无效，跳过: {path}")
            continue
        series_id = path.parent.name
        for item in (doc.get("data") or {}).get("list") or []:
            raw_id = item.get("id") or item.get("tournamentId")
            if raw_id is not None:
                index[str(raw_id)] = (item, series_id)
    return index


def _load_appearance_records(
    base: Path,
    tournament_id: str,
    result: TournamentIngestResult,
) -> list[AppearanceRecord]:
    """tournaments/rank-individual/{tid}/page-*.json → 出战条目列表。"""
    parts = tournament_id.split(":", 1)
    if len(parts) != 2:
        result.warnings.append(f"tournament_id 格式无效（缺 source 前缀），跳过: {tournament_id}")
        return []
    rank_dir = base / "rank-individual" / parts[1]
    records: list[AppearanceRecord] = []
    if not rank_dir.is_dir():
        return records
    for path in sorted(rank_dir.glob("page-*.json")):
        doc = read_raw(path)
        if doc is None:
            result.warnings.append(f"raw 缺失或 hash 无效，跳过: {path}")
            continue
        for entry in (doc.get("data") or {}).get("list") or []:
            records.extend(
                parse_rank_entry(
                    entry, tournament_id=tournament_id, fetched_at=_fetched_at(doc)
                )
            )
    return records


def _mapping_status(ratio: float) -> str:
    if ratio >= FULL_THRESHOLD:
        return "full"
    if ratio > 0:
        return "partial"
    return "unmapped"


def ingest_tourneys(
    raw_dir: str | Path,
    db_path: str | Path,
    *,
    vocab_dir: Path | None = None,
) -> TournamentIngestResult:
    """扫 raw mikmoe/tournaments + decks 目录 → 三表入库。raw 层只读，重跑幂等。"""
    raw_dir = Path(raw_dir)
    db_path = Path(db_path)
    vocab_dir = vocab_dir or VOCAB_DIR
    tier_map = load_tier_map(vocab_dir)
    division_map = load_division_map(vocab_dir)
    result = TournamentIngestResult()

    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        # cards 解析索引：card_id → (card_type, trainer_subtype)
        card_index: dict[str, tuple[str, str | None]] = {
            r[0]: (r[1], r[2])
            for r in session.execute(
                select(Card.card_id, Card.card_type, Card.trainer_subtype)
            )
        }

    base = raw_dir / RAW_SUBDIR / "tournaments"
    decks_base = raw_dir / RAW_SUBDIR / "decks"
    detail_dir = base / "detail"
    if not detail_dir.is_dir():
        engine.dispose()
        return result

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        list_index = _load_list_index(base, result)
        for detail_path in sorted(detail_dir.glob("*.json")):
            doc = read_raw(detail_path)
            if doc is None:
                result.warnings.append(f"raw 缺失或 hash 无效，跳过: {detail_path}")
                continue
            detail = doc.get("data") or {}
            tid = detail_path.stem
            if tid in list_index:
                item, series_id = list_index[tid]
            else:
                item, series_id = {"id": tid, "name": detail.get("name")}, None
                result.warnings.append(
                    f"赛事 {tid} 缺 list 条目（type/division 等不可得），按 detail 最小入库"
                )
            record = parse_tournament(
                item,
                detail=detail,
                series_id=series_id,
                fetched_at=_fetched_at(doc),
                tier_map=tier_map,
                division_map=division_map,
            )
            appearance_records = _load_appearance_records(
                base, record.tournament_id, result
            )
            _ingest_one_tournament(
                engine, record, appearance_records, decks_base, card_index, result
            )
    result.warnings.extend(str(w.message) for w in caught)
    engine.dispose()
    return result


def _ingest_one_tournament(
    engine: Any,
    record: TournamentRecord,
    appearance_records: list[AppearanceRecord],
    decks_base: Path,
    card_index: dict[str, tuple[str, str | None]],
    result: TournamentIngestResult,
) -> None:
    with Session(engine) as session:
        session.merge(Tournament(**record.model_dump()))
        result.tournaments += 1
        # 按内容实体聚合出战条目：同一 deckId 可出现于多个名次（v1.10 续实测语义）
        by_deck: dict[str, list[AppearanceRecord]] = {}
        for app in appearance_records:
            by_deck.setdefault(app.deck_id, []).append(app)
        for deck_id, apps in by_deck.items():
            raw_deck_id = deck_id.split(":", 1)[1]
            doc = read_raw(decks_base / "detail" / f"{raw_deck_id}.json")
            if doc is None:
                result.blocked.append(
                    {
                        "deck_id": deck_id,
                        "total": None,
                        "reason": "deck/detail raw 缺失或 hash 无效",
                    }
                )
                continue
            data = doc.get("data") or {}
            cards = parse_deck_cards(deck_id, data)
            total = sum(c.count for c in cards)
            if total != DECK_SIZE:
                result.blocked.append(
                    {
                        "deck_id": deck_id,
                        "total": total,
                        "reason": f"deck_cards count 合计 {total} != {DECK_SIZE}（60 张质量门）",
                    }
                )
                continue
            # card_id 解析 + stat_scope 派生 + mapped_ratio 计算
            rows: list[DeckCard] = []
            seen_null: set[tuple[str, str]] = set()  # (deck_id, raw_name) 去重
            mapped_count = 0
            for card in cards:
                info = card_index.get(card.card_id) if card.card_id else None
                if info is None:
                    result.unknown_cards.append(
                        {
                            "deck_id": card.deck_id,
                            "card_id": card.card_id,
                            "raw_name": card.raw_name,
                            "count": card.count,
                        }
                    )
                    # card_id 为 NULL 时按 (deck_id, raw_name) 去重（PRD §7.5）
                    null_key = (card.deck_id, card.raw_name)
                    if null_key in seen_null:
                        result.warnings.append(
                            f"deck_cards 重复行已跳过: deck={card.deck_id} raw_name={card.raw_name}"
                        )
                        continue
                    seen_null.add(null_key)
                    rows.append(
                        DeckCard(
                            deck_id=card.deck_id,
                            card_id=None,
                            count=card.count,
                            raw_name=card.raw_name,
                            stat_scope="other",
                        )
                    )
                else:
                    mapped_count += card.count
                    rows.append(
                        DeckCard(
                            deck_id=card.deck_id,
                            card_id=card.card_id,
                            count=card.count,
                            raw_name=card.raw_name,
                            stat_scope=derive_stat_scope(*info),
                        )
                    )
            ratio = mapped_count / total
            archetype_id, archetype_name = parse_deck_variant(data)
            # 内容实体 upsert（deck_code/variant 来自 deck/detail，内容级）
            session.merge(
                Deck(
                    deck_id=deck_id,
                    archetype_id=archetype_id,
                    archetype_name=archetype_name,
                    deck_code=data.get("deckCode"),
                    mapping_status=_mapping_status(ratio),
                    mapped_ratio=ratio,
                    source="mik_moe",
                    fetched_at=apps[0].fetched_at,
                )
            )
            # 幂等：deck_cards 按 deck_id 先删后插
            session.execute(delete(DeckCard).where(DeckCard.deck_id == deck_id))
            session.add_all(rows)
            result.decks += 1
            result.deck_cards += len(rows)
            # 出战条目：按 (deck_id, tournament_id) 先删后插
            session.execute(
                delete(DeckAppearance).where(
                    DeckAppearance.deck_id == deck_id,
                    DeckAppearance.tournament_id == record.tournament_id,
                )
            )
            for app in apps:
                if app.rank is None:
                    result.warnings.append(f"出战条目缺 rank，跳过: {app.deck_id}")
                    continue
                session.add(DeckAppearance(**app.model_dump()))
                result.appearances += 1
        session.commit()

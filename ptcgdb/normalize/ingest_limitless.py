"""Limitless 赛事 ingest：raw（limitless/tournaments）→ 赛事四表（task 028 步骤 4）。

task 028 步骤 4（tournaments/decks/deck_appearances/deck_cards）。口径最大程度复用
mik 管线（ingest_tourneys.py，FR-9.1/9.2/9.3/9.6）：
- **decks = 卡组内容实体**：deck_id = limitless:{sha256(canonical_json(decklist))[:16]}
  （内容哈希，天然跨选手/跨赛事去重）；同一内容在同一赛事 N 个名次出现 =
  1 行内容 + N 行出战条目（多人同卡组照常多行）。
- decklist→简中映射走 normalize/limitless.map_decklist 映射链（ptcd 定位 →
  name_en exact match → env 优先/最新印刷裁决）；每条的决策 rule 计入
  mapping_rules 分布。同一卡组解析到相同 card_id 的多条目合并 count（两种印刷
  同名卡，记 warning）；未解析 card_id=None + raw_name 保真（(deck_id, raw_name)
  去重同 mik），不猜（FR-9.2）。
- stat_scope 照 mik 用 cards 表 card_type/trainer_subtype 派生（FR-9.3）；
  mapped_ratio 张数口径；mapping_status full≥0.95（FULL_THRESHOLD 复用）。
- 60 张质量门（FR-9.6①）：count 合计 != 60 整组拦截（内容与出战条目都不落）。
- env 推导（FR-9.1b）：derive_env("en", date)；未命中 → NULL + warning（记 monitor
  异常，不猜）；落库后以卡组最大赛制标记 ∈ env.allowed_marks 交叉校验，不符告警
  不拒收。映射裁决的 env 优先子集也用同一 env_marks。
- tier：classify_tournament(name, players) 重判 → 词表物化 tier_coef
  （FR-9.6 事实完整性）；未命中 → tier/tier_coef None + warning（不猜）。
- 幂等：tournaments/decks merge upsert；deck_cards 按 deck_id 先删后插；
  出战条目按 (deck_id, tournament_id) 先删后插（同 placing 碰撞后写覆盖）。
- pairings 解析（topcut_slots 等）留给后续步骤。
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.envs import SOURCE_REGION, EnvSegment, derive_env, load_calendar
from ptcgdb.normalize.ingest_tourneys import DECK_SIZE, _mapping_status, derive_stat_scope
from ptcgdb.normalize.limitless import (
    CnCandidate,
    PtcdSetMissingError,
    StandingEntry,
    load_ptcd_index,
    map_decklist_card,
    parse_standings_entry,
)
from ptcgdb.normalize.tournaments import VOCAB_DIR, load_tier_map
from ptcgdb.orm import Card, Deck, DeckAppearance, DeckCard, Set, Tournament
from ptcgdb.scrapers.limitless import (
    RAW_SUBDIR,
    SOURCE,
    TOURNAMENTS_DIR,
    classify_tournament,
)
from ptcgdb.scrapers.raw_store import canonical_json, read_raw

OFFICIAL_URL_TEMPLATE = "https://limitlesstcg.com/tournaments/{}"


@dataclass
class LimitlessIngestResult:
    """Limitless ingest 报告：入库计数 + 映射决策分布 + 质量门拦截 + 未解析卡 + 警告。"""

    tournaments: int = 0
    decks: int = 0  # 内容实体行
    appearances: int = 0  # 出战条目行
    deck_cards: int = 0
    mapping_rules: dict[str, int] = field(default_factory=dict)  # 映射决策 rule → 次数
    blocked: list[dict[str, Any]] = field(default_factory=list)  # 60 张门
    unknown_cards: list[dict[str, Any]] = field(default_factory=list)  # card_id 未解析
    warnings: list[str] = field(default_factory=list)


def make_deck_id(decklist_raw: Any) -> str:
    """内容哈希 deck_id：limitless:{sha256(canonical_json(decklist))[:16]}。

    同一套 60 张清单跨选手/跨赛事同一 deck_id（天然去重，mik deckId 同语义）。
    """
    digest = hashlib.sha256(canonical_json(decklist_raw).encode("utf-8")).hexdigest()
    return f"{SOURCE}:{digest[:16]}"


def _fetched_at(doc: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(doc["_meta"]["fetched_at"])


def _parse_day(raw: Any) -> date | None:
    """Limitless date 字段（UTC ISO，如 "2026-03-15T02:10:00.000Z"）→ 日期部分。"""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _load_list_index(base: Path, result: LimitlessIngestResult) -> dict[str, dict[str, Any]]:
    """tournaments/list/page-*.json → {tournament id: 清单条目}（name/players/date 来源）。"""
    index: dict[str, dict[str, Any]] = {}
    list_dir = base / "list"
    if not list_dir.is_dir():
        return index
    for path in sorted(list_dir.glob("page-*.json")):
        doc = read_raw(path)
        if doc is None:
            result.warnings.append(f"raw 缺失或 hash 无效，跳过: {path}")
            continue
        for item in doc.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                index[str(item["id"])] = item
    return index


def _build_cn_index(
    session: Session,
) -> tuple[dict[str, list[CnCandidate]], dict[str, tuple[str, str | None, str | None]]]:
    """CN 库索引：name_en → 候选卡列表（多印刷裁决用）；card_id → stat_scope/env 信息。"""
    cn_name_index: dict[str, list[CnCandidate]] = {}
    card_index: dict[str, tuple[str, str | None, str | None]] = {}
    rows = session.execute(
        select(
            Card.card_id, Card.name_en, Card.regulation_mark, Card.card_type,
            Card.trainer_subtype, Set.release_date,
        ).outerjoin(Set, Card.set_id == Set.set_id)
    )
    for card_id, name_en, mark, card_type, subtype, release in rows:
        card_index[card_id] = (card_type, subtype, mark)
        if name_en:
            cn_name_index.setdefault(name_en, []).append(
                CnCandidate(card_id, mark, release)
            )
    return cn_name_index, card_index


def ingest_limitless(
    raw_dir: str | Path,
    db_path: str | Path,
    *,
    vocab_dir: Path | None = None,
) -> LimitlessIngestResult:
    """扫 raw limitless/tournaments/standings → 四表入库。raw 层只读，重跑幂等。"""
    raw_dir = Path(raw_dir)
    db_path = Path(db_path)
    tier_map = load_tier_map(vocab_dir or VOCAB_DIR)
    env_calendar = load_calendar()
    result = LimitlessIngestResult()

    base = raw_dir / RAW_SUBDIR / TOURNAMENTS_DIR
    standings_dir = base / "standings"
    if not standings_dir.is_dir():
        return result
    try:
        _set_map, ptcd_index = load_ptcd_index(raw_dir)
    except PtcdSetMissingError as exc:
        result.warnings.append(f"{exc}；映射全部降级为 name_fallback")
        ptcd_index = {}

    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            cn_name_index, card_index = _build_cn_index(session)
        list_index = _load_list_index(base, result)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for path in sorted(standings_dir.glob("*.json")):
                doc = read_raw(path)
                if doc is None:
                    result.warnings.append(f"raw 缺失或 hash 无效，跳过: {path}")
                    continue
                _ingest_one_tournament(
                    engine, path.stem, doc, list_index, tier_map, env_calendar,
                    cn_name_index, card_index, ptcd_index, result,
                )
        result.warnings.extend(str(w.message) for w in caught)
    finally:
        engine.dispose()
    return result


def _ingest_one_tournament(
    engine: Any,
    tid: str,
    doc: dict[str, Any],
    list_index: dict[str, dict[str, Any]],
    tier_map: dict[str, tuple[str, float]],
    env_calendar: dict[str, Any],
    cn_name_index: dict[str, list[CnCandidate]],
    card_index: dict[str, tuple[str, str | None, str | None]],
    ptcd_index: dict[tuple[str, str], dict[str, Any]],
    result: LimitlessIngestResult,
) -> None:
    fetched_at = _fetched_at(doc)
    tournament_id = f"{SOURCE}:{tid}"
    item = list_index.get(tid)
    if item is None:
        # 缺 list 条目：照 mik 口径最小入库 + warning
        item = {"id": tid, "name": None, "players": None, "date": None}
        result.warnings.append(
            f"赛事 {tid} 缺 list 条目（name/players/date 不可得），按 standings 最小入库"
        )
    name = str(item.get("name") or "")
    players = item.get("players") if isinstance(item.get("players"), int) else None
    tier, classify_reason = classify_tournament(item.get("name"), players)
    if tier is None:
        result.warnings.append(
            f"赛事 tier 归类未命中（tier/tier_coef 置空）: {tournament_id} — {classify_reason}"
        )
    tier_coef = tier_map[tier][1] if tier is not None and tier in tier_map else None
    day = _parse_day(item.get("date"))
    # env 推导（FR-9.1b）：日期 ∩ EN 日历段；未命中 → NULL + 记异常，不猜
    env_segment = derive_env(SOURCE_REGION.get(SOURCE), day, env_calendar)
    if env_segment is None:
        result.warnings.append(
            f"赛事环境推导未命中（env=NULL，记 monitor 异常）: {tournament_id} date={day}"
        )
    env_marks = env_segment.allowed_marks if env_segment is not None else None

    standings = [
        parse_standings_entry(e) for e in (doc.get("data") or []) if isinstance(e, dict)
    ]
    with Session(engine) as session:
        session.merge(
            Tournament(
                tournament_id=tournament_id,
                source=SOURCE,
                series_id=None,
                name=name,
                tier=tier,
                tier_coef=tier_coef,
                division=None,
                date=day,
                location=None,
                participant_count=players,
                topcut_slots=None,  # pairings 落库步骤再补
                format="standard",
                regulation_mark=None,
                format_end=None,
                env=env_segment.env if env_segment is not None else None,
                is_qual=False,
                is_team=False,
                official_url=OFFICIAL_URL_TEMPLATE.format(tid),
                fetched_at=fetched_at,
            )
        )
        result.tournaments += 1
        # 按内容实体聚合出战条目：同一 decklist 可出现于多个名次（多人同卡组）
        by_deck: dict[str, list[StandingEntry]] = {}
        for entry in standings:
            if not entry.decklist_raw or not entry.decklist:
                result.warnings.append(
                    f"出战条目缺 decklist，跳过: {tournament_id} player={entry.player}"
                )
                continue
            by_deck.setdefault(make_deck_id(entry.decklist_raw), []).append(entry)
        for deck_id, entries in by_deck.items():
            _ingest_one_deck(
                session, deck_id, entries, tournament_id, fetched_at, env_segment,
                env_marks, cn_name_index, card_index, ptcd_index, result,
            )
        session.commit()


def _ingest_one_deck(
    session: Session,
    deck_id: str,
    entries: list[StandingEntry],
    tournament_id: str,
    fetched_at: datetime,
    env_segment: EnvSegment | None,
    env_marks: tuple[str, ...] | None,
    cn_name_index: dict[str, list[CnCandidate]],
    card_index: dict[str, tuple[str, str | None, str | None]],
    ptcd_index: dict[tuple[str, str], dict[str, Any]],
    result: LimitlessIngestResult,
) -> None:
    cards = entries[0].decklist  # 同 deck_id = 同内容（deck_id 哈希自原始 decklist）
    total = sum(c.count for c in cards)
    if total != DECK_SIZE:
        result.blocked.append(
            {
                "deck_id": deck_id,
                "total": total,
                "reason": f"deck_cards count 合计 {total} != {DECK_SIZE}（60 张质量门）",
            }
        )
        return
    # card_id 解析（决策 rule 计分布）；同 card_id 多条目合并 count（两种印刷同名卡）
    merged: dict[str, int] = {}
    raw_names: dict[str, str] = {}
    unmapped: list[tuple[str, int]] = []  # (raw_name, count)
    for card in cards:
        card_id, rule = map_decklist_card(
            card.set_code, card.number, card.name, ptcd_index, cn_name_index, env_marks
        )
        result.mapping_rules[rule] = result.mapping_rules.get(rule, 0) + 1
        if card_id is None:
            unmapped.append((card.name, card.count))
            continue
        if card_id in merged:
            result.warnings.append(
                f"同卡组多条目解析到相同 card_id，合并 count: deck={deck_id} card_id={card_id}"
            )
        merged[card_id] = merged.get(card_id, 0) + card.count
        raw_names.setdefault(card_id, card.name)
    # 落 deck_cards 行 + mapped_ratio + env 交叉校验材料
    rows: list[DeckCard] = []
    mapped_count = 0
    mapped_marks: list[str] = []
    for card_id in sorted(merged):
        info = card_index.get(card_id)
        if info is None:
            # name_en 候选与 card_index 同源构建，理论不可达（防御性兜底）
            unmapped.append((raw_names[card_id], merged[card_id]))
            continue
        mapped_count += merged[card_id]
        if info[2]:
            mapped_marks.append(info[2])
        rows.append(
            DeckCard(
                deck_id=deck_id,
                card_id=card_id,
                count=merged[card_id],
                raw_name=raw_names[card_id],
                stat_scope=derive_stat_scope(info[0], info[1]),
            )
        )
    seen_null: set[str] = set()  # card_id 为 NULL 时按 (deck_id, raw_name) 去重（PRD §7.5）
    for raw_name, count in unmapped:
        result.unknown_cards.append(
            {"deck_id": deck_id, "card_id": None, "raw_name": raw_name, "count": count}
        )
        if raw_name in seen_null:
            result.warnings.append(
                f"deck_cards 重复行已跳过: deck={deck_id} raw_name={raw_name}"
            )
            continue
        seen_null.add(raw_name)
        rows.append(
            DeckCard(
                deck_id=deck_id, card_id=None, count=count,
                raw_name=raw_name, stat_scope="other",
            )
        )
    ratio = mapped_count / total
    # env 交叉校验（FR-9.1b）：卡组最大赛制标记 ∈ allowed_marks，不符告警不拒收
    if env_segment is not None and mapped_marks:
        max_mark = max(mapped_marks)
        if max_mark not in env_segment.allowed_marks:
            result.warnings.append(
                f"env 交叉校验告警: {deck_id} 最大赛制标记 {max_mark} "
                f"不在 env={env_segment.env} 内（赛事 {tournament_id}），不拒收"
            )
    first = entries[0]
    session.merge(
        Deck(
            deck_id=deck_id,
            archetype_id=first.archetype_id,
            archetype_name=first.archetype_name,
            deck_code=None,
            mapping_status=_mapping_status(ratio),
            mapped_ratio=ratio,
            source=SOURCE,
            fetched_at=fetched_at,
        )
    )
    # 幂等：deck_cards 按 deck_id 先删后插
    session.execute(delete(DeckCard).where(DeckCard.deck_id == deck_id))
    session.add_all(rows)
    result.decks += 1
    result.deck_cards += len(rows)
    # 出战条目：按 (deck_id, tournament_id) 先删后插；同 placing 碰撞后写覆盖
    session.execute(
        delete(DeckAppearance).where(
            DeckAppearance.deck_id == deck_id,
            DeckAppearance.tournament_id == tournament_id,
        )
    )
    by_rank: dict[int, StandingEntry] = {}
    for entry in entries:
        if entry.placing is None:
            result.warnings.append(
                f"出战条目缺 placing，跳过: {deck_id} player={entry.player}"
            )
            continue
        by_rank[entry.placing] = entry  # 同 placing 碰撞：后写覆盖
    for rank in sorted(by_rank):
        entry = by_rank[rank]
        session.add(
            DeckAppearance(
                deck_id=deck_id,
                tournament_id=tournament_id,
                rank=rank,
                points=None,
                player_ref=entry.player,  # Limitless 用户名（隐私最小化，同 mik 口径）
                record_wins=entry.record_wins,
                record_losses=entry.record_losses,
                record_ties=entry.record_ties,
                source=SOURCE,
                fetched_at=fetched_at,
            )
        )
        result.appearances += 1

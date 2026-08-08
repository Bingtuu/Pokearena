"""Limitless 主站 HTML 收录 ingest：raw（limitless_site/）→ 赛事四表（task 028 扩展）。

与 API 通道（ingest_limitless.py）并列的双通道之一：DB source="limitless_site"
（tournament_id = limitless_site:{数字id}，内容与 API 通道各自独立不合并）。
口径照 API 通道（60 张质量门 / FULL_THRESHOLD=0.95 / map_decklist_card 映射链 /
stat_scope 派生 / env 推导 + 交叉校验告警不拒收 / 幂等 merge upsert + 先删后插），
主站特有口径：

- **名次截断**（FR-9.1a ② 与主站全收录实测的调和）：standings 是全交表选手
  （实测 NAIC 675 行），入库只收上位——SITE_CUT_LIMITS：regional/international/
  special → placing ≤ 32；league_cup → ≤ 8。这是与 CN mik top64 上位口径同构的
  截断代理；真实 Top Cut 规模源不暴露。截断外的不入库，截断数记入报告 truncated；
  tier 未知 → 不截断 + warning（不猜）。
- **topcut_slots = 截断后实际入库名次数**（如实物化；60 张门拦截的名次不计）。
- **record 三列 = NULL**（主站收录无比分，不猜）；pairings 无主站数据（不动
  pairings 表，也不做 phase=2 反推）。
- 赛事信息从 index/{season}/page-*.json 按 tournament_id 反查（name/players/date/
  country）；缺失 → warning + 最小入库（同 API 缺 list 口径）。
- decks：archetype_name = 卡组页标题解析的 archetype 字段；archetype_id = standings
  行源侧归类 id（/decks/{id}，可缺）；deck_id = limitless_site:{60 张内容哈希[:16]}
  ——同一内容哈希天然去重（多人同表 = 1 内容行 + N 出战行，同 mik/同 API 口径）。
- 卡组快照缺失（decks/list/{id}.json 不在或 hash 无效）→ blocked 记录，该表
  出战条目不落。
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.envs import SOURCE_REGION, EnvSegment, derive_env, load_calendar
from ptcgdb.normalize.ingest_limitless import _build_cn_index, _fetched_at
from ptcgdb.normalize.ingest_tourneys import DECK_SIZE, _mapping_status, derive_stat_scope
from ptcgdb.normalize.limitless import (
    CnCandidate,
    PtcdSetMissingError,
    load_ptcd_index,
    map_decklist_card,
)
from ptcgdb.normalize.tournaments import VOCAB_DIR, load_tier_map
from ptcgdb.orm import Deck, DeckAppearance, DeckCard, Tournament
from ptcgdb.scrapers.limitless_site import (
    RAW_SUBDIR,
    SOURCE,
    TOURNAMENTS_DIR,
    classify_site_tournament,
)
from ptcgdb.scrapers.raw_store import canonical_json, read_raw

OFFICIAL_URL_TEMPLATE = "https://limitlesstcg.com/tournaments/{}"

# 名次截断（FR-9.1a ② 调和）：与 CN mik top64 上位口径同构的截断代理；
# 真实 Top Cut 规模源不暴露。regional/international/special → Top 32；league_cup → Top 8。
SITE_CUT_LIMITS: dict[str, int] = {
    "regional": 32,
    "international": 32,
    "special": 32,
    "league_cup": 8,
}


@dataclass
class LimitlessSiteIngestResult:
    """主站收录 ingest 报告：入库计数 + 截断数 + 映射决策分布 + 质量门拦截 + 警告。"""

    tournaments: int = 0
    decks: int = 0  # 内容实体行
    appearances: int = 0  # 出战条目行
    deck_cards: int = 0
    truncated: int = 0  # 名次截断丢掉的出战条数（placing > cut）
    cut_limits: dict[str, int] = field(default_factory=lambda: dict(SITE_CUT_LIMITS))
    mapping_rules: dict[str, int] = field(default_factory=dict)  # 映射决策 rule → 次数
    blocked: list[dict[str, Any]] = field(default_factory=list)  # 60 张门 / 快照缺失
    unknown_cards: list[dict[str, Any]] = field(default_factory=list)  # card_id 未解析
    warnings: list[str] = field(default_factory=list)


def make_deck_id(cards: Any) -> str:
    """内容哈希 deck_id：limitless_site:{sha256(canonical_json(cards))[:16]}。

    同一套 60 张清单跨选手/跨赛事同一 deck_id（天然去重，mik deckId 同语义）。
    """
    digest = hashlib.sha256(canonical_json(cards).encode("utf-8")).hexdigest()
    return f"{SOURCE}:{digest[:16]}"


def _parse_day(raw: Any) -> date | None:
    """索引 date 字段（ISO "2026-06-10"，采集层已归一）→ date。"""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _load_index_entries(
    base: Path, result: LimitlessSiteIngestResult
) -> dict[str, dict[str, Any]]:
    """tournaments/index/{season}/page-*.json → {tournament_id: 索引条目}。"""
    index: dict[str, dict[str, Any]] = {}
    index_dir = base / "index"
    if not index_dir.is_dir():
        return index
    for path in sorted(index_dir.glob("*/page-*.json")):
        doc = read_raw(path)
        if doc is None:
            result.warnings.append(f"raw 缺失或 hash 无效，跳过: {path}")
            continue
        for item in doc.get("entries") or []:
            if isinstance(item, dict) and item.get("tournament_id"):
                index[str(item["tournament_id"])] = item
    return index


def ingest_limitless_site(
    raw_dir: str | Path,
    db_path: str | Path,
    *,
    vocab_dir: Path | None = None,
) -> LimitlessSiteIngestResult:
    """扫 raw limitless_site/tournaments/standings → 四表入库。raw 层只读，重跑幂等。"""
    raw_dir = Path(raw_dir)
    db_path = Path(db_path)
    tier_map = load_tier_map(vocab_dir or VOCAB_DIR)
    env_calendar = load_calendar()
    result = LimitlessSiteIngestResult()

    base = raw_dir / RAW_SUBDIR / TOURNAMENTS_DIR
    standings_dir = base / "standings"
    if not standings_dir.is_dir():
        return result
    decklist_base = raw_dir / RAW_SUBDIR / "decks" / "list"
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
        index_entries = _load_index_entries(base, result)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for path in sorted(standings_dir.glob("*.json")):
                doc = read_raw(path)
                if doc is None:
                    result.warnings.append(f"raw 缺失或 hash 无效，跳过: {path}")
                    continue
                _ingest_one_tournament(
                    engine, path.stem, doc, decklist_base, index_entries, tier_map,
                    env_calendar, cn_name_index, card_index, ptcd_index, result,
                )
        result.warnings.extend(str(w.message) for w in caught)
    finally:
        engine.dispose()
    return result


def _ingest_one_tournament(
    engine: Any,
    tid: str,
    doc: dict[str, Any],
    decklist_base: Path,
    index_entries: dict[str, dict[str, Any]],
    tier_map: dict[str, tuple[str, float]],
    env_calendar: dict[str, Any],
    cn_name_index: dict[str, list[CnCandidate]],
    card_index: dict[str, tuple[str, str | None, str | None]],
    ptcd_index: dict[tuple[str, str], dict[str, Any]],
    result: LimitlessSiteIngestResult,
) -> None:
    fetched_at = _fetched_at(doc)
    tournament_id = f"{SOURCE}:{tid}"
    item = index_entries.get(tid)
    if item is None:
        # 缺索引条目：照 API/mik 口径最小入库 + warning
        item = {"tournament_id": tid, "name": None, "players": None, "date": None}
        result.warnings.append(
            f"赛事 {tid} 缺索引条目（name/players/date 不可得），按 standings 最小入库"
        )
    name = str(item.get("name") or doc.get("name") or "")
    players = item.get("players") if isinstance(item.get("players"), int) else None
    tier, classify_reason = classify_site_tournament(
        item.get("name") or doc.get("name"), players, item.get("country")
    )
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

    # 名次截断（FR-9.1a ② 调和）：tier 未知不截断 + warning（不猜）
    cut = SITE_CUT_LIMITS.get(tier) if tier is not None else None
    if tier is not None and cut is None:
        result.warnings.append(
            f"赛事 tier={tier} 无截断档位配置（不截断，不猜）: {tournament_id}"
        )
    standings = [r for r in (doc.get("standings") or []) if isinstance(r, dict)]
    kept: list[dict[str, Any]] = []
    for row in standings:
        placing = row.get("placing")
        if not isinstance(placing, int):
            result.warnings.append(
                f"出战条目缺 placing，跳过: {tournament_id} player={row.get('player')}"
            )
            continue
        if cut is not None and placing > cut:
            result.truncated += 1  # 截断外不入库（计数进报告）
            continue
        kept.append(row)

    with Session(engine) as session:
        session.merge(
            Tournament(
                tournament_id=tournament_id,
                source=SOURCE,
                series_id=None,
                name=name,
                tier=tier,
                tier_coef=tier_coef,
                division=None,  # 主站收录无组别信息（不猜）
                date=day,
                location=None,
                participant_count=players,
                topcut_slots=None,  # 本函数尾部 = 截断后实际入库名次数（物化）
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
        # 按卡组快照聚合出战条目：同一 decklist_id 可出现于多个名次（多人同表）；
        # 再按内容哈希 deck_id 二次聚合（不同 decklist_id 同内容也合并，同 API 口径）
        by_decklist: dict[str, list[dict[str, Any]]] = {}
        for row in kept:
            did = row.get("decklist_id")
            if not isinstance(did, str) or not did:
                result.warnings.append(
                    f"出战条目缺 decklist_id，跳过: {tournament_id} player={row.get('player')}"
                )
                continue
            by_decklist.setdefault(did, []).append(row)
        deck_docs: dict[str, dict[str, Any]] = {}  # decklist_id → 快照文档
        by_deck: dict[str, list[dict[str, Any]]] = {}  # deck_id → 出战行
        deck_representative: dict[str, str] = {}  # deck_id → 代表 decklist_id
        for did, rows in by_decklist.items():
            deck_doc = read_raw(decklist_base / f"{did}.json")
            if deck_doc is None:
                result.blocked.append(
                    {
                        "decklist_id": did,
                        "tournament_id": tournament_id,
                        "reason": "卡组快照缺失或 hash 无效（decks/list 未抓到），整组拦截",
                    }
                )
                continue
            cards_raw = [c for c in (deck_doc.get("cards") or []) if isinstance(c, dict)]
            deck_id = make_deck_id(cards_raw)
            deck_docs[did] = deck_doc
            deck_representative.setdefault(deck_id, did)
            by_deck.setdefault(deck_id, []).extend(rows)
        ingested_ranks = 0
        for deck_id, rows in by_deck.items():
            did = deck_representative[deck_id]
            ingested_ranks += _ingest_one_deck(
                session, deck_id, did, deck_docs[did], rows, tournament_id, env_segment,
                env_marks, cn_name_index, card_index, ptcd_index, result,
            )
        # topcut_slots 物化 = 截断后实际入库名次数（60 张门拦截不计）
        tournament = session.get(Tournament, tournament_id)
        if tournament is not None:
            tournament.topcut_slots = ingested_ranks
        session.commit()


def _ingest_one_deck(
    session: Session,
    deck_id: str,
    decklist_id: str,
    deck_doc: dict[str, Any],
    rows: list[dict[str, Any]],
    tournament_id: str,
    env_segment: EnvSegment | None,
    env_marks: tuple[str, ...] | None,
    cn_name_index: dict[str, list[CnCandidate]],
    card_index: dict[str, tuple[str, str | None, str | None]],
    ptcd_index: dict[tuple[str, str], dict[str, Any]],
    result: LimitlessSiteIngestResult,
) -> int:
    """单套卡组（内容实体 + 出战条目）入库，返回实际入库名次数。"""
    fetched_at = _fetched_at(deck_doc)
    cards_raw = [c for c in (deck_doc.get("cards") or []) if isinstance(c, dict)]
    # 卡条目归一：缺 count/name 的条目无法保真跳过（60 张门会拦截整体）
    cards: list[tuple[int, str | None, str | None, str]] = []
    for c in cards_raw:
        count, name = c.get("count"), c.get("name")
        if not isinstance(count, int) or not name:
            continue
        cards.append(
            (count, c.get("set"), str(c["number"]) if c.get("number") is not None else None,
             str(name))
        )
    total = sum(count for count, _set, _num, _name in cards)
    if total != DECK_SIZE:
        result.blocked.append(
            {
                "deck_id": deck_id,
                "decklist_id": decklist_id,
                "total": total,
                "reason": f"deck_cards count 合计 {total} != {DECK_SIZE}（60 张质量门）",
            }
        )
        return 0
    # card_id 解析（决策 rule 计分布）；同 card_id 多条目合并 count（两种印刷同名卡）
    merged: dict[str, int] = {}
    raw_names: dict[str, str] = {}
    unmapped: list[tuple[str, int]] = []  # (raw_name, count)
    for count, set_code, number, name in cards:
        card_id, rule = map_decklist_card(
            set_code, number, name, ptcd_index, cn_name_index, env_marks
        )
        result.mapping_rules[rule] = result.mapping_rules.get(rule, 0) + 1
        if card_id is None:
            unmapped.append((name, count))
            continue
        if card_id in merged:
            result.warnings.append(
                f"同卡组多条目解析到相同 card_id，合并 count: deck={deck_id} card_id={card_id}"
            )
        merged[card_id] = merged.get(card_id, 0) + count
        raw_names.setdefault(card_id, name)
    # 落 deck_cards 行 + mapped_ratio + env 交叉校验材料
    deck_rows: list[DeckCard] = []
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
        deck_rows.append(
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
        deck_rows.append(
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
    session.merge(
        Deck(
            deck_id=deck_id,
            archetype_id=rows[0].get("archetype_id"),  # standings 行源侧归类 id（可缺）
            archetype_name=deck_doc.get("archetype"),  # 卡组页标题解析的 archetype
            deck_code=None,
            mapping_status=_mapping_status(ratio),
            mapped_ratio=ratio,
            source=SOURCE,
            fetched_at=fetched_at,
        )
    )
    # 幂等：deck_cards 按 deck_id 先删后插
    session.execute(delete(DeckCard).where(DeckCard.deck_id == deck_id))
    session.add_all(deck_rows)
    result.decks += 1
    result.deck_cards += len(deck_rows)
    # 出战条目：按 (deck_id, tournament_id) 先删后插；同 placing 碰撞后写覆盖
    session.execute(
        delete(DeckAppearance).where(
            DeckAppearance.deck_id == deck_id,
            DeckAppearance.tournament_id == tournament_id,
        )
    )
    by_rank: dict[int, dict[str, Any]] = {}
    for row in rows:
        by_rank[row["placing"]] = row  # 同 placing 碰撞：后写覆盖
    for rank in sorted(by_rank):
        row = by_rank[rank]
        session.add(
            DeckAppearance(
                deck_id=deck_id,
                tournament_id=tournament_id,
                rank=rank,
                points=None,
                player_ref=row.get("player"),  # 主站公开选手名
                record_wins=None,  # 主站收录无比分（不猜）
                record_losses=None,
                record_ties=None,
                source=SOURCE,
                fetched_at=fetched_at,
            )
        )
        result.appearances += 1
    return len(by_rank)

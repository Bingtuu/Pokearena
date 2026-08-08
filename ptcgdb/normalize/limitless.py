"""Limitless 解析 + decklist→简中映射层（task 028 步骤 3，FR-9.1a/9.2）。

链路：Limitless standings decklist 卡条目（PTCGO set code + number + 英文名）
→ ptcd（pokemon-tcg-data）(set, number) 精确定位拿到规范英文名
→ CN 库 cards.name_en exact match → 多候选裁决（env 优先 → 最新印刷 → 字典序兜底）。

口径要点：
- 同名多印刷是常态（Dipplin 9 张、Boss's Orders 38 张），裁决规则全链确定性：
  regulation_mark ∈ env.allowed_marks 的子集优先，子集内 set release_date 最新者；
  env 为空或子集为空 → 全体候选里最新者；release_date 并列 → card_id 字典序最小者
  （与 effective_text 口径一致）。
- ptcd 定位失败 → 回退直接用 decklist 自带 name（rule 含 "name_fallback"）；
  基本能量：ptcd 用 "Basic Psychic Energy"、CN name_en 用 "Psychic Energy"（SV 代起
  ptcd 加 Basic 前缀）→ 0 命中且名以 "Basic " 开头时去前缀重试
  （rule 含 "basic_energy_alias"）。
- 0 候选 → (None, "unmapped")，不猜（FR-9.2）。
- raw 层只读；pairings 解析（parse_pairings_entry）→ pairings 表 + topcut_slots
  反推（PRD v1.14 §7.5），winner 空串归一 None（平局/未报，不猜）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, NamedTuple

from ptcgdb.schemas.tournaments import PairingRecord

PTCD_SUBDIR = "pokemon-tcg-data"

# decklist 三节（顺序即落盘遍历顺序）
DECKLIST_SECTIONS = ("pokemon", "trainer", "energy")

# 基本能量别名：ptcd SV 代起加 "Basic " 前缀，CN name_en 无此前缀
BASIC_ENERGY_PREFIX = "Basic "


class PtcdSetMissingError(RuntimeError):
    """ptcd raw 缺失（sets-en.json 不在），映射退化为全 name_fallback。"""


class CnCandidate(NamedTuple):
    """CN 库 name_en 候选卡（多印刷裁决用）。"""

    card_id: str
    regulation_mark: str | None
    release_date: date | None  # 所属 set 的 release_date


@dataclass(frozen=True)
class DecklistCard:
    """decklist 卡条目（PTCGO set code + number + 英文名）。"""

    count: int
    set_code: str | None
    number: str | None
    name: str


@dataclass(frozen=True)
class StandingEntry:
    """standings 条目解析形状：placing/record 三列/player/deck archetype/decklist。"""

    placing: int | None
    record_wins: int | None
    record_losses: int | None
    record_ties: int | None
    player: str | None  # Limitless 用户名
    archetype_id: str | None  # deck.id（源侧归类 id）
    archetype_name: str | None  # deck.name（源侧归类名）
    decklist: tuple[DecklistCard, ...]
    decklist_raw: Any  # 原始 decklist dict（内容哈希用，保真）


def _to_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _array(doc: Any, *keys: str) -> list[Any]:
    """容忍 raw 文档的多种顶层形态：裸数组 / {"sets": [...]} / {"data": [...]} 等。"""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        for key in keys:
            if isinstance(doc.get(key), list):
                return doc[key]
    return []


def parse_standings_entry(entry: dict[str, Any]) -> StandingEntry:
    """Limitless standings 条目 → StandingEntry（frozen）。

    record{wins,losses,ties} 为 A 层逐局战绩（mik 没有）；deck{id,name} 为源侧
    archetype 归类；decklist 缺节/缺条目按空处理（60 张质量门在入库段拦截）。
    """
    record = entry.get("record") or {}
    deck = entry.get("deck") or {}
    decklist_raw = entry.get("decklist") or {}
    cards: list[DecklistCard] = []
    for section in DECKLIST_SECTIONS:
        for item in decklist_raw.get(section) or []:
            name = item.get("name")
            count = _to_int(item.get("count"))
            if not name or count is None:
                continue  # 缺名/缺数量的条目无法保真，跳过（60 张门会拦截整体）
            cards.append(
                DecklistCard(
                    count=count,
                    set_code=item.get("set"),
                    number=str(item["number"]) if item.get("number") is not None else None,
                    name=str(name),
                )
            )
    archetype_id = deck.get("id")
    return StandingEntry(
        placing=_to_int(entry.get("placing")),
        record_wins=_to_int(record.get("wins")),
        record_losses=_to_int(record.get("losses")),
        record_ties=_to_int(record.get("ties")),
        player=entry.get("player"),
        archetype_id=str(archetype_id) if archetype_id is not None else None,
        archetype_name=deck.get("name"),
        decklist=tuple(cards),
        decklist_raw=entry.get("decklist"),
    )


def parse_pairings_entry(
    entry: dict[str, Any], *, tournament_id: str, fetched_at: datetime | None
) -> PairingRecord | None:
    """Limitless pairings 条目 → PairingRecord（task 028，PRD §7.5 v1.14）。

    原始形态 {"round":1,"phase":1,"table":1,"winner":"...","player1":"...","player2":"..."}：
    - table → table_no（避 SQLite 关键字）；phase 1=瑞士轮 2=淘汰赛；
    - winner 空串/None → None（平局或未报，不猜）；
    - round/phase/table 不可解析或 player1/player2 缺失 → None（调用方记 warning
      跳过，不猜）。
    """
    round_ = _to_int(entry.get("round"))
    phase = _to_int(entry.get("phase"))
    table_no = _to_int(entry.get("table"))
    player1 = entry.get("player1")
    player2 = entry.get("player2")
    if round_ is None or phase is None or table_no is None or not player1 or not player2:
        return None
    winner = entry.get("winner") or None  # 空串 = 平局/未报 → None（不猜）
    return PairingRecord(
        tournament_id=tournament_id,
        phase=phase,
        round=round_,
        table_no=table_no,
        player1=str(player1),
        player2=str(player2),
        winner=str(winner) if winner else None,
        fetched_at=fetched_at,
    )


# ---- ptcd 索引（EN 卡静态源，PTCGO set code + number → 规范英文名）----
def load_ptcd_index(
    raw_dir: str | Path,
) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    """加载 ptcd raw → (set_map, card_index)。raw 层只读。

    set_map = ptcgoCode → ptcd set id（sets-en.json）；
    card_index = {(ptcgoCode, number): ptcd 卡条目}（遍历 cards-en/*.json，经
    set_map 反查所属 ptcgoCode；编号含前导零变体键，同号冲突保留先见者）。
    sets-en.json 缺失 → PtcdSetMissingError（调用方降级为全 name_fallback）。
    """
    base = Path(raw_dir) / PTCD_SUBDIR
    sets_path = base / "sets-en.json"
    if not sets_path.is_file():
        raise PtcdSetMissingError(f"ptcd sets-en.json 缺失: {sets_path}")
    doc = json.loads(sets_path.read_text(encoding="utf-8"))
    set_map = {
        s["ptcgoCode"]: s["id"] for s in _array(doc, "sets", "data") if s.get("ptcgoCode")
    }
    code_of = {set_id: code for code, set_id in set_map.items()}  # 反查（先见者胜）
    card_index: dict[tuple[str, str], dict[str, Any]] = {}
    cards_dir = base / "cards-en"
    if cards_dir.is_dir():
        for path in sorted(cards_dir.glob("*.json")):
            code = code_of.get(path.stem)
            if code is None:
                continue  # 无 ptcgoCode 的系列对 Limitless 映射无用
            doc = json.loads(path.read_text(encoding="utf-8"))
            for card in _array(doc, "cards", "data"):
                num = str(card.get("number") or "")
                for variant in {num, num.lstrip("0") or "0", num.zfill(3)}:
                    card_index.setdefault((code, variant), card)
    return set_map, card_index


def _ptcd_lookup(
    card_index: dict[tuple[str, str], dict[str, Any]],
    set_code: str | None,
    number: str | None,
) -> dict[str, Any] | None:
    """(PTCGO set code, number) → ptcd 卡条目（编号含前导零变体）。"""
    if not set_code or not number:
        return None
    for variant in {number, number.lstrip("0") or "0", number.zfill(3)}:
        hit = card_index.get((set_code, variant))
        if hit is not None:
            return hit
    return None


# ---- decklist 卡 → CN card_id 映射链 ----


def map_decklist_card(
    set_code: str | None,
    number: str | None,
    name: str,
    ptcd_index: dict[tuple[str, str], dict[str, Any]],
    cn_name_index: dict[str, list[CnCandidate]],
    env_marks: tuple[str, ...] | None,
) -> tuple[str | None, str]:
    """单卡映射：返回 (card_id | None, rule)。rule 记录决策链（mapping_rules 计数用）。

    决策链：
    1. ptcd (set, number) 精确定位 → 规范英文名（rule 起点 "ptcd"）；
       定位失败回退 decklist 自带 name（"name_fallback"）；
    2. 英文名 exact match CN name_en；0 命中且以 "Basic " 开头 → 去前缀重试
       （"basic_energy_alias"）；
    3. 候选裁决：唯一 → "unique"；多候选 → env 子集优先（"env"）+ 最新印刷
       （"latest"）；release_date 并列 → card_id 字典序最小者（全链确定性）；
    4. 0 候选 → (None, "unmapped")。
    """
    stage = "ptcd"
    en_name = name
    hit = _ptcd_lookup(ptcd_index, set_code, number)
    if hit is not None and hit.get("name"):
        en_name = str(hit["name"])
    elif hit is None:
        stage = "name_fallback"
    candidates = cn_name_index.get(en_name) or []
    rules = [stage]
    if not candidates and en_name.startswith(BASIC_ENERGY_PREFIX):
        # 基本能量别名：ptcd "Basic Psychic Energy" → CN "Psychic Energy"
        stripped = en_name[len(BASIC_ENERGY_PREFIX):]
        candidates = cn_name_index.get(stripped) or []
        if candidates:
            rules.append("basic_energy_alias")
    if not candidates:
        return None, "unmapped"
    if len(candidates) == 1:
        return candidates[0].card_id, "+".join([*rules, "unique"])
    pool = candidates
    if env_marks:
        subset = [c for c in candidates if c.regulation_mark in env_marks]
        if subset:
            pool = subset
            rules.append("env")
    # 最新印刷（release_date 缺失视为最旧）+ card_id 字典序兜底（全链确定性）
    best = min(pool, key=_recency_key)
    rules.append("latest")
    return best.card_id, "+".join(rules)


def _recency_key(candidate: CnCandidate) -> tuple[int, str]:
    ordinal = candidate.release_date.toordinal() if candidate.release_date else 0
    return (-ordinal, candidate.card_id)

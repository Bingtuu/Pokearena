"""赛事解析层：mik 赛事 raw 响应 → frozen schemas（PRD §7.5 / FR-9.6，task 027）。

口径要点：
- tournament_id / deck_id = `mik_moe:{源侧id}`（{source}:{源侧id}，防跨源碰撞）；
- card_id = `{setCode}-{cardIndex}` 原样拼接（不补零；基本能量 cardIndex 为字母码）；
- tier/division 经词表（config/vocabularies/tournament_tiers.yml）归一，匹配大小写
  不敏感；未知 tier → tier 保留源侧原值 + tier_coef=None + warning，**不猜**；
- players[].pinCode → player_ref（只存编号，隐私最小化，FR-9.5）；
- mapping_status / stat_scope 解析段只占位，由入库段按映射率与 cards 表重算。
"""

from __future__ import annotations

import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from ptcgdb.schemas import AppearanceRecord, DeckCardRecord, TournamentRecord

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
VOCAB_DIR = CONFIG_DIR / "vocabularies"

SOURCE = "mik_moe"


def make_tournament_id(raw_id: Any) -> str:
    """{source}:{源侧id} 口径（FR-9.6 防跨源碰撞）。"""
    return f"{SOURCE}:{raw_id}"


def make_deck_id(raw_id: Any) -> str:
    return f"{SOURCE}:{raw_id}"


def compose_card_id(set_code: str | None, card_index: str | None) -> str | None:
    """card_id = {setCode}-{cardIndex}，原样拼接不补零；缺任一侧返回 None（不猜）。"""
    if not set_code or not card_index:
        return None
    return f"{set_code}-{card_index}"


def load_tier_map(vocab_dir: Path = VOCAB_DIR) -> dict[str, tuple[str, float]]:
    """tier 别名（小写）→ (规范 tier, 系数)。"""
    data = yaml.safe_load((vocab_dir / "tournament_tiers.yml").read_text(encoding="utf-8"))
    result: dict[str, tuple[str, float]] = {}
    for entry in data["tiers"]:
        for alias in [entry["tier"], *entry.get("aliases", [])]:
            result[str(alias).lower()] = (entry["tier"], float(entry["coef"]))
    return result


def load_division_map(vocab_dir: Path = VOCAB_DIR) -> dict[str, str]:
    """division 别名（小写）→ 规范 division。"""
    data = yaml.safe_load((vocab_dir / "tournament_tiers.yml").read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for entry in data["divisions"]:
        for alias in [entry["division"], *entry.get("aliases", [])]:
            result[str(alias).lower()] = entry["division"]
    return result


def _normalize_tier(
    raw: Any, tier_map: dict[str, tuple[str, float]]
) -> tuple[str | None, float | None]:
    """词表归一；未知 tier 保留原值 + coef=None + warning（不猜）。"""
    if raw is None or str(raw).strip() == "":
        return None, None
    raw_str = str(raw).strip()
    hit = tier_map.get(raw_str.lower())
    if hit is not None:
        return hit
    warnings.warn(
        f"未知赛事 tier: {raw_str!r}，tier_coef 置空（词表 tournament_tiers.yml 待补充）",
        stacklevel=2,
    )
    return raw_str, None


def _normalize_division(raw: Any, division_map: dict[str, str]) -> str | None:
    if raw is None or str(raw).strip() == "":
        return None
    raw_str = str(raw).strip()
    hit = division_map.get(raw_str.lower())
    if hit is not None:
        return hit
    warnings.warn(f"未知赛事 division: {raw_str!r}，保留源侧原值", stacklevel=2)
    return raw_str


def _parse_date(raw: Any) -> date | None:
    """endDate → date。容忍日期时间串（取前 10 位）；垃圾值置空 + warning，不猜。"""
    if not raw:
        return None
    text = str(raw)
    for candidate in (text, text[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    warnings.warn(f"无法解析的日期: {raw!r}，置空", stacklevel=2)
    return None


def _to_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    return int(raw)


def _to_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    return float(raw)


def parse_tournament(
    item: dict[str, Any],
    *,
    detail: dict[str, Any] | None = None,
    series_id: str | None = None,
    fetched_at: datetime,
    tier_map: dict[str, tuple[str, float]] | None = None,
    division_map: dict[str, str] | None = None,
) -> TournamentRecord:
    """/tournament/list 条目（可叠加 /tournament/detail）→ TournamentRecord。

    item 为 list 端点 data.list[] 条目；detail 为 detail 端点 data（可空）。
    真实口径（2026-08-02 校准）：条目主键字段为 `id`（不是 tournamentId）；
    series_id 由调用方从采集上下文传入（list 条目不自带）；detail 的
    participantCount / location / date 优先于 list 条目的同名字段。
    """
    tier, tier_coef = _normalize_tier(item.get("type"), tier_map or load_tier_map())
    division = _normalize_division(
        item.get("division"), division_map or load_division_map()
    )
    detail = detail or {}
    regulation = detail.get("regulation") or item.get("regulation")
    raw_series = series_id if series_id is not None else item.get("seriesId")
    return TournamentRecord(
        tournament_id=make_tournament_id(item.get("id") or item.get("tournamentId")),
        source=SOURCE,
        series_id=str(raw_series) if raw_series is not None else None,
        name=str(item.get("name") or detail.get("name") or ""),
        tier=tier,
        tier_coef=tier_coef,
        division=division,
        date=_parse_date(detail.get("date") or item.get("endDate")),
        location=detail.get("location") or item.get("location"),
        participant_count=_to_int(
            detail.get("participantCount")
            if detail.get("participantCount") is not None
            else item.get("participantCount")
        ),
        topcut_slots=None,  # 采集段无此数据
        format=str(regulation).lower() if regulation else None,
        regulation_mark=detail.get("regulationMark"),
        format_end=detail.get("formatEnd"),
        is_qual=item.get("isQual") if item.get("isQual") is not None else detail.get("isQual"),
        is_team=item.get("isTeam") if item.get("isTeam") is not None else detail.get("isTeam"),
        official_url=item.get("link"),
        fetched_at=fetched_at,
    )


def parse_rank_entry(
    entry: dict[str, Any], *, tournament_id: str, fetched_at: datetime
) -> list[AppearanceRecord]:
    """rank-individual 的 data.list[] 条目 → 出战条目列表（一条目可挂多卡组）。

    名次/积分/选手 = 出战条目级属性；variant 归类是内容级属性（见
    parse_deck_variant），不在此解析。players[].pinCode → player_ref
    （只存第一个选手的编号，隐私最小化）。
    """
    players = entry.get("players") or []
    player_ref = players[0].get("pinCode") if players else None
    records: list[AppearanceRecord] = []
    for deck in entry.get("decks") or []:
        if deck.get("deckId") is None:
            warnings.warn(f"排名条目缺 deckId，跳过: {deck!r}", stacklevel=2)
            continue
        records.append(
            AppearanceRecord(
                deck_id=make_deck_id(deck["deckId"]),
                tournament_id=tournament_id,
                rank=_to_int(entry.get("rank")),
                points=_to_float(entry.get("points")),
                player_ref=player_ref,
                fetched_at=fetched_at,
            )
        )
    return records


def parse_deck_variant(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """deck/detail 的 variant 字段 → (archetype_id, archetype_name)（内容级归类）。"""
    variant = data.get("variant") or {}
    variant_id = variant.get("variantId")
    return (
        str(variant_id) if variant_id is not None else None,
        variant.get("variantName"),
    )


def parse_deck_cards(deck_id: str, data: dict[str, Any]) -> list[DeckCardRecord]:
    """/deck/detail 的 data → DeckCardRecord 列表。

    卡标识 = setCode+cardIndex（与本库主键一致，零映射成本）；缺编号 card_id=None
    + raw_name 保真，不猜（FR-9.2）。
    """
    records: list[DeckCardRecord] = []
    for entry in data.get("cards") or []:
        raw_name = entry.get("cardName") or entry.get("name") or ""
        if not raw_name:
            warnings.warn(f"卡组卡条目缺卡名，跳过: {entry!r}", stacklevel=2)
            continue
        records.append(
            DeckCardRecord(
                deck_id=deck_id,
                card_id=compose_card_id(entry.get("setCode"), entry.get("cardIndex")),
                count=_to_int(entry.get("count")) or 0,
                raw_name=raw_name,
            )
        )
    return records

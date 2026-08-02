"""task 027 赛事解析层测试：raw 响应 → frozen schemas 的映射规则。

fixtures 为 2026-08-02 真实 API 探测响应（nickname 已脱敏）。校准要点：
- 赛事条目主键字段为 `id`（不是 tournamentId/seriesId）；
- date 优先 detail.date，回退 list.endDate（均为带时区 ISO 串，取日期部分）；
- type 实测值：Great=超级赛 / City=城市赛 / Ultra=高级赛（词表别名）；
- players[].pinCode → player_ref（只存编号，nickname 不落库）。
"""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from ptcgdb.normalize.tournaments import (
    compose_card_id,
    make_deck_id,
    make_tournament_id,
    parse_deck_cards,
    parse_deck_variant,
    parse_rank_entry,
    parse_tournament,
)
from ptcgdb.schemas import AppearanceRecord, DeckCardRecord, TournamentRecord

FIXTURES = Path(__file__).parent / "fixtures" / "tournaments"
NOW = datetime(2026, 8, 2, 12, 0, 0)


def load_data(name):
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return doc["data"]


# ---- ID 口径 ----


def test_id_conventions():
    assert make_tournament_id(3211) == "mik_moe:3211"
    assert make_tournament_id("3211") == "mik_moe:3211"
    assert make_deck_id(610080) == "mik_moe:610080"
    assert compose_card_id("CS5bC", "052") == "CS5bC-052"
    # 基本能量 cardIndex 为字母码，原样拼接不补零
    assert compose_card_id("CSMAC", "PSY") == "CSMAC-PSY"
    assert compose_card_id("CSV1C", "7") == "CSV1C-7"
    # 缺任一侧 → None（不猜）
    assert compose_card_id(None, "001") is None
    assert compose_card_id("CSM1bC", None) is None
    assert compose_card_id("", "") is None


# ---- tournaments 解析 ----


def test_parse_tournament_full():
    # list 条目 3211（西安超级赛公开组正赛）+ 真实 detail
    item = next(
        e for e in load_data("tournament_list.json")["list"] if e["id"] == 3211
    )
    detail = load_data("tournament_detail.json")
    record = parse_tournament(item, detail=detail, series_id="54", fetched_at=NOW)
    assert isinstance(record, TournamentRecord)
    assert record.model_config.get("frozen") is True
    assert record.tournament_id == "mik_moe:3211"
    assert record.source == "mik_moe"
    assert record.series_id == "54"
    assert record.name == "2026西安超级赛 - 公开组正赛"
    # Great → super（词表别名，西安超级赛实测），系数 2（FR-9.4）
    assert record.tier == "super"
    assert record.tier_coef == 2.0
    assert record.division == "master"
    assert record.date == date(2026, 5, 31)  # 带时区 ISO 串取日期部分
    assert record.location == "西安"
    assert record.participant_count == 32
    assert record.is_qual is False
    assert record.is_team is False
    # detail 三件套：regulation → format 小写归一；regulationMark / formatEnd 原样
    assert record.format == "standard"
    assert record.regulation_mark == "FGH"
    assert record.format_end == "CSV9C"
    # 解析层拿不到淘汰赛名额（采集段无此数据）
    assert record.topcut_slots is None


def test_parse_tournament_detail_fields_win_over_list():
    """detail 自带 type/division/location/participantCount/date，优先于 list 条目。"""
    item = next(
        e for e in load_data("tournament_list.json")["list"] if e["id"] == 3211
    )
    item = {**item, "participantCount": 9999, "location": "假地址", "endDate": "2020-01-01"}
    detail = load_data("tournament_detail.json")
    record = parse_tournament(item, detail=detail, series_id="54", fetched_at=NOW)
    assert record.participant_count == 32  # detail 真实值，不是 list 的 9999
    assert record.location == "西安"
    assert record.date == date(2026, 5, 31)


def test_parse_tournament_list_only_fallback():
    """无 detail 时回退 list 条目字段（endDate → date）。"""
    item = next(
        e for e in load_data("tournament_list.json")["list"] if e["id"] == 3215
    )
    record = parse_tournament(item, detail=None, series_id="54", fetched_at=NOW)
    assert record.tournament_id == "mik_moe:3215"
    assert record.name == "2026西安超级赛 - 公开组预赛"
    assert record.tier == "super"
    assert record.division == "master"
    assert record.date == date(2026, 5, 31)
    assert record.participant_count == 2065
    assert record.format == "standard"  # list 条目自带 regulation 字段
    assert record.regulation_mark is None
    assert record.format_end is None


def test_parse_tournament_tier_real_values():
    """2026-08-02 实测 type 值：Great=超级赛 / City=城市赛 / Ultra=高级赛。"""
    cases = {
        "tournament_list.json": ("super", 2.0),
        "tournament_list_city.json": ("city", 1.0),
        "tournament_list_ultra.json": ("advanced", 1.5),
    }
    for fixture, (tier, coef) in cases.items():
        item = load_data(fixture)["list"][0]
        record = parse_tournament(item, detail=None, series_id="0", fetched_at=NOW)
        assert (record.tier, record.tier_coef) == (tier, coef), fixture


def test_parse_tournament_division_real_values():
    items = load_data("tournament_list.json")["list"]
    divisions = {
        e["id"]: parse_tournament(e, detail=None, series_id="54", fetched_at=NOW).division
        for e in items
    }
    assert divisions[3215] == "master"
    assert divisions[3216] == "senior"
    assert divisions[3210] == "junior"


def test_parse_tournament_unknown_tier_warns_and_null_coef():
    item = load_data("tournament_list.json")["list"][0]
    item = {**item, "type": "Galaxy"}  # 词表外的未知 tier
    with pytest.warns(UserWarning, match="未知赛事 tier"):
        record = parse_tournament(item, detail=None, series_id="0", fetched_at=NOW)
    assert record.tier_coef is None
    assert record.tier == "Galaxy"  # 原值保真，不猜


def test_parse_tournament_missing_tier_and_division():
    item = {"id": 9001, "name": "无级别练习赛"}
    record = parse_tournament(item, detail=None, series_id=None, fetched_at=NOW)
    assert record.tier is None
    assert record.tier_coef is None
    assert record.division is None
    assert record.date is None
    assert record.participant_count is None
    assert record.series_id is None


def test_parse_tournament_bad_date_tolerated():
    item = {**load_data("tournament_list.json")["list"][0], "endDate": "not-a-date"}
    with pytest.warns(UserWarning, match="无法解析的日期"):
        record = parse_tournament(item, detail=None, series_id="0", fetched_at=NOW)
    assert record.date is None


# ---- rank-individual → 出战条目解析 ----


def test_parse_rank_entry_real():
    entry = load_data("rank_individual.json")["list"][0]
    apps = parse_rank_entry(entry, tournament_id="mik_moe:3211", fetched_at=NOW)
    assert len(apps) == 1
    app = apps[0]
    assert isinstance(app, AppearanceRecord)
    assert app.deck_id == "mik_moe:610080"
    assert app.tournament_id == "mik_moe:3211"
    assert app.player_ref == "CN94sI4sRe"  # 只存 pinCode（真实官方选手编号）
    assert app.rank == 1
    assert app.points == 1000.0
    # mik 无逐局战绩（A 层字段留空）
    assert app.record_wins is None
    assert app.record_losses is None
    assert app.record_ties is None
    assert app.source == "mik_moe"
    # variant 归类是内容级属性（deck/detail variant），出战条目不挂 archetype
    assert not hasattr(app, "archetype_id")
    # 隐私最小化：nickname/teamName 不进 AppearanceRecord
    assert not hasattr(app, "nickname")
    assert not hasattr(app, "team_name")


def test_parse_rank_entry_missing_fields_tolerated():
    apps = parse_rank_entry(
        {"rank": 5, "decks": [{"deckId": 7}]},
        tournament_id="mik_moe:3211",
        fetched_at=NOW,
    )
    assert len(apps) == 1
    app = apps[0]
    assert app.player_ref is None  # players 缺省
    assert app.points is None
    assert app.rank == 5


def test_parse_rank_entry_no_decks():
    assert parse_rank_entry({"rank": 1}, tournament_id="t", fetched_at=NOW) == []


def test_parse_deck_variant_real():
    """deck/detail 的 variant 字段 → 内容级 archetype（实测 610080）。"""
    data = load_data("deck_detail.json")
    assert parse_deck_variant(data) == ("285", "沙奈朵")


def test_parse_deck_variant_missing():
    assert parse_deck_variant({"deckId": 1}) == (None, None)
    assert parse_deck_variant({"variant": {}}) == (None, None)


# ---- deck/detail → deck_cards 解析 ----


def test_parse_deck_cards_real():
    data = load_data("deck_detail.json")
    cards = parse_deck_cards("mik_moe:610080", data)
    assert len(cards) == 28  # 真实卡组 28 个条目
    assert sum(c.count for c in cards) == 60  # 合计 60 张
    assert all(isinstance(c, DeckCardRecord) for c in cards)

    first = cards[0]
    assert first.deck_id == "mik_moe:610080"
    assert first.card_id == "CS5bC-052"
    assert first.count == 1
    assert first.raw_name == "玛纳霏"  # 源侧原始卡名保真
    # stat_scope 派生属入库段（要联 cards 表），解析段占位 other
    assert all(c.stat_scope == "other" for c in cards)
    # 真实响应里的额外字段（effectId/cardType/yorenCode/is/nameEn 等）不进入 schema
    assert not hasattr(first, "effect_id")


def test_parse_deck_cards_unmapped_entry():
    data = {
        "deckId": 9,
        "cards": [
            {"cardName": "来源缺编号的卡", "count": 2},  # 无 setCode/cardIndex → 不猜
        ],
    }
    cards = parse_deck_cards("mik_moe:9", data)
    assert len(cards) == 1
    assert cards[0].card_id is None
    assert cards[0].raw_name == "来源缺编号的卡"
    assert cards[0].count == 2


def test_parse_deck_cards_empty():
    assert parse_deck_cards("mik_moe:1", {"deckId": 1}) == []
    assert parse_deck_cards("mik_moe:1", {"deckId": 1, "cards": []}) == []


# ---- 词表 ----


def test_tier_vocabulary_coefficients():
    """PRD FR-9.4 系数：master/pjcs=4、super/cl=2、advanced/regional=1.5、city=1。"""
    from ptcgdb.normalize.tournaments import load_tier_map

    tier_map = load_tier_map()
    assert tier_map["great"] == ("super", 2.0)
    assert tier_map["city"] == ("city", 1.0)  # 城市赛实测值（seriesId=55）
    assert tier_map["ultra"] == ("advanced", 1.5)  # 高级赛实测值（seriesId=56）
    canonical = {}
    for _alias, (tier, coef) in tier_map.items():
        canonical.setdefault(tier, coef)
    assert canonical["master"] == 4.0
    assert canonical["pjcs"] == 4.0
    assert canonical["super"] == 2.0
    assert canonical["cl"] == 2.0
    assert canonical["advanced"] == 1.5
    assert canonical["regional"] == 1.5
    assert canonical["city"] == 1.0


def test_division_vocabulary():
    from ptcgdb.normalize.tournaments import load_division_map

    division_map = load_division_map()
    assert division_map["master"] == "master"
    assert division_map["senior"] == "senior"
    assert division_map["junior"] == "junior"

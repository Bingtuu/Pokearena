"""task 027 第二段：赛事 ingest 入库测试（raw → tournaments/decks/deck_cards）。

tmp 库 + 手工 raw 树（write_raw 落盘），零网络。覆盖：
- 全流程行数/字段断言；幂等（跑两遍结果一致）；
- 60 张质量门（FR-9.6 ①）：合计 != 60 的卡组整组拦截入报告；
- mapped_ratio / mapping_status（full ≥0.95 / partial / unmapped）；
- stat_scope 派生（FR-9.3）：pokemon/supporter/stadium/other，未知组合 → other + 警告；
- tier_coef 物化（master=4.0；未知 tier → NULL + 警告）。
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.ingest_tourneys import ingest_tourneys
from ptcgdb.orm import Card, Deck, DeckAppearance, DeckCard, Set, Tournament
from ptcgdb.scrapers.mikmoe_tournament import (
    deck_detail_path,
    rank_individual_path,
    tournament_detail_path,
    tournament_list_path,
)
from ptcgdb.scrapers.raw_store import write_raw

FIXTURES = Path(__file__).parent / "fixtures" / "tournaments"
NOW = datetime(2026, 8, 2, 12, 0, 0)


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---- tmp 库：最小 cards 行（五类 + 未知 trainer_subtype 各一）----


def make_card(card_id, set_id, card_type, trainer_subtype=None, name=None):
    return Card(
        card_id=card_id,
        set_id=set_id,
        number=card_id.split("-")[-1],
        number_display="001/127",
        name_full=name or card_id,
        card_type=card_type,
        regulation_mark=None if card_type == "energy" else "G",
        rarity="R",
        trainer_subtype=trainer_subtype,
        has_rule_box=False,
        is_tera=False,
        prize_cards=1,
        deck_limit=4,
        is_ace_spec=False,
        is_basic_energy=card_type == "energy",
        text_raw="",
        source="test",
        fetched_at=NOW,
        status="active",
    )


def build_db(db_path):
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for set_id, name in (
            ("CSM1bC", "测试补充包"),
            ("CSV1C", "测试朱紫"),
            ("CSMAC", "测试能量"),
        ):
            session.add(
                Set(
                    set_id=set_id,
                    name_zh=name,
                    era="朱&紫",
                    release_date=None,
                    regulation_mark="G",
                    source="test",
                    fetched_at="2026-08-02",
                )
            )
        session.add_all(
            [
                make_card("CSM1bC-001", "CSM1bC", "pokemon", name="超梦ex"),
                make_card("CSV1C-120", "CSV1C", "trainer", "支援者", "博士的研究"),
                make_card("CSV1C-121", "CSV1C", "trainer", "竞技场", "混沌场"),
                make_card("CSV1C-122", "CSV1C", "trainer", "物品", "精灵球"),
                make_card("CSV1C-123", "CSV1C", "trainer", "宝可梦道具", "力量护腕"),
                make_card("CSV1C-124", "CSV1C", "trainer", "实验性", "神秘训练家"),
                make_card("CSMAC-PSY", "CSMAC", "energy", name="基本超能量"),
            ]
        )
        session.commit()
    engine.dispose()


# ---- raw 树构造 ----


def deck_payload(deck_id, entries, variant_name="沙奈朵"):
    """entries: [(setCode, cardIndex, 卡名, count)]。variant 为实测内容级字段。"""
    return {
        "code": 200,
        "data": {
            "deckId": deck_id,
            "deckCode": f"code{deck_id}",
            "variant": {"deckId": deck_id, "variantId": 285, "variantName": variant_name},
            "cards": [
                {"setCode": sc, "cardIndex": ci, "cardName": nm, "count": ct}
                for sc, ci, nm, ct in entries
            ],
        },
        "msg": "",
    }


def rank_entry(rank, points, pin_code, deck_ids):
    """真实形态排名条目：nickname 会被解析层丢弃，player_ref 只取 pinCode。"""
    return {
        "rank": rank,
        "points": points,
        "qualified": False,
        "teamName": None,
        "players": [{"nickname": f"选手{rank:02d}", "pinCode": pin_code}],
        "decks": [
            {"deckId": d, "variantId": 285, "variantIcon": ["gardevoir"], "variantName": "沙奈朵"}
            for d in deck_ids
        ],
    }


def write_tournament_raw(raw_dir, *, series_id, item, detail, rank_entries, decks):
    """按采集器路径约定落一场赛事的全部 raw。decks: {rawDeckId: payload}。"""
    tid = str(item.get("id") or item.get("tournamentId"))
    write_raw(
        tournament_list_path(raw_dir, str(series_id), 1),
        {
            "code": 200,
            "data": {
                "list": [item],
                "pageCur": 1,
                "pageNum": 1,
                "pageSize": 100,
                "itemNum": 1,
            },
            "msg": "",
        },
        source="mik_moe",
    )
    write_raw(
        tournament_detail_path(raw_dir, tid),
        {"code": 200, "data": detail, "msg": ""},
        source="mik_moe",
    )
    write_raw(
        rank_individual_path(raw_dir, tid, 1),
        {
            "code": 200,
            "data": {
                "list": rank_entries,
                "pageCur": 1,
                "pageNum": 1,
                "pageSize": 64,
                "itemNum": len(rank_entries),
            },
            "msg": "",
        },
        source="mik_moe",
    )
    for raw_deck_id, payload in decks.items():
        write_raw(deck_detail_path(raw_dir, str(raw_deck_id)), payload, source="mik_moe")


DECK_555001 = [
    ("CSM1bC", "001", "超梦ex", 4),
    ("CSV1C", "120", "博士的研究", 4),
    ("CSV1C", "121", "混沌场", 2),
    ("CSV1C", "122", "精灵球", 4),
    ("CSV1C", "123", "力量护腕", 2),
    ("CSMAC", "PSY", "基本超能量", 44),
]  # 合计 60，五类全覆盖

DECK_555002 = [
    ("CSM1bC", "001", "超梦ex", 4),
    ("CSV1C", "124", "神秘训练家", 4),  # 未知 trainer_subtype → other + 警告
    ("CSV1C", "120", "博士的研究", 4),
    ("CSMAC", "PSY", "基本超能量", 44),
    ("XXXX", "999", "不存在卡", 4),  # cards 表无此卡 → card_id=NULL
]  # 合计 60，已解析 56 张 → partial

DECK_555003 = [
    ("CSM1bC", "001", "超梦ex", 4),
    ("CSMAC", "PSY", "基本超能量", 55),
]  # 合计 59 → 60 张门拦截


def build_raw_tree(raw_dir):
    # 真实 fixture：list-54 西安超级赛正赛 3211（Great/Master）+ detail-3211（FGH/CSV9C）
    items = load_fixture("tournament_list.json")["data"]["list"]
    item = next(e for e in items if e["id"] == 3211)
    detail = load_fixture("tournament_detail.json")["data"]
    # 合成排名条目（真实形态），卡组装 555001/2/3 对应下方三个 deck payload
    rank_entries = [
        rank_entry(1, 25.0, "P000123", [555001]),
        rank_entry(2, 20.0, "P000456", [555002]),
        rank_entry(3, 15.0, "P000789", [555003]),
    ]
    write_tournament_raw(
        raw_dir,
        series_id=54,
        item=item,
        detail=detail,
        rank_entries=rank_entries,
        decks={
            555001: deck_payload(555001, DECK_555001),
            555002: deck_payload(555002, DECK_555002),
            555003: deck_payload(555003, DECK_555003),
        },
    )


@pytest.fixture()
def env(tmp_path):
    raw_dir = tmp_path / "raw"
    db_path = tmp_path / "test.db"
    build_db(db_path)
    build_raw_tree(raw_dir)
    return raw_dir, db_path


def query(db_path, stmt):
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        rows = session.execute(stmt).all()
    engine.dispose()
    return rows


# ---- 全流程 ----


def test_ingest_full_flow(env):
    raw_dir, db_path = env
    result = ingest_tourneys(raw_dir, db_path)
    assert result.tournaments == 1
    assert result.decks == 2  # 内容实体 555001/555002；555003 被 60 张门拦截
    assert result.appearances == 2  # 555003 被 60 张门拦截，其名次条目也不落
    assert result.deck_cards == 6 + 5  # deck_cards 行数 = 卡条目数（非张数）

    # tournaments 行：tier 归一 + tier_coef 物化 + detail 三件套（detail 优先）
    tour = query(db_path, select(Tournament))[0][0]
    assert tour.tournament_id == "mik_moe:3211"
    assert tour.source == "mik_moe"
    assert tour.series_id == "54"
    assert tour.name == "2026西安超级赛 - 公开组正赛"
    assert tour.tier == "super"
    assert tour.tier_coef == 2.0
    assert tour.division == "master"
    assert tour.participant_count == 32  # detail 真实值优先于 list
    assert tour.format == "standard"
    assert tour.regulation_mark == "FGH"
    assert tour.format_end == "CSV9C"
    assert tour.is_qual is False and tour.is_team is False

    # decks 行 = 内容实体：variant（deck/detail 内容级字段）/ deck_code / full 映射
    deck1 = query(db_path, select(Deck).where(Deck.deck_id == "mik_moe:555001"))[0][0]
    assert deck1.archetype_id == "285"
    assert deck1.archetype_name == "沙奈朵"
    assert deck1.deck_code == "code555001"
    assert deck1.mapping_status == "full"
    assert deck1.mapped_ratio == 1.0

    # 出战条目：名次/积分/选手（pinCode）挂 appearance
    app1 = query(
        db_path,
        select(DeckAppearance).where(
            DeckAppearance.deck_id == "mik_moe:555001",
            DeckAppearance.tournament_id == "mik_moe:3211",
        ),
    )[0][0]
    assert app1.rank == 1
    assert app1.points == 25.0
    assert app1.player_ref == "P000123"
    assert app1.record_wins is None  # mik 无逐局战绩


def test_ingest_stat_scope(env):
    raw_dir, db_path = env
    result = ingest_tourneys(raw_dir, db_path)
    rows = query(
        db_path,
        select(DeckCard.card_id, DeckCard.stat_scope)
        .where(DeckCard.deck_id == "mik_moe:555001")
        .order_by(DeckCard.card_id),
    )
    scope = {card_id: stat_scope for card_id, stat_scope in rows}
    assert scope == {
        "CSM1bC-001": "pokemon",
        "CSV1C-120": "supporter",
        "CSV1C-121": "stadium",
        "CSV1C-122": "other",  # 物品不进统计
        "CSV1C-123": "other",  # 宝可梦道具不进统计
        "CSMAC-PSY": "other",  # 能量不进统计
    }

    # 未知 trainer_subtype（实验性）→ other + 报告警告，不猜
    rows2 = query(
        db_path,
        select(DeckCard.stat_scope).where(
            DeckCard.deck_id == "mik_moe:555002", DeckCard.card_id == "CSV1C-124"
        ),
    )
    assert rows2[0][0] == "other"
    assert any("实验性" in w for w in result.warnings)


def test_ingest_mapping_and_unknown_card(env):
    raw_dir, db_path = env
    result = ingest_tourneys(raw_dir, db_path)

    deck2 = query(db_path, select(Deck).where(Deck.deck_id == "mik_moe:555002"))[0][0]
    assert deck2.mapping_status == "partial"
    assert deck2.mapped_ratio == pytest.approx(56 / 60)

    # 未解析的卡：card_id=NULL + raw_name 保真，入 unknown 清单
    row = query(
        db_path,
        select(DeckCard.card_id, DeckCard.raw_name, DeckCard.stat_scope).where(
            DeckCard.deck_id == "mik_moe:555002", DeckCard.raw_name == "不存在卡"
        ),
    )[0]
    assert row == (None, "不存在卡", "other")
    assert any(u["raw_name"] == "不存在卡" for u in result.unknown_cards)


def test_ingest_sixty_card_gate(env):
    raw_dir, db_path = env
    result = ingest_tourneys(raw_dir, db_path)
    blocked = {b["deck_id"]: b for b in result.blocked}
    assert "mik_moe:555003" in blocked
    assert blocked["mik_moe:555003"]["total"] == 59
    # 被拦截的卡组整组不入库（内容行与出战条目都不落）
    assert query(db_path, select(Deck).where(Deck.deck_id == "mik_moe:555003")) == []
    assert (
        query(db_path, select(DeckCard).where(DeckCard.deck_id == "mik_moe:555003")) == []
    )
    assert (
        query(db_path, select(DeckAppearance).where(
            DeckAppearance.deck_id == "mik_moe:555003")) == []
    )


def test_ingest_shared_content_multiple_appearances(tmp_path):
    """实测语义（2026-08-02 订正）：同一 deckId = 内容实体，可出现在同一赛事多个
    名次 + 跨赛事——入库 = 1 行内容 + N 行出战条目。"""
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    items = load_fixture("tournament_list.json")["data"]["list"]
    item_main = next(e for e in items if e["id"] == 3211)  # 正赛
    item_qual = next(e for e in items if e["id"] == 3215)  # 预赛
    detail = load_fixture("tournament_detail.json")["data"]
    write_tournament_raw(
        raw_dir,
        series_id=54,
        item=item_main,
        detail=detail,
        rank_entries=[rank_entry(1, 25.0, "P000123", [555009])],
        decks={555009: deck_payload(555009, DECK_555001)},
    )
    write_tournament_raw(
        raw_dir,
        series_id=54,
        item=item_qual,
        detail={"id": 3215, "regulation": "Standard"},
        rank_entries=[
            rank_entry(5, 18.0, "P000123", [555009]),
            rank_entry(53, 6.0, "P000999", [555009]),
        ],
        decks={555009: deck_payload(555009, DECK_555001)},
    )
    result = ingest_tourneys(raw_dir, db_path)
    assert result.decks == 2  # 计数 = 处理次数（两场各处理一次，merge 幂等）
    # 内容行唯一（merge 幂等）
    assert len(query(db_path, select(Deck).where(Deck.deck_id == "mik_moe:555009"))) == 1
    assert result.appearances == 3  # 正赛 rank1 + 预赛 rank5/rank53
    apps = query(
        db_path,
        select(DeckAppearance.tournament_id, DeckAppearance.rank)
        .where(DeckAppearance.deck_id == "mik_moe:555009")
        .order_by(DeckAppearance.tournament_id, DeckAppearance.rank),
    )
    assert apps == [("mik_moe:3211", 1), ("mik_moe:3215", 5), ("mik_moe:3215", 53)]


def test_ingest_idempotent(env):
    raw_dir, db_path = env
    first = ingest_tourneys(raw_dir, db_path)
    snapshot = query(
        db_path,
        select(DeckCard.deck_id, DeckCard.card_id, DeckCard.count, DeckCard.raw_name,
               DeckCard.stat_scope).order_by(DeckCard.deck_id, DeckCard.raw_name),
    )
    second = ingest_tourneys(raw_dir, db_path)
    assert (second.tournaments, second.decks, second.appearances, second.deck_cards) == (
        first.tournaments,
        first.decks,
        first.appearances,
        first.deck_cards,
    )
    assert query(
        db_path,
        select(DeckCard.deck_id, DeckCard.card_id, DeckCard.count, DeckCard.raw_name,
               DeckCard.stat_scope).order_by(DeckCard.deck_id, DeckCard.raw_name),
    ) == snapshot
    assert len(query(db_path, select(Deck))) == 2
    assert len(query(db_path, select(DeckAppearance))) == 2  # 555003 的名次条目不落


def test_ingest_unmapped_deck(tmp_path):
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    items = load_fixture("tournament_list.json")["data"]["list"]
    item = next(e for e in items if e["id"] == 3211)
    detail = load_fixture("tournament_detail.json")["data"]
    rank_entries = [
        {"rank": 9, "points": 1.0, "players": [{"pinCode": "P999"}],
         "decks": [{"deckId": 777, "variantId": 1, "variantName": "谜之卡组"}]}
    ]
    write_tournament_raw(
        raw_dir,
        series_id=54,
        item=item,
        detail=detail,
        rank_entries=rank_entries,
        decks={
            777: deck_payload(777, [("XXXX", "001", "未知卡A", 30), ("YYYY", "002", "未知卡B", 30)])
        },
    )
    result = ingest_tourneys(raw_dir, db_path)
    deck = query(db_path, select(Deck).where(Deck.deck_id == "mik_moe:777"))[0][0]
    assert deck.mapping_status == "unmapped"
    assert deck.mapped_ratio == 0.0
    assert len(result.unknown_cards) == 2


def test_ingest_tier_coef_master_and_unknown(tmp_path):
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    entries = [("CSM1bC", "001", "超梦ex", 60)]
    # 9901 用实测主键字段 id；9902 保留旧 tournamentId 形态以覆盖兼容回退
    cases = [
        (9901, 12, "master",
         {"id": 9901, "name": "赛事9901", "endDate": "2026-07-26", "type": "master",
          "division": "Master", "participantCount": 100, "isQual": False, "isTeam": False}),
        (9902, 13, "Galaxy",
         {"tournamentId": 9902, "name": "赛事9902", "endDate": "2026-07-26",
          "type": "Galaxy", "division": "Master", "participantCount": 100,
          "isQual": False, "isTeam": False}),
    ]
    for tid, series_id, _tier_raw, item in cases:
        write_tournament_raw(
            raw_dir,
            series_id=series_id,
            item=item,
            detail={"id": tid, "regulation": "Standard",
                    "regulationMark": "GHI", "formatEnd": "CSV10C"},
            rank_entries=[{"rank": 1, "points": 10.0, "players": [{"pinCode": "P1"}],
                           "decks": [{"deckId": tid * 10, "variantId": 1, "variantName": "x"}]}],
            decks={tid * 10: deck_payload(tid * 10, entries)},
        )
    result = ingest_tourneys(raw_dir, db_path)
    coefs = dict(query(db_path, select(Tournament.tournament_id, Tournament.tier_coef)))
    assert coefs["mik_moe:9901"] == 4.0  # 大师赛系数（FR-9.4）
    assert coefs["mik_moe:9902"] is None  # 未知 tier → NULL，不猜
    assert any("Galaxy" in w for w in result.warnings)


# ---- CLI：ptcgdb ingest-tourneys ----

from typer.testing import CliRunner  # noqa: E402

from ptcgdb import cli  # noqa: E402


def test_cli_ingest_tourneys_blocked_exit_1(env):
    raw_dir, db_path = env
    result = CliRunner().invoke(
        cli.app,
        ["ingest-tourneys", "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    # 有卡组被 60 张门拦截 → 非零退出（与卡牌 ingest 的 skipped 行为一致）
    assert result.exit_code == 1
    assert "tournaments=1" in result.output
    assert "decks=2" in result.output
    assert "blocked=1" in result.output
    assert "mik_moe:555003" in result.output
    # 行已入库
    assert len(query(db_path, select(Deck))) == 2


def test_cli_ingest_tourneys_clean_exit_0(tmp_path):
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    items = load_fixture("tournament_list.json")["data"]["list"]
    item = next(e for e in items if e["id"] == 3211)
    write_tournament_raw(
        raw_dir,
        series_id=54,
        item=item,
        detail=load_fixture("tournament_detail.json")["data"],
        rank_entries=[{"rank": 1, "points": 10.0, "players": [{"pinCode": "P1"}],
                       "decks": [{"deckId": 888, "variantId": 66, "variantName": "沙奈朵ex"}]}],
        decks={888: deck_payload(888, DECK_555001)},
    )
    result = CliRunner().invoke(
        cli.app,
        ["ingest-tourneys", "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    assert result.exit_code == 0
    assert "blocked=0" in result.output

"""task 028 首步：赛事环境推导与落库测试（PRD FR-9.1b）。

零网络。覆盖：
- derive_env 日历段命中/边界/未命中（CN/EN/JA 三赛区种子真值）；
- ingest 集成：env 落库、未命中 → NULL + 异常告警、卡组最大赛制标记交叉校验
  （不符告警不拒收）。
"""

from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.envs import derive_env, load_calendar
from ptcgdb.normalize.ingest_tourneys import ingest_tourneys
from ptcgdb.orm import Card, Set, Tournament
from ptcgdb.scrapers.mikmoe_tournament import (
    deck_detail_path,
    rank_individual_path,
    tournament_detail_path,
    tournament_list_path,
)
from ptcgdb.scrapers.raw_store import write_raw

FIXTURES = Path(__file__).parent / "fixtures" / "tournaments"
NOW = datetime(2026, 8, 4, 12, 0, 0)

# ---- derive_env 单元（种子真值：config/tournament_envs.yml）----

CAL = load_calendar()


def test_derive_env_cn_segment():
    # CN 当前段：2026-07-16 起 G/H/I（合法性快照复用，无 effective_to）
    seg = derive_env("cn", date(2026, 7, 16), CAL)
    assert seg is not None
    assert seg.env == "GHI"
    assert seg.allowed_marks == ("G", "H", "I")
    assert derive_env("cn", date(2026, 8, 4), CAL).env == "GHI"


def test_derive_env_cn_before_start_misses():
    # 早于收集起点（范围收口，历史不回填）→ None，不猜
    assert derive_env("cn", date(2026, 7, 15), CAL) is None
    assert derive_env("cn", date(2023, 5, 28), CAL) is None


def test_derive_env_en_window_and_rotation():
    # EN 对齐窗口 2025-04-11 ~ 2026-04-09 = G/H/I；2026-04-10 起 H/I/J
    assert derive_env("en", date(2025, 4, 11), CAL).env == "GHI"
    assert derive_env("en", date(2026, 4, 9), CAL).env == "GHI"
    assert derive_env("en", date(2026, 4, 10), CAL).env == "HIJ"
    assert derive_env("en", date(2025, 4, 10), CAL) is None


def test_derive_env_ja_transition_period():
    # JA 2025-12-19 ~ 2026-01-22 过渡期 G~J 四标并行
    assert derive_env("ja", date(2025, 12, 18), CAL).env == "GHI"
    assert derive_env("ja", date(2025, 12, 19), CAL).env == "GHIJ"
    assert derive_env("ja", date(2026, 1, 22), CAL).env == "GHIJ"
    assert derive_env("ja", date(2026, 1, 23), CAL).env == "HIJ"


def test_derive_env_none_inputs():
    assert derive_env("cn", None, CAL) is None
    assert derive_env(None, date(2026, 8, 1), CAL) is None
    assert derive_env("unknown_region", date(2026, 8, 1), CAL) is None


# ---- ingest 集成：env 落库 + 交叉校验 ----


def make_card(card_id, set_id, regulation_mark="G"):
    return Card(
        card_id=card_id,
        set_id=set_id,
        number=card_id.split("-")[-1],
        number_display="001/127",
        name_full=card_id,
        card_type="pokemon",
        regulation_mark=regulation_mark,
        rarity="R",
        trainer_subtype=None,
        has_rule_box=False,
        is_tera=False,
        prize_cards=1,
        deck_limit=4,
        is_ace_spec=False,
        is_basic_energy=False,
        text_raw="",
        source="test",
        fetched_at=NOW,
        status="active",
    )


def build_db(db_path):
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(
            Set(
                set_id="CSX1C",
                name_zh="测试包",
                era="朱&紫",
                release_date=None,
                regulation_mark="G",
                source="test",
                fetched_at="2026-08-04",
            )
        )
        session.add_all(
            [
                make_card("CSX1C-001", "CSX1C", "G"),
                make_card("CSX1C-002", "CSX1C", "J"),  # 超 env 标记（交叉校验用）
            ]
        )
        session.commit()
    engine.dispose()


def write_tournament_raw(raw_dir, tid, end_date, deck_entries):
    """落一场最小赛事 raw：list + detail + rank-individual + deck/detail。"""
    write_raw(
        tournament_list_path(raw_dir, "99", 1),
        {
            "code": 200,
            "data": {
                "list": [
                    {
                        "id": tid,
                        "name": f"赛事{tid}",
                        "endDate": end_date,
                        "type": "Great",
                        "division": "Master",
                        "participantCount": 64,
                        "isQual": False,
                        "isTeam": False,
                    }
                ],
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
        tournament_detail_path(raw_dir, str(tid)),
        {"code": 200, "data": {"id": tid, "regulation": "Standard"}, "msg": ""},
        source="mik_moe",
    )
    write_raw(
        rank_individual_path(raw_dir, str(tid), 1),
        {
            "code": 200,
            "data": {
                "list": [
                    {
                        "rank": 1,
                        "points": 10.0,
                        "players": [{"pinCode": "P1"}],
                        "decks": [{"deckId": tid * 10, "variantId": 1, "variantName": "x"}],
                    }
                ],
                "pageCur": 1,
                "pageNum": 1,
                "pageSize": 64,
                "itemNum": 1,
            },
            "msg": "",
        },
        source="mik_moe",
    )
    write_raw(
        deck_detail_path(raw_dir, str(tid * 10)),
        {
            "code": 200,
            "data": {
                "deckId": tid * 10,
                "variant": {"variantId": 1, "variantName": "x"},
                "cards": [
                    {"setCode": sc, "cardIndex": ci, "cardName": nm, "count": ct}
                    for sc, ci, nm, ct in deck_entries
                ],
            },
            "msg": "",
        },
        source="mik_moe",
    )


def query(db_path, stmt):
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        rows = session.execute(stmt).all()
    engine.dispose()
    return rows


def test_ingest_env_derived_and_stored(tmp_path):
    """CN 当前段内的赛事：env=GHI 落库；卡组最大标记 G ∈ allowed → 无告警。"""
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    write_tournament_raw(raw_dir, 9001, "2026-08-01", [("CSX1C", "001", "测试卡", 60)])
    result = ingest_tourneys(raw_dir, db_path)
    tour = query(db_path, select(Tournament))[0][0]
    assert tour.env == "GHI"
    assert not any("环境推导未命中" in w for w in result.warnings)
    assert not any("交叉校验" in w for w in result.warnings)


def test_ingest_env_miss_null_and_warning(tmp_path):
    """早于收集起点的赛事：env=NULL + 记异常（范围收口，历史不回填，不猜）。"""
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    write_tournament_raw(raw_dir, 9002, "2026-05-31", [("CSX1C", "001", "测试卡", 60)])
    result = ingest_tourneys(raw_dir, db_path)
    tour = query(db_path, select(Tournament))[0][0]
    assert tour.env is None
    assert any("环境推导未命中" in w and "mik_moe:9002" in w for w in result.warnings)


def test_ingest_env_cross_check_warns_not_rejects(tmp_path):
    """卡组最大赛制标记 J ∉ env GHI → 告警但照常入库（不拒收）。"""
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    build_db(db_path)
    write_tournament_raw(
        raw_dir,
        9003,
        "2026-08-01",
        [("CSX1C", "001", "测试卡G", 30), ("CSX1C", "002", "测试卡J", 30)],
    )
    result = ingest_tourneys(raw_dir, db_path)
    assert any(
        "交叉校验告警" in w and "J" in w and "mik_moe:90030" in w
        for w in result.warnings
    )
    # 不拒收：卡组与出战条目照常落库
    assert result.decks == 1
    assert result.appearances == 1


def test_ingest_env_migration_user_version_8(tmp_path):
    """migration 008：env 列落库后 user_version=8。"""
    db_path = tmp_path / "t.db"
    assert apply_migrations(db_path) == 8

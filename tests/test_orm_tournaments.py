"""ORM 测试：Tournament / Deck / DeckAppearance / DeckCard（PRD §7.5 v1.10 续，task 027）。

校验 metadata 建表列名与 PRD 一致、ORM 往返插入（含 deck_cards 可空 card_id、
同一内容多条出战条目）。
"""

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.orm import Base, Deck, DeckAppearance, DeckCard, Pairing, Tournament


def test_orm_tables_registered():
    assert {"tournaments", "decks", "deck_appearances", "deck_cards", "pairings"} <= set(
        Base.metadata.tables
    )


def test_orm_columns_match_prd():
    assert list(Tournament.__table__.columns.keys()) == [
        "tournament_id",
        "source",
        "series_id",
        "name",
        "tier",
        "tier_coef",
        "division",
        "date",
        "location",
        "participant_count",
        "topcut_slots",
        "format",
        "regulation_mark",
        "format_end",
        "env",  # FR-9.1b（migration 008）：日期∩日历段推导，未命中 NULL
        "is_qual",
        "is_team",
        "official_url",
        "fetched_at",
    ]
    assert list(Deck.__table__.columns.keys()) == [
        "deck_id",
        "archetype_id",
        "archetype_name",
        "deck_code",
        "mapping_status",
        "mapped_ratio",
        "source",
        "fetched_at",
    ]
    assert list(DeckAppearance.__table__.columns.keys()) == [
        "deck_id",
        "tournament_id",
        "rank",
        "points",
        "player_ref",
        "record_wins",
        "record_losses",
        "record_ties",
        "source",
        "fetched_at",
    ]
    assert [c.name for c in DeckAppearance.__table__.primary_key] == [
        "deck_id",
        "tournament_id",
        "rank",
    ]
    assert list(DeckCard.__table__.columns.keys()) == [
        "deck_id",
        "card_id",
        "count",
        "raw_name",
        "stat_scope",
    ]
    assert [c.name for c in DeckCard.__table__.primary_key] == [
        "deck_id",
        "card_id",
        "raw_name",
    ]
    assert DeckCard.__table__.c.card_id.nullable is True
    assert list(Pairing.__table__.columns.keys()) == [
        "tournament_id",
        "phase",
        "round",
        "table_no",  # 避 SQLite 关键字 table
        "player1",
        "player2",
        "winner",
        "fetched_at",
    ]
    assert [c.name for c in Pairing.__table__.primary_key] == [
        "tournament_id",
        "phase",
        "round",
        "table_no",
    ]
    assert Pairing.__table__.c.winner.nullable is True  # 平局/未报不猜


def test_orm_round_trip(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 2, 12, 0, 0)
    with Session(engine) as session:
        session.add(
            Tournament(
                tournament_id="mik_moe:8801",
                source="mik_moe",
                series_id="12",
                name="2026 大师赛·上海 正赛",
                tier="super",
                tier_coef=2.0,
                division="master",
                date=date(2026, 7, 26),
                location="上海",
                participant_count=1024,
                topcut_slots=64,
                format="standard",
                regulation_mark="GHI",
                format_end="CSV10C",
                is_qual=False,
                is_team=False,
                official_url=None,
                fetched_at=now,
            )
        )
        session.add(
            Deck(
                deck_id="mik_moe:555001",
                archetype_id="285",
                archetype_name="沙奈朵",
                deck_code="Ab3dEf",
                mapping_status="full",
                mapped_ratio=1.0,
                source="mik_moe",
                fetched_at=now,
            )
        )
        # 同一内容在同一赛事的两个名次（实测语义：deckId 按内容去重）
        session.add_all(
            [
                DeckAppearance(
                    deck_id="mik_moe:555001",
                    tournament_id="mik_moe:8801",
                    rank=5,
                    points=18.0,
                    player_ref="CN0001aa",
                    record_wins=None,
                    record_losses=None,
                    record_ties=None,
                    source="mik_moe",
                    fetched_at=now,
                ),
                DeckAppearance(
                    deck_id="mik_moe:555001",
                    tournament_id="mik_moe:8801",
                    rank=53,
                    points=6.0,
                    player_ref="CN0002bb",
                    record_wins=None,
                    record_losses=None,
                    record_ties=None,
                    source="mik_moe",
                    fetched_at=now,
                ),
            ]
        )
        session.add_all(
            [
                DeckCard(
                    deck_id="mik_moe:555001",
                    card_id="CSM1bC-001",
                    count=3,
                    raw_name="超梦ex",
                    stat_scope="pokemon",
                ),
                DeckCard(
                    deck_id="mik_moe:555001",
                    card_id=None,  # 映射不上不猜
                    count=4,
                    raw_name="某未映射卡",
                    stat_scope="other",
                ),
            ]
        )
        session.commit()

        deck = session.get(Deck, "mik_moe:555001")
        assert deck is not None
        assert len(deck.appearances) == 2
        assert deck.appearances[0].tournament.tier_coef == 2.0
        cards = session.query(DeckCard).filter_by(deck_id="mik_moe:555001").all()
        assert len(cards) == 2
        assert {c.card_id for c in cards} == {"CSM1bC-001", None}
    engine.dispose()

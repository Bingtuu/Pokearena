"""task 026 测试：SDK validate_deck 双后端（DbBackend/JsonlBackend）同一契约。

fixture 库含：白名单旧卡 / 禁卡 / 非合法标记卡 / 基本能量，standard + open 双快照；
经 export_all 导出 dist 后断言两后端 DeckReport 全等，且语义与 FR-8 一致。
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.export.exporter import export_all
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import (
    Card,
    CardNameGroup,
    LegalitySnapshot,
    Meta,
    NameGroup,
    Set,
)
from ptcgdb.sdk import open_db, open_jsonl

D = date(2026, 8, 1)


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "t.db"
    apply_migrations(path)
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        s.add(Set(
            set_id="TS", name_zh="测试系列", era="朱&紫", release_date=date(2026, 1, 1),
            regulation_mark="G", expected_count=None, expected_secret_count=None,
            source="test", fetched_at="2026-01-01",
        ))
        s.add(NameGroup(group_key="高级球", display_name="高级球"))

        def card(cid, name, mark, *, ctype="pokemon", basic=False, provides=None):
            s.add(Card(
                card_id=cid, set_id="TS", number=cid.rsplit("-", 1)[1],
                number_display="001/100", name_full=name, species=name, owner=None,
                card_type=ctype, regulation_mark=mark, rarity="R", stage=None, hp=None,
                types=None, evolves_from_text=None, evolves_from_id=None,
                evolution_chain_id=None, rule_box_type=None, has_rule_box=False,
                is_tera=False, union_position=None, prize_cards=1, deck_limit=4,
                is_ace_spec=False, abilities=None, attacks=None, weakness=None,
                resistance=None, retreat_cost=None, trainer_subtype=None,
                provides=provides, is_basic_energy=basic,
                text_raw=f"{name}原文", effect_tags=None,
                name_en=None, name_ja=None, name_zh_tw=None, source="test",
                fetched_at=datetime.now(UTC), status="active",
            ))

        card("TS-001", "喵喵", "G")
        card("TS-002", "高级球", "G", ctype="trainer")
        card("TS-003", "高级球", "F", ctype="trainer")      # 白名单旧卡
        card("TS-004", "玛夏多", "G")                        # 禁卡
        card("TS-005", "古老化石", "F")                      # 非白名单旧卡 → not_legal
        card("TS-006", "基本草能量", None, ctype="energy", basic=True, provides=["草"])
        for cid in ("TS-002", "TS-003"):
            s.add(CardNameGroup(card_id=cid, group_key="高级球"))
        s.add(LegalitySnapshot(
            snapshot_id="standard-1", format="standard",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=["G", "H", "I"],
            allowed_basic_energy_types=["草"],
            whitelist_cards=[{"name_full": "高级球"}],
            banned_cards=[{"name": "玛夏多"}],
            mark_overrides=[], latest_text_overrides={},
            source_url="test", created_at=datetime.now(UTC),
        ))
        s.add(LegalitySnapshot(
            snapshot_id="open-1", format="open",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=list("ABCDEFGHI"),
            allowed_basic_energy_types=["草"],
            whitelist_cards=[], banned_cards=[{"name": "玛夏多"}],
            mark_overrides=[], latest_text_overrides={},
            source_url="test", created_at=datetime.now(UTC),
        ))
        s.add(Meta(key="data_version", value="v20260804.1"))
        s.commit()
    engine.dispose()
    return path


@pytest.fixture()
def backends(db_path, tmp_path):
    dist = tmp_path / "dist"
    export_all(db_path, dist)
    db = open_db(db_path)
    jl = open_jsonl(dist)
    yield db, jl
    db.close()
    jl.close()


def pad(deck: list[str]) -> list[str]:
    return deck + ["TS-006"] * (60 - len(deck))


def test_ok_deck_both_backends(backends):
    db, jl = backends
    deck = pad(["TS-001"] * 4 + ["TS-002"] * 2 + ["TS-003"] * 2)  # 白名单旧卡合法
    for backend in (db, jl):
        report = backend.validate_deck(deck, date=D, format="standard")
        assert report.ok is True
        assert report.violations == []
        assert report.deck_size == 60
        assert report.snapshot_id == "standard-1"


def test_banned_and_not_legal(backends):
    db, _ = backends
    report = db.validate_deck(pad(["TS-004", "TS-005"]), date=D, format="standard")
    assert report.ok is False
    by_kind = {v.kind: v for v in report.violations}
    assert by_kind["banned"].cards == ["TS-004"]
    assert by_kind["not_legal"].cards == ["TS-005"]


def test_open_format_allows_old_marks(backends):
    """同一卡表换赛制：open 允许 F 标记 → 古老化石合法；玛夏多仍 banned。"""
    db, _ = backends
    report = db.validate_deck(pad(["TS-005"] * 4), date=D, format="open")
    assert report.ok is True
    assert report.snapshot_id == "open-1"
    banned = db.validate_deck(pad(["TS-004"]), date=D, format="open")
    assert [v.kind for v in banned.violations] == ["banned"]


def test_dual_backends_report_equal(backends):
    """A8 式契约：含混合违规的卡表，两后端 DeckReport 全等。"""
    db, jl = backends
    deck = pad(["TS-001"] * 5 + ["TS-004", "TS-005", "X-999"])
    r_db = db.validate_deck(deck, date="2026-08-01", format="standard")
    r_jl = jl.validate_deck(deck, date="2026-08-01", format="standard")
    assert r_db == r_jl
    kinds = {v.kind for v in r_db.violations}
    assert kinds == {"name_limit", "banned", "not_legal", "unknown_card"}


def test_no_snapshot_raises(backends):
    db, jl = backends
    for backend in (db, jl):
        with pytest.raises(LookupError):
            backend.validate_deck(pad([]), date=date(2020, 1, 1), format="standard")

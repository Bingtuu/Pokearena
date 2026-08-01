"""SDK 双后端测试（task 011）：接口行为 + A8 双后端一致性契约。"""

from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.export.exporter import export_all
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import (
    Card,
    CardNameGroup,
    Errata,
    LegalitySnapshot,
    Meta,
    NameGroup,
    Set,
)
from ptcgdb.sdk import open_db, open_jsonl


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "t.db"
    apply_migrations(path)
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        s.add(Set(
            set_id="T1", name_zh="测试系列", era="朱&紫", release_date=date(2026, 1, 1),
            regulation_mark="G", expected_count=None, expected_secret_count=None,
            source="test", fetched_at="2026-01-01",
        ))
        s.add(Set(
            set_id="T0", name_zh="旧系列", era="剑&盾", release_date=date(2025, 1, 1),
            regulation_mark="F", expected_count=None, expected_secret_count=None,
            source="test", fetched_at="2025-01-01",
        ))
        s.add(NameGroup(group_key="高级球", display_name="高级球"))

        def card(cid, sid, name, mark, *, ctype="pokemon", tera=False, rule=False,
                 basic=False, provides=None, text=None, species=None):
            c = Card(
                card_id=cid, set_id=sid, number=cid.rsplit("-", 1)[1],
                number_display="001/100", name_full=name, species=species, owner=None,
                card_type=ctype, regulation_mark=mark, rarity="R", stage=None, hp=None,
                types=None, evolves_from_text=None, evolves_from_id=None,
                evolution_chain_id=None, rule_box_type=None, has_rule_box=rule,
                is_tera=tera, union_position=None, prize_cards=1, deck_limit=4,
                is_ace_spec=False, abilities=None, attacks=None, weakness=None,
                resistance=None, retreat_cost=None, trainer_subtype=None,
                provides=provides, is_basic_energy=basic,
                text_raw=text or f"{name}原文", effect_tags=None,
                name_en=None, name_ja=None, name_zh_tw=None, source="test",
                fetched_at=datetime.now(UTC), status="active",
            )
            s.add(c)
            return c

        card("T1-001", "T1", "新叶喵", "G", tera=True, species="新叶喵")
        card("T1-002", "T1", "魔幻假面喵ex", "G", rule=True)
        card("T0-001", "T0", "高级球", "F", ctype="trainer", text="高级球旧文本")
        card("T1-003", "T1", "高级球", "G", ctype="trainer", text="高级球新文本")
        card("T1-004", "T1", "基本妖能量", None, ctype="energy", basic=True,
             provides=["妖"])
        for cid in ("T0-001", "T1-003"):
            s.add(CardNameGroup(card_id=cid, group_key="高级球"))
        s.add(Errata(
            errata_id="e1", card_id="T1-003",
            effective_from=date(2026, 6, 1), corrected_text="高级球勘误文本",
        ))
        s.add(LegalitySnapshot(
            snapshot_id="standard-1", format="standard",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=["G", "H", "I"],
            allowed_basic_energy_types=["草", "火"],
            whitelist_cards=[{"name_full": "高级球"}], banned_cards=[],
            mark_overrides=[], latest_text_overrides={"T0-001": "T1-003"},
            source_url="test", created_at=datetime.now(UTC),
        ))
        s.add(LegalitySnapshot(
            snapshot_id="open-1", format="open",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=list("ABCDEFGHI"),
            allowed_basic_energy_types=["草", "火", "妖"],
            whitelist_cards=[{"name_full": "高级球"}], banned_cards=[],
            mark_overrides=[], latest_text_overrides={},
            source_url="test", created_at=datetime.now(UTC),
        ))
        s.add(Meta(key="data_version", value="v20260801.1"))
        s.commit()
    engine.dispose()
    return path


@pytest.fixture()
def dist(db_path, tmp_path):
    out = tmp_path / "dist"
    export_all(db_path, out)
    return out


@pytest.fixture()
def backends(db_path, dist):
    db = open_db(db_path)
    jl = open_jsonl(dist)
    yield db, jl
    db.close()
    jl.close()


D = date(2026, 8, 1)


class TestInterfaceBehavior:
    def test_schema_version(self, backends):
        db, jl = backends
        assert db.schema_version == "1.0.0"
        assert jl.schema_version == "1.0.0"

    def test_return_types_are_pydantic(self, backends):
        """返回类型一律 frozen Pydantic，不暴露 ORM。"""
        db, _ = backends
        card = db.get_card("T1-001")
        assert isinstance(card, BaseModel)
        assert card.model_config.get("frozen") is True
        assert not hasattr(card, "_sa_instance_state")
        pool = db.legal_at(D, "standard")
        assert isinstance(pool, BaseModel)
        assert isinstance(pool.card_ids, frozenset)

    def test_get_card_missing(self, backends):
        db, _ = backends
        assert db.get_card("NOPE-001") is None

    def test_search_filters(self, backends):
        db, _ = backends
        assert {c.card_id for c in db.search_cards(name="喵")} == {"T1-001", "T1-002"}
        assert {c.card_id for c in db.search_cards(marks=("F",))} == {"T0-001"}
        assert {c.card_id for c in db.search_cards(is_tera=True)} == {"T1-001"}
        assert {c.card_id for c in db.search_cards(has_rule_box=True)} == {"T1-002"}
        assert {c.card_id for c in db.search_cards(card_type="energy")} == {"T1-004"}
        assert {c.card_id for c in db.search_cards(set_ids=("T0",))} == {"T0-001"}
        assert len(db.search_cards(limit=1)) == 1

    def test_sets(self, backends):
        db, _ = backends
        assert db.get_set("T1").name_zh == "测试系列"
        assert db.get_set("NOPE") is None
        assert {s.set_id for s in db.list_sets()} == {"T0", "T1"}
        assert {s.set_id for s in db.list_sets(era="朱&紫")} == {"T1"}

    def test_snapshots(self, backends):
        db, _ = backends
        assert {s.snapshot_id for s in db.snapshots()} == {"standard-1", "open-1"}
        assert [s.snapshot_id for s in db.snapshots(format="standard")] == ["standard-1"]

    def test_legal_at_semantics(self, backends):
        db, _ = backends
        std = db.legal_at(D, "standard")
        assert std.snapshot_id == "standard-1"
        assert "T1-004" not in std.card_ids  # 妖能量 standard 不合法
        assert "T1-004" in db.legal_at(D, "open").card_ids
        assert std.by_name_group["高级球"] == ["T0-001", "T1-003"]

    def test_legal_at_accepts_str_date(self, backends):
        db, _ = backends
        assert db.legal_at("2026-08-01", "standard").card_ids == db.legal_at(D, "standard").card_ids

    def test_effective_text(self, backends):
        db, _ = backends
        et = db.effective_text("T0-001", D)
        assert et.text == "高级球勘误文本"  # 勘误 > 最新印刷
        assert et.source == "errata"
        assert et.resolved_card_id == "T1-003"
        et2 = db.effective_text("T0-001", date(2026, 2, 1))
        assert et2.text == "高级球新文本"  # 最新印刷 > 原文
        assert et2.source == "latest_print"


class TestDualBackendContract:
    """A8：同一查询集，open_db 与 open_jsonl 返回一致。"""

    def test_get_card(self, backends):
        db, jl = backends
        for cid in ("T1-001", "T0-001", "T1-004", "NOPE-001"):
            assert db.get_card(cid) == jl.get_card(cid)

    def test_search_cards(self, backends):
        db, jl = backends
        queries = [
            {"name": "喵"},
            {"name": "高级球"},
            {"marks": ("F",)},
            {"marks": ("G", "H", "I"), "card_type": "pokemon"},
            {"is_tera": True},
            {"has_rule_box": True},
            {"set_ids": ("T0",)},
            {},
        ]
        for q in queries:
            assert db.search_cards(**q) == jl.search_cards(**q), q

    def test_sets_and_snapshots(self, backends):
        db, jl = backends
        assert db.get_set("T1") == jl.get_set("T1")
        assert db.list_sets() == jl.list_sets()
        assert db.list_sets(era="朱&紫") == jl.list_sets(era="朱&紫")
        assert db.snapshots() == jl.snapshots()
        assert db.snapshots(format="open") == jl.snapshots(format="open")

    def test_legal_at(self, backends):
        db, jl = backends
        for fmt in ("standard", "open"):
            assert db.legal_at(D, fmt) == jl.legal_at(D, fmt)

    def test_effective_text(self, backends):
        db, jl = backends
        for cid, d in [("T0-001", D), ("T0-001", date(2026, 2, 1)), ("T1-001", D)]:
            assert db.effective_text(cid, d) == jl.effective_text(cid, d)

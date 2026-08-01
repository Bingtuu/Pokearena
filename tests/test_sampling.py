"""task 017 测试：A2/A3 抽样比对工具。

A2：同 seed 抽样可复现、清单含逐字段 checkbox 与小程序指引。
A3：五项机制校验的过/挂路径（prize/ACE SPEC/V-UNION/owner/进化）。
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.accept.sampling import run_a3_checks, sample_cards, write_a2_checklist
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, CardRelation, Set
from tests.test_audit import _mk_card


def _db(tmp_path: Path, cards: list[Card], relations: list[CardRelation] | None = None) -> Path:
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(Set(set_id="T1", name_zh="测试", era="测试", release_date=None,
                        regulation_mark="A", expected_count=None,
                        expected_secret_count=None, source="manual", fetched_at=""))
        for c in cards:
            session.add(c)
        for r in relations or []:
            session.add(r)
        session.commit()
    engine.dispose()
    return db_path


def _rule_box_card(card_id: str, name: str, rb: str, prize: int, **kw) -> Card:
    c = _mk_card(card_id, name, card_type="pokemon", mark="A", **kw)
    c.rule_box_type = rb
    c.has_rule_box = True
    c.prize_cards = prize
    return c


# ---- A2 抽样 ----


def test_sample_reproducible(tmp_path):
    cards = [_mk_card(f"T1-{i:03d}", f"卡{i}", mark="A") for i in range(1, 21)]
    db_path = _db(tmp_path, cards)
    a = sample_cards(db_path, 5, seed=42)
    b = sample_cards(db_path, 5, seed=42)
    assert a == b
    assert len(a) == 5
    assert len(set(a)) == 5  # 无重复


def test_a2_checklist_structure(tmp_path):
    cards = [_mk_card(f"T1-{i:03d}", f"卡{i}", mark="A") for i in range(1, 8)]
    db_path = _db(tmp_path, cards)
    out = write_a2_checklist(db_path, tmp_path / "reports", n=5, seed=42)
    text = out.read_text(encoding="utf-8")
    assert out.name.startswith("sampling-a2-")
    # 逐字段 checkbox + 小程序指引
    for field_label in ("卡名", "赛制标记", "罕贵度", "text_raw"):
        assert field_label in text
    assert "宝可梦卡牌会员" in text  # 小程序名
    assert "- [ ]" in text
    # 抽中 5 张，每张一个小节
    assert text.count("### T1-") == 5


# ---- A3 机制校验 ----


def _special_cards() -> list[Card]:
    ex = _rule_box_card("T1-101", "测试ex", "ex", 2)
    tt = _rule_box_card("T1-102", "测试TAG TEAM GX", "tag_team_gx", 3)
    ace = _mk_card("T1-103", "ACE测试", card_type="trainer", mark="A")
    ace.is_ace_spec = True
    ace.deck_limit = 1
    owner = _mk_card("T1-104", "火箭队的喵喵", card_type="pokemon", mark="A")
    owner.owner = "火箭队"
    evo = _mk_card("T1-105", "卡105", card_type="pokemon", mark="A")
    evo.evolves_from_text = "由「卡001」进化而来"
    evo.evolves_from_id = "T1-001"
    base = _mk_card("T1-001", "卡001", card_type="pokemon", mark="A")
    union_parts = []
    for i, pos in enumerate(["左上", "右上", "左下", "右下"]):
        p = _rule_box_card(f"T1-11{i}", f"合体{i}", "v_union", 3)
        p.union_position = pos
        union_parts.append(p)
    return [ex, tt, ace, owner, evo, base, *union_parts]


def _union_relations() -> list[CardRelation]:
    ids = [f"T1-11{i}" for i in range(4)]
    rels = []
    for cid in ids:
        for rid in ids:
            if cid != rid:
                rels.append(CardRelation(card_id=cid, related_card_id=rid,
                                         relation_type="union_part_of",
                                         confidence="high", source="manual"))
    return rels


def test_a3_all_pass(tmp_path):
    db_path = _db(tmp_path, _special_cards(), _union_relations())
    result = run_a3_checks(db_path)
    assert result.passed, [f for f in result.failures]
    assert result.checked >= 5


def test_a3_prize_rule_failure(tmp_path):
    bad = _rule_box_card("T1-101", "测试ex", "ex", 1)  # ex 应 2 奖赏
    db_path = _db(tmp_path, [bad])
    result = run_a3_checks(db_path)
    assert not result.passed
    assert any("prize" in f.lower() or "奖赏" in f for f in result.failures)


def test_a3_ace_spec_deck_limit_failure(tmp_path):
    ace = _mk_card("T1-103", "ACE测试", card_type="trainer", mark="A")
    ace.is_ace_spec = True
    ace.deck_limit = 4  # 应为 1
    db_path = _db(tmp_path, [ace])
    result = run_a3_checks(db_path)
    assert not result.passed
    assert any("ACE" in f for f in result.failures)


def test_a3_owner_mismatch_failure(tmp_path):
    c = _mk_card("T1-104", "莉莉艾的皮皮", card_type="pokemon", mark="A")
    c.owner = "火箭队"  # 前缀与 owner 不符
    db_path = _db(tmp_path, [c])
    result = run_a3_checks(db_path)
    assert not result.passed
    assert any("owner" in f.lower() or "归属" in f for f in result.failures)


def test_a3_union_incomplete_failure(tmp_path):
    parts = []
    for i, pos in enumerate(["左上", "右上", "左下"]):  # 缺右下
        p = _rule_box_card(f"T1-11{i}", f"合体{i}", "v_union", 3)
        p.union_position = pos
        parts.append(p)
    rels = []
    for c in parts:
        for r in parts:
            if c.card_id != r.card_id:
                rels.append(CardRelation(card_id=c.card_id, related_card_id=r.card_id,
                                         relation_type="union_part_of",
                                         confidence="high", source="manual"))
    db_path = _db(tmp_path, parts, rels)
    result = run_a3_checks(db_path)
    assert not result.passed
    assert any("V-UNION" in f or "union" in f.lower() for f in result.failures)


def test_a3_evolution_dangling_id_failure(tmp_path):
    """已解析但指向不存在的卡 → 挂（数据坏）。"""
    evo = _mk_card("T1-105", "卡105", card_type="pokemon", mark="A")
    evo.evolves_from_text = "由「卡001」进化而来"
    evo.evolves_from_id = "T1-999"
    db_path = _db(tmp_path, [evo])
    result = run_a3_checks(db_path)
    assert not result.passed
    assert any("进化" in f for f in result.failures)


def test_a3_evolution_unresolved_classified_as_notes(tmp_path):
    """未解析分两类记 notes 不挂：跨系列缺口（来源在库）/ 合理豁免（来源非库内宝可梦）。"""
    base = _mk_card("T1-001", "卡001", card_type="pokemon", mark="A")
    cross = _mk_card("T1-105", "卡105", card_type="pokemon", mark="A")
    cross.evolves_from_text = "由「卡001」进化而来"
    fossil = _mk_card("T1-106", "头盖龙", card_type="pokemon", mark="A")
    fossil.evolves_from_text = "古老的头盖化石"
    db_path = _db(tmp_path, [base, cross, fossil])
    result = run_a3_checks(db_path)
    assert result.passed
    assert any("跨系列缺口" in n for n in result.notes)
    assert any("合理未解析" in n for n in result.notes)

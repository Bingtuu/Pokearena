"""task 016 测试：A1 白名单逐卡核对器。

合成库：标记卡/白名单卡/基本能量（草/妖），快照字段手工构造。
覆盖：白名单有合法印刷（过）、无合法印刷（挂）、归组不存在（挂+诊断）、
能量双向（allowed 有卡过；词表内不在 allowed 的种类在池外过、在池内挂）。
"""

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.legal.audit import audit_format
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, LegalitySnapshot, Set

D = date(2026, 8, 1)


def _mk_card(card_id: str, name_full: str, *, mark: str | None = None,
             card_type: str = "trainer", is_basic_energy: bool = False,
             provides: list[str] | None = None) -> Card:
    return Card(
        card_id=card_id, set_id="T1", number=card_id.rsplit("-", 1)[1],
        number_display="001/100", name_full=name_full, species=None, owner=None,
        card_type=card_type, regulation_mark=mark, rarity="-", stage=None, hp=None,
        types=None, evolves_from_text=None, evolves_from_id=None, evolution_chain_id=None,
        rule_box_type=None, has_rule_box=False, is_tera=False, union_position=None,
        prize_cards=1, deck_limit=4, is_ace_spec=False, abilities=None, attacks=None,
        weakness=None, resistance=None, retreat_cost=None, trainer_subtype=None,
        provides=provides, is_basic_energy=is_basic_energy, text_raw="t",
        effect_tags=None, name_en=None, name_ja=None, name_zh_tw=None,
        source="manual", fetched_at=datetime.now(UTC), status="active",
    )


def _snapshot(fmt: str, *, marks: list[str], whitelist: list[str],
              energies: list[str]) -> LegalitySnapshot:
    return LegalitySnapshot(
        snapshot_id=f"{fmt}-2026-01-01", format=fmt,
        effective_from=date(2026, 1, 1), effective_to=None,
        allowed_marks=marks,
        allowed_basic_energy_types=energies,
        whitelist_cards=[{"name_full": n, "note": None} for n in whitelist],
        banned_cards=[], mark_overrides=[], latest_text_overrides={},
        source_url=None, created_at=datetime.now(UTC),
    )


def _db(tmp_path: Path, *, whitelist: list[str], energies: list[str],
        extra_cards: list[Card] | None = None) -> Path:
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(Set(set_id="T1", name_zh="测试", era="测试", release_date=None,
                        regulation_mark="A", expected_count=None,
                        expected_secret_count=None, source="manual", fetched_at=""))
        session.add(_mk_card("T1-001", "标记卡", mark="A"))
        session.add(_mk_card("T1-002", "测试道具"))
        session.add(_mk_card("T1-E1", "基本草能量", card_type="energy",
                             is_basic_energy=True, provides=["草"]))
        for c in extra_cards or []:
            session.add(c)
        session.add(_snapshot("standard", marks=["A"], whitelist=whitelist,
                              energies=energies))
        session.commit()
    engine.dispose()
    return db_path


def test_audit_pass(tmp_path):
    """白名单有合法印刷 + 能量双向（妖不在词表 allowed 且池外）→ 全过。"""
    db_path = _db(tmp_path, whitelist=["测试道具"], energies=["草"])
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        result = audit_format(session, "standard", D)
    engine.dispose()
    assert result.passed, [e for e in result.entries if not e.ok]
    by_name = {e.name: e for e in result.entries}
    assert by_name["测试道具"].ok
    assert by_name["能量:草"].ok
    assert by_name["能量负向:妖"].ok  # 妖不在 allowed，且池内无妖能量 → 负向通过


def test_audit_whitelist_no_legal_printing(tmp_path):
    """白名单名在库中不存在 → 挂，detail 带诊断。"""
    db_path = _db(tmp_path, whitelist=["不存在的卡"], energies=["草"])
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        result = audit_format(session, "standard", D)
    engine.dispose()
    assert not result.passed
    entry = next(e for e in result.entries if e.name == "不存在的卡")
    assert not entry.ok
    assert "归组" in entry.detail or "无合法印刷" in entry.detail


def test_audit_whitelist_grouped_name(tmp_path):
    """白名单按 name_group 匹配：卡名带前缀但归组命中 → 过。"""
    from ptcgdb.orm import CardNameGroup, NameGroup

    db_path = _db(tmp_path, whitelist=["博士的研究"], energies=["草"])
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(_mk_card("T1-003", "博士的研究（木兰博士）", mark="Z"))  # 标记不合法
        session.add(NameGroup(group_key="博士的研究", display_name="博士的研究", rule_note=None))
        session.flush()
        session.add(CardNameGroup(card_id="T1-003", group_key="博士的研究"))
        session.commit()
        result = audit_format(session, "standard", D)
    engine.dispose()
    assert next(e for e in result.entries if e.name == "博士的研究").ok


def test_audit_energy_negative_fails_when_legal(tmp_path):
    """妖不在 allowed，但妖能量卡借赛制标记混入合法池 → 负向核对挂。"""
    yao = _mk_card("T1-E2", "基本妖能量", mark="A", card_type="energy",
                   is_basic_energy=True, provides=["妖"])
    db_path = _db(tmp_path, whitelist=["测试道具"], energies=["草"],
                  extra_cards=[yao])
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        result = audit_format(session, "standard", D)
    engine.dispose()
    assert not result.passed
    entry = next(e for e in result.entries if e.name == "能量负向:妖")
    assert not entry.ok


def test_audit_energy_missing_card_fails(tmp_path):
    """allowed 里的种类库中无基本能量卡 → 挂。"""
    db_path = _db(tmp_path, whitelist=["测试道具"], energies=["草", "火"])
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        result = audit_format(session, "standard", D)
    engine.dispose()
    assert not result.passed
    entry = next(e for e in result.entries if e.name == "能量:火")
    assert not entry.ok

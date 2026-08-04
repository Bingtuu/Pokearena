"""task 026 测试：FR-8 validate_deck 核心纯函数（合法性层 + 计数层组合）。

零网络、零 DB：构造 frozen Card/LegalitySnapshot schema，经 build_pool 建池后喂
validate_deck 纯函数核。规则依据：PRD FR-8 Violation 语义全集（v1.7 定死）——
banned 与 not_legal 互斥（禁卡优先）、白名单旧卡合法、evolution_chain 预留不产生。
"""

from datetime import UTC, date, datetime

from ptcgdb.legal.deck import validate_deck
from ptcgdb.legal.engine import build_pool
from ptcgdb.schemas.models import (
    Card,
    LegalitySnapshot,
    Violation,
)

D = date(2026, 8, 1)


def make_card(
    card_id: str,
    name_full: str,
    *,
    card_type: str = "pokemon",
    regulation_mark: str | None = "G",
    rule_box_type: str | None = None,
    deck_limit: int = 4,
    is_ace_spec: bool = False,
    is_basic_energy: bool = False,
    provides: list[str] | None = None,
) -> Card:
    return Card(
        card_id=card_id, set_id="TST", number="001", number_display="001",
        name_full=name_full, species=name_full, owner=None, card_type=card_type,
        regulation_mark=regulation_mark, rarity="无", stage=None, hp=None, types=None,
        evolves_from_text=None, evolves_from_id=None, evolution_chain_id=None,
        rule_box_type=rule_box_type, has_rule_box=rule_box_type is not None,
        is_tera=False, union_position=None, prize_cards=1, deck_limit=deck_limit,
        is_ace_spec=is_ace_spec, abilities=None, attacks=None, weakness=None,
        resistance=None, retreat_cost=None, trainer_subtype=None,
        provides=provides, is_basic_energy=is_basic_energy, text_raw="",
        effect_tags=None, name_en=None, name_ja=None, name_zh_tw=None, source="test",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC), status="active",
    )


CARDS = {c.card_id: c for c in [
    make_card("T-001", "喵喵"),
    make_card("T-002", "高级球", card_type="trainer"),
    make_card("T-003", "高级球", card_type="trainer", regulation_mark="F"),  # 白名单旧卡
    make_card("T-004", "玛夏多"),                                  # 禁卡（无特性限定）
    make_card("T-005", "破罐破摔玛夏多", regulation_mark="F"),      # 禁卡 + 旧标记 → banned 优先
    make_card("T-006", "古老化石", regulation_mark="F"),            # 非白名单旧卡 → not_legal
    make_card("T-007", "大师球 ACE SPEC", card_type="trainer",
              deck_limit=1, is_ace_spec=True),
    make_card("T-008", "高级香氛 ACE SPEC", card_type="trainer",
              deck_limit=1, is_ace_spec=True),
    make_card("T-009", "光辉喷火龙", rule_box_type="radiant", deck_limit=1),
    make_card("T-010", "光辉伊布", rule_box_type="radiant", deck_limit=1),
    make_card("T-011", "莫鲁贝可V-UNION", rule_box_type="v_union", deck_limit=1),
    make_card("T-012", "莫鲁贝可V-UNION", rule_box_type="v_union", deck_limit=1),
    make_card("T-013", "基本草能量", card_type="energy", is_basic_energy=True,
              provides=["草"]),
    make_card("T-014", "基本妖能量", card_type="energy", is_basic_energy=True,
              regulation_mark=None, provides=["妖"]),  # 无标记 + 妖不在快照能量表 → not_legal
]}

GROUPS: dict[str, set[str]] = {cid: {c.name_full} for cid, c in CARDS.items()}
GROUPS["T-002"] = {"高级球"}
GROUPS["T-003"] = {"高级球"}

SNAPSHOT = LegalitySnapshot(
    snapshot_id="standard-test", format="standard",
    effective_from=date(2026, 1, 1), effective_to=None,
    allowed_marks=["G", "H", "I"], allowed_basic_energy_types=["草"],
    whitelist_cards=[{"name_full": "高级球"}],
    banned_cards=[{"name": "玛夏多"}, {"name": "破罐破摔玛夏多"}],
    mark_overrides=[], latest_text_overrides={},
    source_url="test", created_at=datetime(2026, 1, 1, tzinfo=UTC),
)

POOL = build_pool(list(CARDS.values()), GROUPS, SNAPSHOT, "standard", D)


def pad(deck: list[str]) -> list[str]:
    """补足 60 张（基本草能量填充，合法且无同名上限）。"""
    return deck + ["T-013"] * (60 - len(deck))


def check(deck: list[str]) -> list[Violation]:
    return validate_deck(deck, CARDS, GROUPS, SNAPSHOT, POOL).violations


def kinds(violations: list[Violation]) -> list[str]:
    return [v.kind for v in violations]


def test_legal_deck_ok():
    report = validate_deck(
        pad(["T-001"] * 4 + ["T-002"] * 2 + ["T-003"] * 2 + ["T-009"] + ["T-011"]),
        CARDS, GROUPS, SNAPSHOT, POOL,
    )
    assert report.ok is True
    assert report.violations == []
    assert report.deck_size == 60
    assert report.format == "standard"
    assert report.date == D
    assert report.snapshot_id == "standard-test"


def test_deck_size_59_and_61():
    v59 = check(pad(["T-001"] * 4)[:-1])
    assert kinds(v59) == ["deck_size"] and v59[0].count == 59
    v61 = check(pad(["T-001"] * 4) + ["T-001"])
    assert [v.kind for v in v61 if v.kind == "deck_size"]
    assert next(v for v in v61 if v.kind == "deck_size").count == 61


def test_name_limit_over_4():
    violations = check(pad(["T-001"] * 5))
    assert "name_limit" in kinds(violations)


def test_ace_spec_two_kinds():
    violations = check(pad(["T-007", "T-008"]))
    assert "ace_spec_limit" in kinds(violations)


def test_radiant_two():
    violations = check(pad(["T-009", "T-010"]))
    assert "radiant_limit" in kinds(violations)


def test_v_union_part_duplicated():
    violations = check(pad(["T-011"] * 2 + ["T-012"]))
    assert "name_limit" in kinds(violations)


def test_banned_card():
    violations = check(pad(["T-004"]))
    assert kinds(violations) == ["banned"]
    assert violations[0].cards == ["T-004"] and violations[0].count == 1


def test_banned_priority_over_not_legal():
    """禁卡 + 旧标记：报 banned 而非 not_legal（互斥，禁卡优先）。"""
    violations = check(pad(["T-005"]))
    assert kinds(violations) == ["banned"]


def test_not_legal_old_mark():
    violations = check(pad(["T-006"]))
    assert kinds(violations) == ["not_legal"]
    assert violations[0].cards == ["T-006"]


def test_whitelist_old_card_legal():
    """白名单旧卡（F 标记但 name_group 命中白名单）→ 无违规。"""
    assert check(pad(["T-003"] * 4)) == []


def test_basic_energy_type_not_allowed():
    violations = check(pad(["T-014"]))
    assert kinds(violations) == ["not_legal"]
    assert violations[0].cards == ["T-014"]


def test_unknown_card():
    violations = check(pad(["X-999"] * 2))
    assert kinds(violations) == ["unknown_card"]
    assert violations[0].cards == ["X-999"] and violations[0].count == 1


def test_no_evolution_chain_violation():
    """evolution_chain 为预留类型：任何卡表都不产生（PRD FR-8 v1.7）。"""
    for deck in (pad(["T-001"] * 5), pad(["X-999"]), pad(["T-004", "T-006"])):
        assert "evolution_chain" not in kinds(check(deck))


def test_multiple_violations_combined():
    """复合违规：超 4 + 禁卡 + 不合法同报，ok=False。"""
    report = validate_deck(
        pad(["T-001"] * 5 + ["T-004"] + ["T-006"]), CARDS, GROUPS, SNAPSHOT, POOL,
    )
    assert report.ok is False
    ks = kinds(report.violations)
    assert "name_limit" in ks and "banned" in ks and "not_legal" in ks

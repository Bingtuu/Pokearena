"""task 025 测试：FR-3.4 同名计数引擎（§6.2 全规则用例）。

零网络、零 DB：直接构造 frozen Card schema + groups_of 映射喂纯函数核。
规则依据：PRD v1.7 FR-3.4（双层上限 / ACE SPEC / 光辉全局 ≤1 / ◇ 同名 ≤1 /
V-UNION 部件各 1 / 基本能量豁免）。
"""

from datetime import datetime

from ptcgdb.legal.deck import check_counts
from ptcgdb.schemas.models import Card, Violation


def make_card(
    card_id: str,
    name_full: str,
    *,
    card_type: str = "pokemon",
    rule_box_type: str | None = None,
    deck_limit: int = 4,
    is_ace_spec: bool = False,
    is_basic_energy: bool = False,
) -> Card:
    return Card(
        card_id=card_id, set_id="TST", number="001", number_display="001",
        name_full=name_full, species=name_full, owner=None, card_type=card_type,
        regulation_mark="G", rarity="无", stage=None, hp=None, types=None,
        evolves_from_text=None, evolves_from_id=None, evolution_chain_id=None,
        rule_box_type=rule_box_type, has_rule_box=rule_box_type is not None,
        is_tera=False, union_position=None, prize_cards=1, deck_limit=deck_limit,
        is_ace_spec=is_ace_spec, abilities=None, attacks=None, weakness=None,
        resistance=None, retreat_cost=None, trainer_subtype=None,
        provides=["草"] if is_basic_energy else None,
        is_basic_energy=is_basic_energy, text_raw="", effect_tags=None,
        name_en=None, name_ja=None, name_zh_tw=None, source="test",
        fetched_at=datetime(2026, 1, 1), status="active",
    )


# —— 固定卡池（覆盖 §6.2 全部规则面）——

CARDS = {c.card_id: c for c in [
    make_card("T-001", "喵喵"),
    make_card("T-002", "火箭队的喵喵"),                     # owner 前缀 → 不同名
    make_card("T-003", "獒教父"),
    make_card("T-004", "獒教父ex", rule_box_type="ex"),      # ex 后缀 → 不同名
    make_card("T-005", "博士的研究（赤红的指导）", card_type="trainer"),
    make_card("T-006", "博士的研究（木兰博士）", card_type="trainer"),  # 跨插画同名
    make_card("T-007", "大师球 ACE SPEC", card_type="trainer",
              deck_limit=1, is_ace_spec=True),
    make_card("T-008", "高级香氛 ACE SPEC", card_type="trainer",
              deck_limit=1, is_ace_spec=True),
    make_card("T-009", "光辉喷火龙", rule_box_type="radiant", deck_limit=1),
    make_card("T-010", "光辉伊布", rule_box_type="radiant", deck_limit=1),
    make_card("T-011", "雪米◇", rule_box_type="prism_star", deck_limit=1),
    make_card("T-012", "烈空坐◇", rule_box_type="prism_star", deck_limit=1),
    make_card("T-013", "莫鲁贝可V-UNION", rule_box_type="v_union", deck_limit=1),  # 部件1
    make_card("T-014", "莫鲁贝可V-UNION", rule_box_type="v_union", deck_limit=1),  # 部件2
    make_card("T-015", "莫鲁贝可V-UNION", rule_box_type="v_union", deck_limit=1),  # 部件3
    make_card("T-016", "莫鲁贝可V-UNION", rule_box_type="v_union", deck_limit=1),  # 部件4
    make_card("T-017", "基本草能量", card_type="energy", is_basic_energy=True),
]}

GROUPS: dict[str, set[str]] = {cid: {c.name_full} for cid, c in CARDS.items()}
GROUPS["T-005"] = {"博士的研究"}  # 归组规则：跨插画同名 → base
GROUPS["T-006"] = {"博士的研究"}


def pad(deck: list[str], energy: str = "T-017") -> list[str]:
    """补足 60 张（基本能量填充，自身无同名上限）。"""
    return deck + [energy] * (60 - len(deck))


def kinds(violations: list[Violation]) -> list[str]:
    return [v.kind for v in violations]


def test_legal_deck_no_violations():
    deck = pad(["T-001"] * 4 + ["T-002"] * 4 + ["T-003"] * 4 + ["T-004"] * 4)
    assert check_counts(deck, CARDS, GROUPS) == []


def test_deck_size_59_and_61():
    v59 = check_counts(["T-017"] * 59, CARDS, GROUPS)
    assert kinds(v59) == ["deck_size"] and v59[0].count == 59
    v61 = check_counts(["T-017"] * 61, CARDS, GROUPS)
    assert kinds(v61) == ["deck_size"] and v61[0].count == 61


def test_unknown_card():
    v = check_counts(pad(["T-001"] * 4 + ["NOPE-001"]), CARDS, GROUPS)
    assert kinds(v) == ["unknown_card"]
    assert v[0].cards == ["NOPE-001"]


def test_name_limit_same_name_over_4():
    v = check_counts(pad(["T-001"] * 5), CARDS, GROUPS)
    assert kinds(v) == ["name_limit"]
    assert v[0].count == 5 and v[0].cards == ["T-001"]


def test_cross_illustration_same_name_merged():
    """博士的研究跨插画归组：3 + 2 = 5 > 4 → name_limit。"""
    v = check_counts(pad(["T-005"] * 3 + ["T-006"] * 2), CARDS, GROUPS)
    assert kinds(v) == ["name_limit"]
    assert v[0].count == 5 and v[0].cards == ["T-005", "T-006"]


def test_owner_prefix_not_same_name():
    v = check_counts(pad(["T-001"] * 4 + ["T-002"] * 4), CARDS, GROUPS)
    assert v == []


def test_ex_suffix_not_same_name():
    v = check_counts(pad(["T-003"] * 4 + ["T-004"] * 4), CARDS, GROUPS)
    assert v == []


def test_ace_spec_global_limit():
    """ACE SPEC 跨卡名全局 ≤1：两种各 1 → ace_spec_limit。"""
    v = check_counts(pad(["T-007", "T-008"]), CARDS, GROUPS)
    assert kinds(v) == ["ace_spec_limit"]
    assert v[0].count == 2 and v[0].cards == ["T-007", "T-008"]


def test_ace_spec_same_card_twice_double_violation():
    """同一张 ACE SPEC ×2：同名组限 1（name_limit）+ 全局 1（ace_spec_limit）。"""
    v = check_counts(pad(["T-007"] * 2), CARDS, GROUPS)
    assert kinds(v) == ["name_limit", "ace_spec_limit"]


def test_radiant_global_limit():
    """光辉跨卡名全局 ≤1：两种各 1 → radiant_limit。"""
    v = check_counts(pad(["T-009", "T-010"]), CARDS, GROUPS)
    assert kinds(v) == ["radiant_limit"]
    assert v[0].cards == ["T-009", "T-010"]


def test_prism_star_same_name_limit_but_no_global():
    """◇ 同名 ≤1；不同名 ◇ 全卡组 ≤1（全局限制）。"""
    v_same = check_counts(pad(["T-011"] * 2), CARDS, GROUPS)
    assert sorted(kinds(v_same)) == sorted(["name_limit", "prism_star_limit"])
    v_diff = check_counts(pad(["T-011", "T-012"]), CARDS, GROUPS)
    assert kinds(v_diff) == ["prism_star_limit"]


def test_v_union_parts_each_one():
    """V-UNION 四部件各 1 合法；同部件 ×2 → name_limit（单卡上限）。"""
    v_ok = check_counts(pad(["T-013", "T-014", "T-015", "T-016"]), CARDS, GROUPS)
    assert v_ok == []
    v_dup = check_counts(pad(["T-013"] * 2 + ["T-014"]), CARDS, GROUPS)
    assert kinds(v_dup) == ["name_limit"]
    assert v_dup[0].cards == ["T-013"] and v_dup[0].count == 2


def test_basic_energy_no_name_limit():
    """基本能量不受同名上限：60 张基本草能量合法。"""
    assert check_counts(["T-017"] * 60, CARDS, GROUPS) == []

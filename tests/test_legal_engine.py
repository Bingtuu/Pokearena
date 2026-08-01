"""合法性引擎测试（task 008）：FR-3.1~3.3 + A4 构造用例（合成库，零外部依赖）。"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.legal.engine import effective_text, legal_at
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import (
    Card,
    CardNameGroup,
    Errata,
    LegalitySnapshot,
    NameGroup,
    Set,
)


def _card(session, card_id, name_full, *, mark="G", group=None, card_type="pokemon",
          is_basic_energy=False, provides=None, abilities=None, attacks=None,
          is_ace_spec=False, owner=None, text_raw=None, status="active"):
    if session.get(Set, "T1") is None:
        session.add(Set(
            set_id="T1", name_zh="测试系列", era="朱&紫", release_date=None,
            regulation_mark="G", expected_count=None, expected_secret_count=None,
            source="test", fetched_at="2026-01-01",
        ))
    session.add(Card(
        card_id=card_id, set_id="T1", number=card_id.rsplit("-", 1)[1],
        number_display="001/100", name_full=name_full, species=None, owner=owner,
        card_type=card_type, regulation_mark=mark, rarity="R", stage=None, hp=None,
        types=None, evolves_from_text=None, evolves_from_id=None,
        evolution_chain_id=None, rule_box_type=None, has_rule_box=False,
        is_tera=False, union_position=None, prize_cards=1, deck_limit=4,
        is_ace_spec=is_ace_spec, abilities=abilities, attacks=attacks,
        weakness=None, resistance=None, retreat_cost=None, trainer_subtype=None,
        provides=provides, is_basic_energy=is_basic_energy,
        text_raw=text_raw if text_raw is not None else f"{name_full}的原文",
        effect_tags=None, name_en=None, name_ja=None, name_zh_tw=None,
        source="test", fetched_at=datetime.now(UTC), status=status,
    ))
    if group:
        if session.get(NameGroup, group) is None:
            session.add(NameGroup(group_key=group, display_name=group))
        session.add(CardNameGroup(card_id=card_id, group_key=group))


def _snapshot(session, snapshot_id, fmt, *, marks, energies, whitelist=(),
              banned=(), overrides=(), text_overrides=None,
              effective_from=date(2026, 1, 1), effective_to=None):
    session.add(LegalitySnapshot(
        snapshot_id=snapshot_id, format=fmt, effective_from=effective_from,
        effective_to=effective_to, allowed_marks=marks,
        allowed_basic_energy_types=energies,
        whitelist_cards=[{"name_full": n} for n in whitelist],
        banned_cards=[b for b in banned],
        mark_overrides=[{"card_id": c, "mark": m} for c, m in overrides],
        latest_text_overrides=text_overrides or {},
        source_url="test", created_at=datetime.now(UTC),
    ))


@pytest.fixture()
def session(tmp_path):
    """合成库：双赛制快照 + 覆盖全部判定路径的卡牌集。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as s:
        _snapshot(
            s, "std-1", "standard", marks=["G", "H", "I"],
            energies=["草", "火", "水", "雷", "超", "斗", "恶", "钢"],
            whitelist=["高级球", "博士的研究", "大师球"],
        )
        _snapshot(
            s, "open-1", "open", marks=list("ABCDEFGHI"),
            energies=["草", "火", "水", "雷", "超", "斗", "恶", "钢", "妖"],
            whitelist=["高级球", "博士的研究", "大师球", "离洞绳"],
            banned=[
                {"name": "玛夏多", "ability_or_attack": "破罐破摔"},
                {"name": "阿塞萝拉"},
                {"name": "全满药"},
                {"name": "高级球"},  # 合成：验证禁卡 > 白名单
            ],
        )
        _snapshot(  # 视作覆盖专用快照：只认 B
            s, "std-b", "standard", marks=["B"],
            energies=["草"], effective_from=date(2020, 1, 1),
            effective_to=date(2020, 12, 31),
            overrides=[("T1-039", "B")],
        )

        _card(s, "T1-001", "新叶喵", mark="G", group="新叶喵")
        _card(s, "T1-002", "旧搭档", mark="F", group="旧搭档")
        _card(s, "T1-003", "高级球", mark="F", group="高级球", card_type="trainer")
        # 博士的研究：两个人物/插画，同组（官方同名规则）
        _card(s, "T1-004", "博士的研究", mark="F", group="博士的研究", card_type="trainer")
        _card(s, "T1-005", "博士的研究", mark="E", group="博士的研究", card_type="trainer")
        # 基本能量：草（双赛制合法）/ 妖（仅开放）
        _card(s, "T1-006", "基本草能量", mark=None, card_type="energy",
              is_basic_energy=True, provides=["草"])
        _card(s, "T1-007", "基本妖能量", mark=None, card_type="energy",
              is_basic_energy=True, provides=["妖"])
        # 视作覆盖：T1-039 印刷标记 C 视作 B；T1-040 同名印刷无覆盖
        _card(s, "T1-039", "天空之柱", mark="C", group="天空之柱", card_type="trainer")
        _card(s, "T1-040", "天空之柱", mark="C", group="天空之柱", card_type="trainer")
        # 禁卡：玛夏多（破罐破摔 / 其他特性）、阿塞萝拉、全满药（G 标记照禁）
        _card(s, "T1-008", "玛夏多", mark="A", group="玛夏多",
              abilities=[{"name": "破罐破摔", "text": "…"}])
        _card(s, "T1-009", "玛夏多", mark="A", group="玛夏多",
              abilities=[{"name": "别的特性", "text": "…"}])
        _card(s, "T1-010", "阿塞萝拉", mark="A", group="阿塞萝拉", card_type="trainer")
        _card(s, "T1-011", "全满药", mark="G", group="全满药", card_type="trainer")
        # ACE SPEC 与普通同名不同组（§6.2）
        _card(s, "T1-012", "大师球〔ACE SPEC〕", mark="G", group="大师球〔ACE SPEC〕",
              card_type="trainer", is_ace_spec=True)
        _card(s, "T1-013", "大师球", mark="F", group="大师球", card_type="trainer")
        # owner 前缀：独立成组
        _card(s, "T1-014", "火箭队的喵喵", mark="G", group="火箭队的喵喵", owner="火箭队")
        _card(s, "T1-015", "喵喵", mark="F", group="喵喵")
        # 特殊能量（非基本、无标记）：不在白名单 → 不合法
        _card(s, "T1-016", "双重涡轮能量", mark=None, card_type="energy",
              provides=["无"], is_basic_energy=False)
        # draft 状态不入池
        _card(s, "T1-017", "草稿卡", mark="G", group="草稿卡", status="draft")
        # effective_text：旧卡 → 最新印刷 + 勘误
        _card(s, "T1-018", "高级球", mark="C", group="高级球", card_type="trainer",
              text_raw="高级球旧文本")
        _card(s, "T1-019", "高级球", mark="G", group="高级球", card_type="trainer",
              text_raw="高级球新文本")
        s.add(Errata(
            errata_id="e1", card_id="T1-019",
            effective_from=date(2026, 6, 1), corrected_text="高级球勘误文本",
        ))
        s.commit()
        yield s
    engine.dispose()


POOL_DATE = date(2026, 8, 1)


class TestLegalAtStandard:
    def test_g_mark_legal(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-001" in pool.card_ids
        assert pool.snapshot_id == "std-1"

    def test_f_mark_not_legal(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-002" not in pool.card_ids

    def test_whitelist_via_name_group(self, session):
        """白名单按 name_group 匹配，该名下全部印刷行入池（FR-3.1）。"""
        pool = legal_at(session, POOL_DATE, "standard")
        assert {"T1-003", "T1-018", "T1-019"} <= pool.card_ids  # 高级球三种印刷
        assert pool.by_name_group["高级球"] == ["T1-003", "T1-018", "T1-019"]

    def test_professors_research_cross_illustration(self, session):
        """博士的研究：不同人物/插画均视同名，全部印刷入池。"""
        pool = legal_at(session, POOL_DATE, "standard")
        assert {"T1-004", "T1-005"} <= pool.card_ids
        assert pool.by_name_group["博士的研究"] == ["T1-004", "T1-005"]

    def test_fairy_energy_not_legal_standard(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-007" not in pool.card_ids

    def test_grass_energy_legal(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-006" in pool.card_ids

    def test_ace_spec_and_plain_name_distinct(self, session):
        """大师球〔ACE SPEC〕按标记合法；普通大师球经白名单合法——两组互不相干。"""
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-012" in pool.card_ids
        assert "T1-013" in pool.card_ids  # 大师球在白名单
        assert "大师球〔ACE SPEC〕" not in pool.by_name_group

    def test_owner_prefix_independent_group(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-014" in pool.card_ids  # 火箭队的喵喵 G
        assert "T1-015" not in pool.card_ids  # 喵喵 F，不同组不沾染

    def test_special_energy_not_legal(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-016" not in pool.card_ids

    def test_draft_not_in_pool(self, session):
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-017" not in pool.card_ids


class TestLegalAtOpen:
    def test_fairy_energy_legal_open(self, session):
        pool = legal_at(session, POOL_DATE, "open")
        assert "T1-007" in pool.card_ids

    def test_f_mark_legal_open(self, session):
        pool = legal_at(session, POOL_DATE, "open")
        assert "T1-002" in pool.card_ids

    def test_open_whitelist_sample(self, session):
        """开放赛制白名单抽样：离洞绳（开放多出 6 种之一）。"""
        _card(session, "T1-020", "离洞绳", mark="D", group="离洞绳", card_type="trainer")
        session.commit()
        pool = legal_at(session, POOL_DATE, "open")
        assert "T1-020" in pool.card_ids
        pool_std = legal_at(session, POOL_DATE, "standard")
        assert "T1-020" not in pool_std.card_ids

    def test_ban_beats_mark(self, session):
        """禁卡表优先于赛制标记：G 标记的全满药照样不合法。"""
        pool = legal_at(session, POOL_DATE, "open")
        assert "T1-011" not in pool.card_ids

    def test_ban_beats_whitelist(self, session):
        """禁卡表优先于白名单。"""
        pool = legal_at(session, POOL_DATE, "open")
        assert "T1-003" not in pool.card_ids  # 高级球：白名单但被禁
        assert "高级球" not in pool.by_name_group

    def test_ban_with_ability_qualifier(self, session):
        """玛夏多：特性破罐破摔的禁，其他特性的不禁。"""
        pool = legal_at(session, POOL_DATE, "open")
        assert "T1-008" not in pool.card_ids
        assert "T1-009" in pool.card_ids
        assert "T1-010" not in pool.card_ids  # 阿塞萝拉无条件禁


class TestMarkOverride:
    def test_override_makes_legal_same_name_other_print_not(self, session):
        """视作B 覆盖：被覆盖印刷合法，同名其他印刷不合法（A4）。"""
        pool = legal_at(session, date(2020, 6, 1), "standard")
        assert pool.snapshot_id == "std-b"
        assert "T1-039" in pool.card_ids
        assert "T1-040" not in pool.card_ids

    def test_override_not_used_when_snapshot_absent(self, session):
        """当前快照（G/H/I）下，视作B 的天空之柱不合法（B 不在 allowed_marks）。"""
        pool = legal_at(session, POOL_DATE, "standard")
        assert "T1-039" not in pool.card_ids
        assert "T1-040" not in pool.card_ids


class TestSnapshotSelection:
    def test_no_snapshot_raises(self, session):
        with pytest.raises(LookupError):
            legal_at(session, date(2019, 1, 1), "standard")

    def test_unknown_format_raises(self, session):
        with pytest.raises(LookupError):
            legal_at(session, POOL_DATE, "expanded")


class TestEffectiveText:
    def test_errata_beats_latest_print(self, session):
        et = effective_text(session, "T1-019", POOL_DATE)
        assert et.text == "高级球勘误文本"
        assert et.source == "errata"
        assert et.resolved_card_id == "T1-019"

    def test_latest_print_override(self, tmp_path, session):
        """latest_text_overrides：旧卡解析到最新印刷文本。"""
        snap = session.query(LegalitySnapshot).filter_by(snapshot_id="std-1").one()
        snap.latest_text_overrides = {"T1-018": "T1-019"}
        session.commit()
        # 勘误生效日前：解析到新印刷原文
        et = effective_text(session, "T1-018", date(2026, 2, 1))
        assert et.text == "高级球新文本"
        assert et.source == "latest_print"
        assert et.card_id == "T1-018"
        assert et.resolved_card_id == "T1-019"

    def test_raw_fallback(self, session):
        et = effective_text(session, "T1-001", POOL_DATE)
        assert et.text == "新叶喵的原文"
        assert et.source == "text_raw"
        assert et.resolved_card_id == "T1-001"

    def test_errata_respects_effective_date(self, session):
        """勘误生效日前查询：不受未来勘误影响。"""
        et = effective_text(session, "T1-019", date(2026, 2, 1))
        assert et.text == "高级球新文本"
        assert et.source == "text_raw"

"""接受验收模块覆盖率补充测试（task 030 后续）。

覆盖 runner.py 和 sampling.py 中现有测试未触及的分支与边界：
- _run_a1：白名单逐卡检查 / 空白名单 / 无快照跳过
- _run_a4：妖能量二分边界（标准池 0 / 开放池有 / 妖入标准池则挂）
- _run_a5：冻结守卫触发 / 无 standard 快照不假过
- _run_a8：双后端一致 / SDK 异常 → 契约失败
- _check_union：V-UNION 正常组 / checked 计数不膨胀
- write_a2_checklist：100 张 seed 可复现
- write_a3_report：自动校验结果写入报告
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.accept.runner import (
    _run_a1,
    _run_a4,
    _run_a5,
    _run_a8,
)
from ptcgdb.accept.sampling import (
    A3Result,
    _check_union,
    run_a3_checks,
    write_a2_checklist,
    write_a3_report,
)
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, CardRelation, LegalitySnapshot, Meta, Set
from tests.test_audit import _mk_card, _snapshot

# ── helpers ──────────────────────────────────────────────────────────


def _db_with_snapshots(
    tmp_path: Path,
    *,
    standard_snapshot: LegalitySnapshot | None = None,
    open_snapshot: LegalitySnapshot | None = None,
    extra_cards: list[Card] | None = None,
) -> Path:
    """创建含 sets / cards / snapshots 的最小合成库。"""
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
        if standard_snapshot:
            session.add(standard_snapshot)
        if open_snapshot:
            session.add(open_snapshot)
        session.merge(Meta(key="schema_version", value="1.0.0"))
        session.merge(Meta(key="data_version", value="v20260801.1"))
        session.commit()
    engine.dispose()
    return db_path


def _std_snapshot(whitelist=None, energies=None) -> LegalitySnapshot:
    return _snapshot("standard", marks=["A"],
                     whitelist=whitelist or ["测试道具"],
                     energies=energies or ["草"])


def _open_snapshot(whitelist=None, energies=None) -> LegalitySnapshot:
    return _snapshot("open", marks=["A"],
                     whitelist=whitelist or ["测试道具"],
                     energies=energies or ["草", "妖"])


# ── A1: 白名单逐卡核对 ─────────────────────────────────────────────


def test_run_a1_whitelist_pass(tmp_path):
    """白名单卡在库且有合法印刷 → A1 通过。"""
    db_path = _db_with_snapshots(tmp_path, standard_snapshot=_std_snapshot())
    sec = _run_a1(db_path, date(2026, 8, 1))
    assert sec.passed
    assert any("standard" in line for line in sec.lines)


def test_run_a1_empty_whitelist(tmp_path):
    """空白名单 → 无条目可失败，A1 应通过。"""
    db_path = _db_with_snapshots(
        tmp_path,
        standard_snapshot=_std_snapshot(whitelist=[]),
    )
    sec = _run_a1(db_path, date(2026, 8, 1))
    assert sec.passed


def test_run_a1_no_snapshot_skips(tmp_path):
    """某赛制无当前快照 → 跳过该赛制，不影响整体通过。"""
    db_path = _db_with_snapshots(tmp_path, standard_snapshot=_std_snapshot())
    sec = _run_a1(db_path, date(2026, 8, 1))
    assert sec.passed
    # open 无快照 → 应出现"无当前快照，跳过"
    assert any("open" in line and "跳过" in line for line in sec.lines)


# ── A4: 妖能量二分 ──────────────────────────────────────────────────


def test_run_a4_fairy_boundary_correct(tmp_path):
    """妖能量在开放池、不在标准池 → 二分正确，A4 通过。"""
    yao = _mk_card("T1-E2", "基本妖能量", card_type="energy",
                   is_basic_energy=True, provides=["妖"])
    db_path = _db_with_snapshots(
        tmp_path,
        standard_snapshot=_std_snapshot(),
        open_snapshot=_open_snapshot(),
        extra_cards=[yao],
    )
    sec = _run_a4(db_path, date(2026, 8, 1))
    assert sec.passed
    assert any("二分正确" in line for line in sec.lines)


def test_run_a4_fairy_in_standard_fails(tmp_path):
    """妖能量在标准池 → A4 挂。"""
    yao = _mk_card("T1-E2", "基本妖能量", mark="A", card_type="energy",
                   is_basic_energy=True, provides=["妖"])
    db_path = _db_with_snapshots(
        tmp_path,
        standard_snapshot=_std_snapshot(energies=["草", "妖"]),
        open_snapshot=_open_snapshot(),
        extra_cards=[yao],
    )
    sec = _run_a4(db_path, date(2026, 8, 1))
    assert not sec.passed
    assert any("妖能量出现在标准池" in line for line in sec.lines)


# ── A5: 冻结守卫 + old_id=None 不假过 ──────────────────────────────


def test_run_a5_freeze_guard_triggered(tmp_path):
    """正常流程：提案 apply → 新快照生效 + 旧快照闭合 + 冻结守卫拒绝写入。"""
    db_path = _db_with_snapshots(tmp_path, standard_snapshot=_std_snapshot())
    work_dir = tmp_path / "work"
    sec = _run_a5(db_path, work_dir)
    assert sec.passed, sec.lines
    assert any("新快照生效" in line and "✓" in line for line in sec.lines)
    assert any("旧快照闭合" in line and "✓" in line for line in sec.lines)
    assert any("冻结守卫拒绝" in line and "✓" in line for line in sec.lines)


def test_run_a5_no_standard_snapshot_fails(tmp_path):
    """库中无 standard 快照 → _write_future_proposal 抛 LookupError → A5 挂。"""
    db_path = _db_with_snapshots(tmp_path, open_snapshot=_open_snapshot())
    work_dir = tmp_path / "work"
    sec = _run_a5(db_path, work_dir)
    assert not sec.passed
    assert any("异常" in line for line in sec.lines)


# ── A8: SDK 双后端契约 ─────────────────────────────────────────────


def _mock_backend(cards=None, pool_size=3):
    """构造一个双后端 mock（open_db / open_jsonl 返回相同数据）。"""
    from ptcgdb.schemas.models import Card as CardSchema
    from ptcgdb.schemas.models import EffectiveText, LegalityPool

    cards = cards or [
        CardSchema(card_id="T1-001", set_id="T1", number="001",
                   number_display="001/100", name_full="标记卡", species=None,
                   owner=None, card_type="trainer", regulation_mark="A",
                   rarity="-", stage=None, hp=None, types=None,
                   evolves_from_text=None, evolves_from_id=None,
                   evolution_chain_id=None, rule_box_type=None,
                   has_rule_box=False, is_tera=False, union_position=None,
                   prize_cards=1, deck_limit=4, is_ace_spec=False,
                   abilities=None, attacks=None, weakness=None,
                   resistance=None, retreat_cost=None, trainer_subtype=None,
                   provides=None, is_basic_energy=False, text_raw="t",
                   effect_tags=None, name_en=None, name_ja=None, name_zh_tw=None,
                   source="manual", fetched_at=datetime.now(UTC),
                   status="active"),
        CardSchema(card_id="T1-002", set_id="T1", number="002",
                   number_display="002/100", name_full="测试道具", species=None,
                   owner=None, card_type="trainer", regulation_mark=None,
                   rarity="-", stage=None, hp=None, types=None,
                   evolves_from_text=None, evolves_from_id=None,
                   evolution_chain_id=None, rule_box_type=None,
                   has_rule_box=False, is_tera=False, union_position=None,
                   prize_cards=1, deck_limit=4, is_ace_spec=False,
                   abilities=None, attacks=None, weakness=None,
                   resistance=None, retreat_cost=None, trainer_subtype=None,
                   provides=None, is_basic_energy=False, text_raw="t",
                   effect_tags=None, name_en=None, name_ja=None, name_zh_tw=None,
                   source="manual", fetched_at=datetime.now(UTC),
                   status="active"),
    ]
    pool = LegalityPool(
        snapshot_id="std-2026-01-01", format="standard", date=date(2026, 8, 1),
        card_ids=frozenset(c.card_id for c in cards),
        by_name_group={},
    )
    et = EffectiveText(
        card_id=cards[0].card_id, resolved_card_id=cards[0].card_id,
        text="t", source="text_raw",
    )

    by_id = {c.card_id: c for c in cards}
    backend = MagicMock()
    backend.schema_version = "1.0.0"
    backend.get_card.side_effect = lambda card_id: by_id.get(card_id)
    backend.search_cards.return_value = cards[:pool_size]
    backend.legal_at.return_value = pool
    backend.effective_text.return_value = et

    cm = MagicMock()
    cm.__enter__.return_value = backend
    cm.__exit__.return_value = None
    return cm


def test_run_a8_dual_backend_equality(tmp_path):
    """open_db 与 open_jsonl 返回同一数据 → A8 通过。"""
    db_path = _db_with_snapshots(tmp_path, standard_snapshot=_std_snapshot(),
                                  open_snapshot=_open_snapshot())
    work_dir = tmp_path / "work"
    dist = work_dir / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "manifest.json").write_text('{"version":"v1","schema_version":"1.0.0"}')

    mock_cm = _mock_backend(pool_size=3)

    with patch("ptcgdb.accept.runner.open_db", return_value=mock_cm), \
         patch("ptcgdb.accept.runner.open_jsonl", return_value=mock_cm):
        sec = _run_a8(db_path, work_dir, date(2026, 8, 1))

    assert sec.passed, sec.lines
    assert any("schema_version 一致" in line for line in sec.lines)
    assert any("get_card" in line and "一致" in line for line in sec.lines)


def test_run_a8_sdk_exception_contract_failure(tmp_path):
    """open_db 抛出异常 → 契约失败，A8 挂且如实记录异常类型。"""
    db_path = _db_with_snapshots(tmp_path, standard_snapshot=_std_snapshot(),
                                  open_snapshot=_open_snapshot())
    work_dir = tmp_path / "work"
    dist = work_dir / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "manifest.json").write_text('{"version":"v1","schema_version":"1.0.0"}')

    with patch("ptcgdb.accept.runner.open_db", side_effect=ValueError("boom")), \
         patch("ptcgdb.accept.runner.open_jsonl", side_effect=ValueError("boom")):
        sec = _run_a8(db_path, work_dir, date(2026, 8, 1))

    assert not sec.passed
    assert any("ValueError" in line for line in sec.lines)


# ── _check_union: V-UNION 组校验 ────────────────────────────────────


def _union_db(tmp_path: Path, cards: list[Card], rels: list[CardRelation]) -> Path:
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(Set(set_id="T1", name_zh="测试", era="测试", release_date=None,
                        regulation_mark="A", expected_count=None,
                        expected_secret_count=None, source="manual", fetched_at=""))
        for c in cards:
            session.add(c)
        for r in rels:
            session.add(r)
        session.commit()
    engine.dispose()
    return db_path


def _union_card(card_id: str, position: str) -> Card:
    c = _mk_card(card_id, f"合体{card_id[-1]}", mark="A", card_type="pokemon")
    c.rule_box_type = "v_union"
    c.has_rule_box = True
    c.prize_cards = 3
    c.union_position = position
    return c


def _union_relations(card_ids: list[str]) -> list[CardRelation]:
    rels = []
    for cid in card_ids:
        for rid in card_ids:
            if cid != rid:
                rels.append(CardRelation(card_id=cid, related_card_id=rid,
                                         relation_type="union_part_of",
                                         confidence="high", source="manual"))
    return rels


def test_check_union_normal_group(tmp_path):
    """V-UNION 四部件方位齐全、关系完备 → 通过。"""
    ids = ["T1-110", "T1-111", "T1-112", "T1-113"]
    positions = ["左上", "右上", "左下", "右下"]
    cards = [_union_card(cid, pos) for cid, pos in zip(ids, positions, strict=False)]
    rels = _union_relations(ids)
    db_path = _union_db(tmp_path, cards, rels)

    result = run_a3_checks(db_path)
    union_failures = [f for f in result.failures if "V-UNION" in f or "union" in f.lower()]
    assert not union_failures, union_failures


def test_check_union_checked_count_no_inflate(tmp_path):
    """四部件 V-UNION：checked 计数等于部件数，不膨胀。"""
    ids = ["T1-110", "T1-111", "T1-112", "T1-113"]
    positions = ["左上", "右上", "左下", "右下"]
    cards = [_union_card(cid, pos) for cid, pos in zip(ids, positions, strict=False)]
    rels = _union_relations(ids)
    db_path = _union_db(tmp_path, cards, rels)

    # 直接调用 _check_union 精确控制被测范围
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        all_cards = session.query(Card).all()
        res = A3Result()
        _check_union(all_cards, session, res)
    engine.dispose()

    # 4 张 V-UNION 卡 → checked 应为 4，不因连通分量遍历重复计数
    assert res.checked == 4, f"checked={res.checked}, expected 4"
    assert res.passed


# ── A2: 抽样清单 seed 可复现 ────────────────────────────────────────


def test_write_a2_checklist_seed_reproducibility(tmp_path):
    """100 张卡固定 seed → 两次产出相同清单。"""
    cards = [_mk_card(f"T1-{i:03d}", f"卡{i}", mark="A") for i in range(1, 101)]
    db_path = _union_db(tmp_path, cards, [])

    out1 = write_a2_checklist(db_path, tmp_path / "r1", n=100, seed=42)
    out2 = write_a2_checklist(db_path, tmp_path / "r2", n=100, seed=42)
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")

    # 不同 seed → 不同清单
    out3 = write_a2_checklist(db_path, tmp_path / "r3", n=100, seed=99)
    assert out1.read_text(encoding="utf-8") != out3.read_text(encoding="utf-8")


# ── A3: 报告含自动校验 ──────────────────────────────────────────────


def test_write_a3_report_includes_auto_validation(tmp_path):
    """A3 报告包含自动校验结果段落。"""
    # 构造含特殊卡的库：ex（奖赏正确）+ ACE SPEC + owner 卡 + 进化链
    ex = _mk_card("T1-101", "测试ex", mark="A", card_type="pokemon")
    ex.rule_box_type = "ex"
    ex.has_rule_box = True
    ex.prize_cards = 2

    ace = _mk_card("T1-103", "ACE测试", card_type="trainer", mark="A")
    ace.is_ace_spec = True
    ace.deck_limit = 1

    owner = _mk_card("T1-104", "火箭队的喵喵", card_type="pokemon", mark="A")
    owner.owner = "火箭队"

    base = _mk_card("T1-001", "卡001", card_type="pokemon", mark="A")
    evo = _mk_card("T1-105", "卡105", card_type="pokemon", mark="A")
    evo.evolves_from_text = "由「卡001」进化而来"
    evo.evolves_from_id = "T1-001"

    db_path = _union_db(tmp_path, [ex, ace, owner, base, evo], [])

    out = write_a3_report(db_path, tmp_path / "reports", n=3, seed=42,
                          today=date(2026, 8, 1))
    text = out.read_text(encoding="utf-8")

    # 报告应含自动校验结果
    assert "自动一致性校验" in text
    assert "校验项次" in text
    # 应含抽样核对清单
    assert "卡面人工核对清单" in text
    assert out.name.startswith("sampling-a3-")

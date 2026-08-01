"""task 016 测试：验收 runner 端到端（合成库）。

合成一个"小而全"的库：标记卡/白名单卡/草妖基本能量 + 双赛制快照，
run_acceptance 应七节全过并产出 markdown 证据报告。
A5/A6 在 work_dir 副本上操作，源库不被改动（校验源库卡片数不变）。
"""

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.accept.runner import run_acceptance
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, Meta, Set
from tests.test_audit import _mk_card, _snapshot  # 复用合成卡/快照构造


def _build_full_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "real.db"
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
        session.add(_mk_card("T1-E2", "基本妖能量", card_type="energy",
                             is_basic_energy=True, provides=["妖"]))
        session.add(_snapshot("standard", marks=["A"], whitelist=["测试道具"],
                              energies=["草"]))
        session.add(_snapshot("open", marks=["A"], whitelist=["测试道具"],
                              energies=["草", "妖"]))
        session.merge(Meta(key="schema_version", value="1.0.0"))
        session.merge(Meta(key="data_version", value="v20260801.1"))
        session.commit()
    engine.dispose()
    return db_path


def _card_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    conn.close()
    return n


def test_run_acceptance_all_pass(tmp_path):
    db_path = _build_full_db(tmp_path)
    before = _card_count(db_path)
    report = run_acceptance(db_path, tmp_path / "reports", tmp_path / "work")

    assert report.passed, [(s.aid, s.lines) for s in report.sections if not s.passed]
    assert [s.aid for s in report.sections] == ["A1", "A4", "A5", "A6", "A7", "A8"]
    # 源库只读：验收前后卡片数一致
    assert _card_count(db_path) == before
    # 报告落盘，含七节标题与 PASS 标记
    text = report.path.read_text(encoding="utf-8")
    for aid in ("A1", "A4", "A5", "A6", "A7", "A8"):
        assert f"## {aid}" in text
    assert "FAIL" not in text


def test_run_acceptance_report_records_failure(tmp_path):
    """A1 不符项不伪造通过：删掉白名单卡 → A1 FAIL 且其余节照常跑完。"""
    db_path = _build_full_db(tmp_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        card = session.get(Card, "T1-002")
        session.delete(card)
        session.commit()
    engine.dispose()

    report = run_acceptance(db_path, tmp_path / "reports", tmp_path / "work")
    assert not report.passed
    by_aid = {s.aid: s for s in report.sections}
    assert not by_aid["A1"].passed
    assert "测试道具" in "\n".join(by_aid["A1"].lines)
    assert by_aid["A6"].passed  # 其余节不受影响
    text = report.path.read_text(encoding="utf-8")
    assert "FAIL" in text

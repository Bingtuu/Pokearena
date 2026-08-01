"""task 015 测试：L2 勘误导入（FR-5.3）+ 提案闭环。

errata：config/errata/*.yml → errata 表 upsert 幂等；缺卡 warning 跳过；
引擎 effective_text 联测消费。闭环：list_proposals → legal-apply → status=applied。
"""

import shutil
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.legal.engine import effective_text
from ptcgdb.legal.errata import import_errata
from ptcgdb.legal.versions import apply_snapshot
from ptcgdb.migrations import apply_migrations
from ptcgdb.monitor.proposals import list_proposals, mark_proposal_applied
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Errata
from ptcgdb.scrapers.raw_store import write_raw

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
SET_ID = "CSM1aC"


def _db_with_card(tmp_path: Path) -> Path:
    """用真实 fixture 入一张卡（CSM1aC-001），供 errata.card_id 外键引用。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / SET_ID
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "001.json", set_dir / "001.json")
    write_raw(set_dir / "cards.json", {
        "code": 200,
        "data": {"name": "横空出世 赫", "setCode": SET_ID, "setId": SET_ID,
                 "releaseDate": "2022-10-28T00:00:00+08:00", "series": "Sun & Moon",
                 "mainExpansion": True, "cardsNum": 1, "cards": []},
        "msg": "OK.",
    }, source="mik_moe")
    db_path = tmp_path / "test.db"
    ingest_set(raw_dir, SET_ID, db_path)
    return db_path


def _write_errata(config_dir: Path, entries: list[dict]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    for e in entries:
        (config_dir / f"{e['errata_id']}.yml").write_text(
            yaml.safe_dump(e, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


# ---- errata 导入 ----


def test_import_errata_upsert_idempotent(tmp_path):
    db_path = _db_with_card(tmp_path)
    config_dir = tmp_path / "errata"
    entry = {
        "errata_id": "2026-08-01-csm1ac-001",
        "card_id": f"{SET_ID}-001",
        "effective_from": "2026-08-01",
        "corrected_text": "【勘误】正确文本",
        "notice_url": "https://www.pokemon.cn/tcg/card/1.html",
    }
    _write_errata(config_dir, [entry])

    result = import_errata(db_path, config_dir)
    assert result.imported == ["2026-08-01-csm1ac-001"]
    assert result.warnings == []

    # 重跑幂等（upsert，不重复）
    result2 = import_errata(db_path, config_dir)
    assert result2.imported == ["2026-08-01-csm1ac-001"]
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        rows = session.scalars(select(Errata)).all()
        assert len(rows) == 1
        assert rows[0].corrected_text == "【勘误】正确文本"
        assert rows[0].effective_from == date(2026, 8, 1)
    engine.dispose()


def test_import_errata_missing_card_warns(tmp_path):
    db_path = _db_with_card(tmp_path)
    config_dir = tmp_path / "errata"
    _write_errata(config_dir, [{
        "errata_id": "e1", "card_id": "NOPE-999",
        "effective_from": "2026-08-01", "corrected_text": "x", "notice_url": None,
    }])
    result = import_errata(db_path, config_dir)
    assert result.imported == []
    assert len(result.warnings) == 1
    assert "NOPE-999" in result.warnings[0]
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.scalars(select(Errata)).all() == []
    engine.dispose()


def test_imported_errata_consumed_by_effective_text(tmp_path):
    """联测：导入的勘误被引擎 effective_text 消费（优先级 勘误 > 印刷文本）。"""
    db_path = _db_with_card(tmp_path)
    config_dir = tmp_path / "errata"
    _write_errata(config_dir, [{
        "errata_id": "e1", "card_id": f"{SET_ID}-001",
        "effective_from": "2026-08-01", "corrected_text": "【勘误】正确文本",
        "notice_url": None,
    }])
    import_errata(db_path, config_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        et = effective_text(session, f"{SET_ID}-001", date(2026, 8, 2))
        assert et.text == "【勘误】正确文本"
        assert et.source == "errata"
        # 生效日前：回退印刷文本
        et_before = effective_text(session, f"{SET_ID}-001", date(2026, 7, 1))
        assert et_before.source != "errata"
    engine.dispose()


# ---- 提案闭环 ----


def _write_proposal(proposals_dir: Path, name: str, doc: dict) -> Path:
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / name
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _proposal_doc(status: str = "pending_review") -> dict:
    return {
        "snapshot_id": "standard-2026-09-16",
        "format": "standard",
        "effective_from": "2026-09-16",
        "allowed_marks": ["H", "I", "J"],
        "allowed_basic_energy_types": ["草", "火"],
        "whitelist_cards": [],
        "banned_cards": [],
        "mark_overrides": [],
        "status": status,
        "diff": {"allowed_marks": {"old": ["G", "H", "I"], "new": ["H", "I", "J"]}},
    }


def test_list_proposals(tmp_path):
    proposals_dir = tmp_path / "proposals"
    _write_proposal(proposals_dir, "20260801_standard-2026-09-16.yaml", _proposal_doc())
    _write_proposal(
        proposals_dir, "20260802_manual.yaml", {**_proposal_doc("needs_manual"),
                                                "snapshot_id": "manual-2026-08-02"}
    )
    rows = list_proposals(proposals_dir)
    assert len(rows) == 2
    by_id = {r["snapshot_id"]: r for r in rows}
    assert by_id["standard-2026-09-16"]["status"] == "pending_review"
    assert by_id["manual-2026-08-02"]["status"] == "needs_manual"
    assert list_proposals(tmp_path / "不存在") == []


def test_apply_then_mark_applied(tmp_path):
    """闭环：legal-apply 成功 → mark_proposal_applied 回写 status=applied。"""
    proposals_dir = tmp_path / "proposals"
    path = _write_proposal(proposals_dir, "20260801_standard-2026-09-16.yaml", _proposal_doc())

    # 备一个含当前快照的库（当前快照生效日必须早于新快照）
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    from datetime import UTC, datetime

    from ptcgdb.orm import LegalitySnapshot
    with Session(engine) as session:
        session.add(LegalitySnapshot(
            snapshot_id="standard-2026-07-16", format="standard",
            effective_from=date(2026, 7, 16), effective_to=None,
            allowed_marks=["G", "H", "I"], allowed_basic_energy_types=["草", "火"],
            whitelist_cards=[], banned_cards=[], mark_overrides=[],
            latest_text_overrides={}, source_url=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()
    engine.dispose()

    sid = apply_snapshot(
        db_path, path, changelog_path=tmp_path / "CHANGELOG.md",
        versions_dir=tmp_path / "versions",
    )
    mark_proposal_applied(path, sid)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["status"] == "applied"
    assert doc["applied_snapshot_id"] == "standard-2026-09-16"
    assert "applied_at" in doc
    # list_proposals 反映新状态
    rows = list_proposals(proposals_dir)
    assert rows[0]["status"] == "applied"

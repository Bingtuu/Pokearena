"""导出七件套测试（task 010）：A7——文件齐全、checksum 校验、JSONL 流式、legality 结构。"""

import hashlib
import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.export.exporter import EXPORT_FILES, export_all
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import (
    Card,
    CardNameGroup,
    CardRelation,
    LegalitySnapshot,
    Meta,
    NameGroup,
    Set,
)


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "t.db"
    apply_migrations(path)
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        s.add(Set(
            set_id="T1", name_zh="测试系列", era="朱&紫", release_date=date(2026, 1, 1),
            regulation_mark="G", expected_count=100, expected_secret_count=5,
            source="test", fetched_at="2026-01-01",
        ))
        for i, cid in enumerate(["T1-001", "T1-002"]):
            s.add(Card(
                card_id=cid, set_id="T1", number=f"00{i + 1}", number_display=f"00{i + 1}/100",
                name_full=f"卡{i}", species=None, owner=None, card_type="pokemon",
                regulation_mark="G", rarity="R", stage=None, hp=60, types=["草"],
                evolves_from_text=None, evolves_from_id=None, evolution_chain_id=None,
                rule_box_type=None, has_rule_box=False, is_tera=False,
                union_position=None, prize_cards=1, deck_limit=4, is_ace_spec=False,
                abilities=None, attacks=None, weakness=None, resistance=None,
                retreat_cost=1, trainer_subtype=None, provides=None,
                is_basic_energy=False, text_raw=f"卡{i}原文", effect_tags=None,
                name_en=None, name_ja=None, name_zh_tw=None, source="test",
                fetched_at=datetime.now(UTC), status="active",
            ))
        s.add(NameGroup(group_key="卡0", display_name="卡0"))
        s.add(CardNameGroup(card_id="T1-001", group_key="卡0"))
        s.add(CardRelation(
            card_id="T1-002", related_card_id="T1-001",
            relation_type="evolves_from", confidence="high", source="test",
        ))
        s.add(LegalitySnapshot(
            snapshot_id="standard-1", format="standard",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=["G"], allowed_basic_energy_types=["草"],
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


def test_all_files_present(dist):
    for name in EXPORT_FILES:
        assert (dist / name).is_file(), f"缺 {name}"


def test_manifest(dist):
    m = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    assert m["version"] == "v20260801.1"
    assert m["schema_version"] == "1.0.0"
    assert m["built_at"]
    assert len(m["db_sha256"]) == 64
    assert m["counts"]["cards"] == 2
    assert m["counts"]["sets"] == 1
    assert m["counts"]["snapshots"] == 1


def test_checksums_verify(dist):
    lines = (dist / "checksums.sha256").read_text(encoding="utf-8").strip().split("\n")
    entries = dict(reversed(line.split("  ")) for line in lines)
    for name, digest in entries.items():
        actual = hashlib.sha256((dist / name).read_bytes()).hexdigest()
        assert actual == digest, f"{name} checksum 不符"
    assert "checksums.sha256" not in entries  # 不自签


def test_cards_jsonl_streamable(dist):
    rows = []
    with (dist / "cards.jsonl").open(encoding="utf-8") as f:
        for line in f:  # 下游流式读取方式
            rows.append(json.loads(line))
    assert len(rows) == 2
    assert rows[0]["card_id"] == "T1-001"
    assert rows[0]["text_raw"] == "卡0原文"  # 逐字保留
    raw_text = (dist / "cards.jsonl").read_text(encoding="utf-8")
    assert "卡0原文" in raw_text  # UTF-8 直写，不做 ascii 转义


def test_sets_and_relations_jsonl(dist):
    sets = [json.loads(x) for x in (dist / "sets.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sets[0]["set_id"] == "T1"
    rels = [
        json.loads(x)
        for x in (dist / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    kinds = {r["kind"] for r in rels}
    assert kinds == {"card_relation", "name_group", "cards_name_group"}
    assert any(r["kind"] == "card_relation" and r["relation_type"] == "evolves_from" for r in rels)


def test_legality_json_structure(dist):
    data = json.loads((dist / "legality.json").read_text(encoding="utf-8"))
    assert set(data) == {"meta", "data"}
    assert data["meta"]["schema_version"] == "1.0.0"
    assert set(data["data"]) == {"snapshots", "errata"}
    snaps = data["data"]["snapshots"]
    assert len(snaps) == 1
    s = snaps[0]
    assert s["snapshot_id"] == "standard-1"
    assert s["allowed_marks"] == ["G"]
    assert s["whitelist_cards"] == [{"name_full": "高级球"}]
    assert isinstance(data["data"]["errata"], list)


def test_db_copy_and_schema_md(dist, db_path):
    assert hashlib.sha256((dist / "ptcg-cn.db").read_bytes()).hexdigest() == (
        hashlib.sha256(db_path.read_bytes()).hexdigest()
    )
    md = (dist / "schema.md").read_text(encoding="utf-8")
    assert "Card" in md and "LegalitySnapshot" in md
    assert "card_id" in md


def test_export_rerun_overwrites(db_path, tmp_path):
    """重跑幂等：重复导出同目录不报错、文件数不变。"""
    out = tmp_path / "dist"
    export_all(db_path, out)
    export_all(db_path, out)
    assert len(list(out.iterdir())) == len(EXPORT_FILES)

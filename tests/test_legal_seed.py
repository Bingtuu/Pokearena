"""环境快照种子（task 007）：种子文件完整性 + 入库幂等 + upsert 语义。"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.legal.seed import SnapshotSeed, load_seeds, seed_snapshots
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import LegalitySnapshot

CONFIG_DIR = Path("config/legality")


def _seeds() -> dict[str, SnapshotSeed]:
    return {s.snapshot_id: s for s in load_seeds(CONFIG_DIR)}


def test_seed_files_match_official_counts():
    """种子计数与官方赛制页（2026-07-16）逐项一致。"""
    seeds = _seeds()
    std, opn = seeds["standard-2026-07-16"], seeds["open-2026-07-16"]

    assert std.format == "standard" and opn.format == "open"
    assert std.effective_from == date(2026, 7, 16)
    assert opn.effective_from == date(2026, 7, 16)

    # 标准：G/H/I + 8 能量（不含妖）+ 44 白名单（18 特典 + 26 旧卡）+ 无禁卡
    assert std.allowed_marks == ["G", "H", "I"]
    assert len(std.allowed_basic_energy_types) == 8
    assert "妖" not in std.allowed_basic_energy_types
    assert len(std.whitelist_cards) == 44
    assert std.banned_cards == []

    # 开放：A~I 全标记 + 9 能量（含妖）+ 50 白名单（18 特典 + 32 旧卡）+ 3 禁卡
    assert opn.allowed_marks == list("ABCDEFGHI")
    assert len(opn.allowed_basic_energy_types) == 9
    assert "妖" in opn.allowed_basic_energy_types
    assert len(opn.whitelist_cards) == 50
    assert {b.name for b in opn.banned_cards} == {"玛夏多", "阿塞萝拉", "全满药"}
    assert next(b for b in opn.banned_cards if b.name == "玛夏多").ability_or_attack == "破罐破摔"

    # 双赛制均含视作覆盖：天空之柱 CSM2DC-339 → B
    for s in (std, opn):
        mo = next(m for m in s.mark_overrides if m.card_id == "CSM2DC-339")
        assert mo.mark == "B"

    # 白名单名称两赛制无重复、特典 18 种齐全
    for s in (std, opn):
        names = [w.name_full for w in s.whitelist_cards]
        assert len(names) == len(set(names))
    promos = [w for w in std.whitelist_cards if w.note and "30th-P" in w.note]
    assert len(promos) == 18


def test_seed_snapshots_idempotent(tmp_path):
    """入库：重跑幂等，字段与种子一致。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)

    ids1 = seed_snapshots(db_path, CONFIG_DIR)
    ids2 = seed_snapshots(db_path, CONFIG_DIR)
    assert ids1 == ids2 == ["open-2026-07-16", "standard-2026-07-16"]

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        rows = list(session.scalars(select(LegalitySnapshot)))
        assert len(rows) == 2  # 幂等：无重复行
        std = session.get(LegalitySnapshot, "standard-2026-07-16")
        assert std.format == "standard"
        assert std.allowed_marks == ["G", "H", "I"]
        assert len(std.whitelist_cards) == 44
        assert std.whitelist_cards[0]["name_full"] == "妙蛙种子"
        assert std.mark_overrides[0]["card_id"] == "CSM2DC-339"
        assert std.effective_to is None
        assert std.source_url == "https://www.pokemon.cn/tcg-rules-regulation"
    engine.dispose()


def test_seed_snapshots_upsert(tmp_path):
    """同 snapshot_id 再入库 = 更新（upsert），不产生第二行。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    seed_snapshots(db_path, CONFIG_DIR)

    # 构造一份修改过的种子目录：标准赛制加一种能量
    mod_dir = tmp_path / "legality"
    mod_dir.mkdir()
    for f in CONFIG_DIR.glob("*.yml"):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if data["snapshot_id"] == "standard-2026-07-16":
            data["allowed_basic_energy_types"] = [*data["allowed_basic_energy_types"], "妖"]
        (mod_dir / f.name).write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )

    seed_snapshots(db_path, mod_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert len(list(session.scalars(select(LegalitySnapshot)))) == 2
        std = session.get(LegalitySnapshot, "standard-2026-07-16")
        assert "妖" in std.allowed_basic_energy_types
    engine.dispose()


# ---- 冻结快照拒绝 / 未冻结允许 ----


def test_seed_frozen_snapshot_rejected(tmp_path):
    """已冻结快照（effective_to 非空）拒绝种子覆盖，抛 ValueError。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(LegalitySnapshot(
            snapshot_id="standard-2026-01-01",
            format="standard",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 30),  # 已冻结
            allowed_marks=["G"],
            allowed_basic_energy_types=["草"],
            whitelist_cards=[],
            banned_cards=[],
            mark_overrides=[],
            latest_text_overrides={},
            source_url=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()
    engine.dispose()

    seed_dir = tmp_path / "legality"
    seed_dir.mkdir()
    seed_data = {
        "snapshot_id": "standard-2026-01-01",
        "format": "standard",
        "effective_from": "2026-01-01",
        "source_url": None,
        "allowed_marks": ["G", "H"],
        "allowed_basic_energy_types": ["草"],
        "whitelist_cards": [],
        "banned_cards": [],
        "mark_overrides": [],
    }
    (seed_dir / "standard.yml").write_text(
        yaml.safe_dump(seed_data, allow_unicode=True), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="已冻结"):
        seed_snapshots(db_path, seed_dir)


def test_seed_unfrozen_snapshot_allowed(tmp_path):
    """未冻结快照（effective_to=None）允许种子 upsert 覆盖。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(LegalitySnapshot(
            snapshot_id="standard-2026-01-01",
            format="standard",
            effective_from=date(2026, 1, 1),
            effective_to=None,  # 未冻结
            allowed_marks=["G"],
            allowed_basic_energy_types=["草"],
            whitelist_cards=[],
            banned_cards=[],
            mark_overrides=[],
            latest_text_overrides={},
            source_url=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()
    engine.dispose()

    seed_dir = tmp_path / "legality"
    seed_dir.mkdir()
    seed_data = {
        "snapshot_id": "standard-2026-01-01",
        "format": "standard",
        "effective_from": "2026-01-01",
        "source_url": None,
        "allowed_marks": ["G", "H"],
        "allowed_basic_energy_types": ["草"],
        "whitelist_cards": [],
        "banned_cards": [],
        "mark_overrides": [],
    }
    (seed_dir / "standard.yml").write_text(
        yaml.safe_dump(seed_data, allow_unicode=True), encoding="utf-8"
    )

    ids = seed_snapshots(db_path, seed_dir)
    assert ids == ["standard-2026-01-01"]

    # upsert 生效：种子字段已覆盖
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        snap = session.get(LegalitySnapshot, "standard-2026-01-01")
        assert snap.allowed_marks == ["G", "H"]
    engine.dispose()

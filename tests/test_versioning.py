"""版本化与回滚测试（task 009）：A5 快照 apply/冻结 + A6 回滚 + 双轨版本号。"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.legal import legal_at
from ptcgdb.legal.versions import (
    FrozenSnapshotError,
    apply_snapshot,
    rollback,
    update_text_overrides,
)
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, CardNameGroup, LegalitySnapshot, Meta, NameGroup, Set


def _base_db(tmp_path) -> Path:
    """合成库：standard 当前快照（白名单 高级球）+ 高级球新旧两印刷。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as s:
        s.add_all([
            Set(set_id="OLD", name_zh="旧系列", era="剑&盾", release_date=date(2025, 1, 1),
                regulation_mark="F", expected_count=None, expected_secret_count=None,
                source="test", fetched_at="2025-01-01"),
            Set(set_id="NEW", name_zh="新系列", era="朱&紫", release_date=date(2026, 3, 1),
                regulation_mark="G", expected_count=None, expected_secret_count=None,
                source="test", fetched_at="2026-03-01"),
        ])
        s.add(NameGroup(group_key="高级球", display_name="高级球"))

        def card(cid, sid, mark):
            return Card(
                card_id=cid, set_id=sid, number=cid.rsplit("-", 1)[1],
                number_display="001/100", name_full="高级球", species=None, owner=None,
                card_type="trainer", regulation_mark=mark, rarity="R", stage=None,
                hp=None, types=None, evolves_from_text=None, evolves_from_id=None,
                evolution_chain_id=None, rule_box_type=None, has_rule_box=False,
                is_tera=False, union_position=None, prize_cards=1, deck_limit=4,
                is_ace_spec=False, abilities=None, attacks=None, weakness=None,
                resistance=None, retreat_cost=None, trainer_subtype=None, provides=None,
                is_basic_energy=False, text_raw=f"{cid}文本", effect_tags=None,
                name_en=None, name_ja=None, name_zh_tw=None, source="test",
                fetched_at=datetime.now(UTC), status="active",
            )

        s.add_all([card("OLD-001", "OLD", "F"), card("NEW-001", "NEW", "G")])
        s.add_all([
            CardNameGroup(card_id="OLD-001", group_key="高级球"),
            CardNameGroup(card_id="NEW-001", group_key="高级球"),
        ])
        s.add(LegalitySnapshot(
            snapshot_id="standard-2026-01-01", format="standard",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=["G", "H", "I"],
            allowed_basic_energy_types=["草"],
            whitelist_cards=[{"name_full": "高级球"}],
            banned_cards=[], mark_overrides=[], latest_text_overrides={},
            source_url="test", created_at=datetime.now(UTC),
        ))
        s.commit()
    engine.dispose()
    return db_path


def _proposal(tmp_path) -> Path:
    """模拟赛制页变更提案：新增 J 标记，2026-09-01 生效。"""
    path = tmp_path / "proposals" / "20260901_standard.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump({
        "snapshot_id": "standard-2026-09-01",
        "format": "standard",
        "effective_from": "2026-09-01",
        "source_url": "https://www.pokemon.cn/tcg-rules-regulation",
        "allowed_marks": ["G", "H", "I", "J"],
        "allowed_basic_energy_types": ["草"],
        "whitelist_cards": [{"name_full": "高级球"}],
        "banned_cards": [],
        "mark_overrides": [],
    }, allow_unicode=True), encoding="utf-8")
    return path


def _apply(tmp_path):
    db_path, prop = _base_db(tmp_path), _proposal(tmp_path)
    changelog = tmp_path / "CHANGELOG.md"
    sid = apply_snapshot(
        db_path, prop, changelog_path=changelog,
        versions_dir=tmp_path / "versions",
    )
    return db_path, changelog, sid


class TestApplySnapshot:
    def test_apply_closes_old_and_opens_new(self, tmp_path):
        """A5：apply 后新快照生效、旧快照闭合且可查询（S5 历史回放）。"""
        db_path, _, sid = _apply(tmp_path)
        assert sid == "standard-2026-09-01"
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            old = s.get(LegalitySnapshot, "standard-2026-01-01")
            new = s.get(LegalitySnapshot, "standard-2026-09-01")
            assert old.effective_to == date(2026, 8, 31)
            assert new.effective_to is None
            assert new.allowed_marks == ["G", "H", "I", "J"]
            # 历史回放：apply 前的日期仍命中旧快照
            assert legal_at(s, date(2026, 8, 1), "standard").snapshot_id == "standard-2026-01-01"
            assert legal_at(s, date(2026, 10, 1), "standard").snapshot_id == "standard-2026-09-01"
        engine.dispose()

    def test_apply_refreshes_latest_text_overrides(self, tmp_path):
        """FR-5.1 后处理：白名单旧卡 → 最新印刷。"""
        db_path, _, _ = _apply(tmp_path)
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            new = s.get(LegalitySnapshot, "standard-2026-09-01")
            assert new.latest_text_overrides == {"OLD-001": "NEW-001"}
            old = s.get(LegalitySnapshot, "standard-2026-01-01")
            assert old.latest_text_overrides == {}  # 旧快照不被回填
        engine.dispose()

    def test_data_version_and_changelog(self, tmp_path):
        """FR-6.1：数据版本 vYYYYMMDD.N 同日递增；CHANGELOG 四段式。"""
        db_path, changelog, _ = _apply(tmp_path)
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            meta = {m.key: m.value for m in s.scalars(select(Meta))}
        engine.dispose()
        today = date.today().strftime("%Y%m%d")
        assert meta["data_version"] == f"v{today}.1"
        assert meta["schema_version"] == "1.0.0"
        text = changelog.read_text(encoding="utf-8")
        assert f"## [{meta['data_version']}]" in text
        assert "### Added" in text
        assert "standard-2026-09-01" in text

        # 同日第二次 apply → .2
        prop2 = tmp_path / "proposals" / "p2.yaml"
        prop2.write_text(yaml.safe_dump({
            "snapshot_id": "standard-2026-10-01", "format": "standard",
            "effective_from": "2026-10-01", "allowed_marks": ["H", "I", "J"],
            "allowed_basic_energy_types": ["草"],
            "whitelist_cards": [], "banned_cards": [], "mark_overrides": [],
        }, allow_unicode=True), encoding="utf-8")
        apply_snapshot(db_path, prop2, changelog_path=changelog,
                       versions_dir=tmp_path / "versions")
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            meta = {m.key: m.value for m in s.scalars(select(Meta))}
        engine.dispose()
        assert meta["data_version"] == f"v{today}.2"

    def test_backup_created(self, tmp_path):
        _, _, _ = _apply(tmp_path)
        backups = list((tmp_path / "versions").glob("*.db"))
        assert len(backups) == 1


class TestFreeze:
    def test_historical_snapshot_frozen(self, tmp_path):
        """历史快照 override 一经生成即冻结（S5 不漂移）。"""
        db_path, _, _ = _apply(tmp_path)
        with pytest.raises(FrozenSnapshotError):
            update_text_overrides(db_path, "standard-2026-01-01", {"OLD-001": "NEW-001"})

    def test_current_snapshot_writable(self, tmp_path):
        db_path, _, _ = _apply(tmp_path)
        update_text_overrides(db_path, "standard-2026-09-01", {"X-001": "Y-001"})
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            assert s.get(LegalitySnapshot, "standard-2026-09-01").latest_text_overrides == {
                "OLD-001": "NEW-001",  # apply 时自动刷新（FR-5.1 后处理）
                "X-001": "Y-001",
            }
        engine.dispose()


class TestRollback:
    def test_rollback_restores_previous_version(self, tmp_path):
        """A6：脏合入后一键回滚，数据无损。"""
        db_path, _, _ = _apply(tmp_path)
        # apply 已生效（新快照在、旧快照闭合）
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            assert s.get(LegalitySnapshot, "standard-2026-09-01") is not None
        engine.dispose()

        restored = rollback(db_path, versions_dir=tmp_path / "versions")
        assert restored
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as s:
            assert s.get(LegalitySnapshot, "standard-2026-09-01") is None
            old = s.get(LegalitySnapshot, "standard-2026-01-01")
            assert old.effective_to is None  # 旧快照复原未闭合
            assert legal_at(s, date(2026, 10, 1), "standard").snapshot_id == (
                "standard-2026-01-01"
            )
        engine.dispose()

    def test_rollback_without_backup_raises(self, tmp_path):
        db_path = _base_db(tmp_path)
        with pytest.raises(LookupError):
            rollback(db_path, versions_dir=tmp_path / "versions")

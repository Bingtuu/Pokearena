"""task 026 测试：CLI `ptcgdb deck-check`（FR-8，卡表 YAML 格式见 PRD v1.12）。

卡表格式：cards 为 card_id → 数量的映射；format/date 可选，CLI 选项覆盖。
ok 退出码 0，有违规退出码 1，输入/快照错误退出码 2。
"""

from datetime import UTC, date, datetime

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from ptcgdb.cli import app
from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, LegalitySnapshot, Meta, Set

runner = CliRunner()


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "t.db"
    apply_migrations(path)
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        s.add(Set(
            set_id="TS", name_zh="测试系列", era="朱&紫", release_date=date(2026, 1, 1),
            regulation_mark="G", expected_count=None, expected_secret_count=None,
            source="test", fetched_at="2026-01-01",
        ))

        def card(cid, name, mark, *, ctype="pokemon", basic=False, provides=None):
            s.add(Card(
                card_id=cid, set_id="TS", number=cid.rsplit("-", 1)[1],
                number_display="001/100", name_full=name, species=name, owner=None,
                card_type=ctype, regulation_mark=mark, rarity="R", stage=None, hp=None,
                types=None, evolves_from_text=None, evolves_from_id=None,
                evolution_chain_id=None, rule_box_type=None, has_rule_box=False,
                is_tera=False, union_position=None, prize_cards=1, deck_limit=4,
                is_ace_spec=False, abilities=None, attacks=None, weakness=None,
                resistance=None, retreat_cost=None, trainer_subtype=None,
                provides=provides, is_basic_energy=basic,
                text_raw=f"{name}原文", effect_tags=None,
                name_en=None, name_ja=None, name_zh_tw=None, source="test",
                fetched_at=datetime.now(UTC), status="active",
            ))

        card("TS-001", "喵喵", "G")
        card("TS-004", "玛夏多", "G")
        card("TS-006", "基本草能量", None, ctype="energy", basic=True, provides=["草"])
        s.add(LegalitySnapshot(
            snapshot_id="standard-1", format="standard",
            effective_from=date(2026, 1, 1), effective_to=None,
            allowed_marks=["G", "H", "I"], allowed_basic_energy_types=["草"],
            whitelist_cards=[], banned_cards=[{"name": "玛夏多"}],
            mark_overrides=[], latest_text_overrides={},
            source_url="test", created_at=datetime.now(UTC),
        ))
        s.add(Meta(key="data_version", value="v20260804.1"))
        s.commit()
    engine.dispose()
    return path


def write_deck(tmp_path, cards: dict[str, int], **extra) -> str:
    path = tmp_path / "deck.yml"
    path.write_text(
        yaml.dump({"cards": cards, **extra}, allow_unicode=True), encoding="utf-8",
    )
    return str(path)


def test_ok_deck_exit_0(db_path, tmp_path):
    f = write_deck(tmp_path, {"TS-001": 4, "TS-006": 56},
                   date="2026-08-01", format="standard")
    result = runner.invoke(app, ["deck-check", "--file", f, "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "ok=True" in result.output
    assert "snapshot=standard-1" in result.output


def test_banned_deck_exit_1(db_path, tmp_path):
    f = write_deck(tmp_path, {"TS-004": 1, "TS-006": 59}, date="2026-08-01")
    result = runner.invoke(app, ["deck-check", "--file", f, "--db-path", str(db_path)])
    assert result.exit_code == 1, result.output
    assert "ok=False" in result.output
    assert "banned" in result.output and "玛夏多" in result.output


def test_cli_option_overrides_file(db_path, tmp_path):
    """CLI --date/--format 覆盖文件内字段；无覆盖快照 → 退出码 2。"""
    f = write_deck(tmp_path, {"TS-001": 4, "TS-006": 56}, date="2026-08-01")
    result = runner.invoke(app, [
        "deck-check", "--file", f, "--db-path", str(db_path), "--date", "2020-01-01",
    ])
    assert result.exit_code == 2, result.output


def test_bad_file_exit_2(db_path, tmp_path):
    f = tmp_path / "bad.yml"
    f.write_text("not_cards: 1", encoding="utf-8")
    result = runner.invoke(app, ["deck-check", "--file", str(f), "--db-path", str(db_path)])
    assert result.exit_code == 2, result.output


def test_default_date_is_today(db_path, tmp_path):
    """文件与 CLI 都不给日期时默认当天（快照 effective_from=2026-01-01 覆盖）。"""
    f = write_deck(tmp_path, {"TS-001": 4, "TS-006": 56})
    result = runner.invoke(app, ["deck-check", "--file", f, "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

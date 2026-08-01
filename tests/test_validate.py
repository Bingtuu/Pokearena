"""task 006 测试：FR-2.3 六条规则正负例 + CLI 冒烟（合成数据，零网络）。

全部用 tmp_path 建独立小 DB + 合成 raw JSON（write_raw 保持 _meta hash 有效）；
绝不允许联网，绝不碰 data/ptcg-cn.db 与 data/raw/。
"""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from ptcgdb.cli import app
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, CardRelation
from ptcgdb.scrapers.raw_store import write_raw
from ptcgdb.validate import run_validations, write_report
from ptcgdb.validate.rules import RuleResult

SET_ID = "TEST1"
CARD_COUNT = 5

runner = CliRunner()


def card_payload(index: str, *, name: str | None = None, hp: int = 60) -> dict:
    """合成 mik card-detail payload：cost "RC" → DB [{火,1},{无,1}]。"""
    return {
        "code": 200,
        "data": {
            "name": name or f"测试宝可梦{index}",
            "nameEn": "",
            "setCode": SET_ID,
            "cardIndex": index,
            "cardType": "Pokemon",
            "regulationMark": "A",
            "rarity": "C",
            "description": f"卡面原文{index}",
            "mechanic": None,
            "label": None,
            "pokemonAttr": {
                "stage": "Basic",
                "hp": hp,
                "energyType": "G",
                "attack": [
                    {"name": f"招式{index}", "cost": "RC", "damage": "20", "text": ""}
                ],
                "weakness": {"energy": "R", "value": "×2"},
                "resistance": None,
                "retreatCost": 1,
            },
        },
        "msg": "OK.",
    }


def make_raw_dir(tmp_path: Path, count: int = CARD_COUNT, cards_num: int | None = None) -> Path:
    """合成 raw 目录：count 张单卡 + 系列级 cards.json（cardsNum 默认=count 使对账通过）。"""
    set_dir = tmp_path / "raw" / "mikmoe" / SET_ID
    set_dir.mkdir(parents=True)
    for i in range(1, count + 1):
        index = f"{i:03d}"
        write_raw(set_dir / f"{index}.json", card_payload(index), source="mik_moe")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "测试系列",
                "setCode": SET_ID,
                "setId": SET_ID,
                "releaseDate": "2024-01-01T00:00:00+08:00",
                "series": "Sun & Moon",
                "mainExpansion": True,
                "cardsNum": cards_num if cards_num is not None else count,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )
    return tmp_path / "raw"


@pytest.fixture()
def db_env(tmp_path):
    """干净环境：5 张卡入库为 draft，六条规则应全过。"""
    raw_dir = make_raw_dir(tmp_path)
    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, SET_ID, db_path)
    assert result.card_count == CARD_COUNT and not result.skipped
    return raw_dir, db_path


def get_rule(results: list[RuleResult], name: str) -> RuleResult:
    return next(r for r in results if r.rule == name)


def mutate_card(db_path: Path, card_id: str, **changes) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        card = session.get(Card, card_id)
        for key, value in changes.items():
            setattr(card, key, value)
        session.commit()
    engine.dispose()


# ---- 干净环境：六条规则全过 ----


def test_all_rules_pass_on_clean_ingest(db_env):
    raw_dir, db_path = db_env
    results = run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir)
    assert [r.rule for r in results] == [
        "必填非空", "枚举合法", "能量成本合法且保序", "系列对账", "V-UNION 完整性", "抽样比对",
    ]
    assert all(r.passed for r in results)
    # 对账表：5 == 5 + 0
    recon = get_rule(results, "系列对账")
    assert recon.details == [{"set_id": SET_ID, "expected": 5, "actual": 5, "ok": True}]
    # 无 V-UNION 样本自动跳过
    assert get_rule(results, "V-UNION 完整性").note == "无 V-UNION 样本，规则跳过"


# ---- 规则 1：必填非空 ----


def test_required_missing_fails(db_env):
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", name_full="")
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "name_full" for f in res.failures
    )


def test_required_regulation_mark_none_fails_for_non_basic_energy(db_env):
    """非基本能量 regulation_mark=NULL → 规则 1 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", regulation_mark=None)
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "regulation_mark"
        for f in res.failures
    )


def test_required_regulation_mark_none_passes_for_basic_energy(db_env):
    """基本能量无赛制标记是数据事实（PRD FR-3.2），regulation_mark=NULL 豁免。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", regulation_mark=None, is_basic_energy=True)
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert res.passed
    # 豁免依据如实注明
    assert res.note and "is_basic_energy" in res.note


def test_required_text_raw_empty_passes_for_basic_energy(db_env):
    """基本能量卡面无文字是数据事实（§7.2"卡面全部文字"即空），text_raw 豁免。"""
    raw_dir, db_path = db_env
    mutate_card(
        db_path, f"{SET_ID}-001", regulation_mark=None, text_raw="", is_basic_energy=True
    )
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert res.passed


def test_required_text_raw_empty_fails_for_non_basic_energy(db_env):
    """非基本能量 text_raw 空 → 规则 1 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", text_raw="")
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "text_raw" for f in res.failures
    )


# ---- 规则 2：枚举合法 ----


def test_enum_out_of_vocab_fails(db_env):
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-002", rarity="XXX")
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "枚举合法")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-002" and f["field"] == "rarity" and f["value"] == "XXX"
        for f in res.failures
    )


# ---- 规则 3：能量成本合法且保序 ----


def test_energy_out_of_order_fails(db_env):
    raw_dir, db_path = db_env
    # raw cost "RC" → [火, 无]；把 DB 顺序颠倒应判乱序
    mutate_card(
        db_path, f"{SET_ID}-003",
        attacks=[{
            "name": "招式003",
            "cost": [{"type": "无", "count": 1}, {"type": "火", "count": 1}],
            "damage_base": 20, "damage_modifier": None, "effect_text": "",
        }],
    )
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "能量成本合法且保序"
    )
    assert not res.passed
    assert any(f["card_id"] == f"{SET_ID}-003" and "cost" in f["field"] for f in res.failures)


def test_energy_unknown_symbol_fails(db_env):
    raw_dir, db_path = db_env
    mutate_card(
        db_path, f"{SET_ID}-003",
        attacks=[{
            "name": "招式003", "cost": [{"type": "金", "count": 1}],
            "damage_base": 20, "damage_modifier": None, "effect_text": "",
        }],
    )
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "能量成本合法且保序"
    )
    assert not res.passed
    assert any(f.get("value") == "金" for f in res.failures)


def test_energy_cost_modifier_mismatch_fails(db_env):
    """raw cost "RC" 无追加标记；DB 多出 cost_modifier="+" 应判不一致。"""
    raw_dir, db_path = db_env
    mutate_card(
        db_path, f"{SET_ID}-003",
        attacks=[{
            "name": "招式003",
            "cost": [{"type": "火", "count": 1}, {"type": "无", "count": 1}],
            "cost_modifier": "+",
            "damage_base": 20, "damage_modifier": None, "effect_text": "",
        }],
    )
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "能量成本合法且保序"
    )
    assert not res.passed
    assert any(f["field"] == "attacks[0].cost_modifier" for f in res.failures)


# ---- 规则 4：系列对账 ----


def test_reconciliation_gap_fails(db_env):
    raw_dir, db_path = db_env
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.execute(delete(Card).where(Card.card_id == f"{SET_ID}-005"))
        session.commit()
    engine.dispose()
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "系列对账")
    assert not res.passed
    assert res.failures[0]["expected"] == 5 and res.failures[0]["actual"] == 4


# ---- 规则 5：V-UNION 完整性 ----

UNION_POSITIONS = ("左上", "右上", "左下", "右下")


def add_union_cards(db_path: Path, positions: tuple[str, ...]) -> None:
    """直接插 V-UNION 部件卡 + union_part_of 链式关系（ingest 不产此关系，合成直插）。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for i, pos in enumerate(positions, start=1):
            session.add(Card(
                card_id=f"{SET_ID}-U{i}", set_id=SET_ID, number=f"U{i}",
                number_display=f"U{i}", name_full=f"测试V-UNION{i}",
                species=None, owner=None, card_type="pokemon", regulation_mark="A",
                rarity="RRR", stage=None, hp=300, types=["超"],
                evolves_from_text=None, evolves_from_id=None, evolution_chain_id=None,
                rule_box_type="v_union", has_rule_box=True, is_tera=False,
                union_position=pos, prize_cards=3, deck_limit=1, is_ace_spec=False,
                abilities=None, attacks=None, weakness=None, resistance=None,
                retreat_cost=None, trainer_subtype=None, provides=None,
                is_basic_energy=False, text_raw="部件原文", effect_tags=None,
                name_en=None, name_ja=None, name_zh_tw=None,
                source="mik_moe", fetched_at=datetime(2024, 1, 1), status="draft",
            ))
        for i in range(1, len(positions)):
            session.add(CardRelation(
                card_id=f"{SET_ID}-U{i}", related_card_id=f"{SET_ID}-U{i + 1}",
                relation_type="union_part_of", confidence="high", source="mik_moe",
            ))
        session.commit()
    engine.dispose()


def union_rule(db_env) -> RuleResult:
    raw_dir, db_path = db_env
    return get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "V-UNION 完整性")


def test_vunion_complete_passes(db_env):
    _, db_path = db_env
    add_union_cards(db_path, UNION_POSITIONS)
    assert union_rule(db_env).passed


def test_vunion_missing_part_fails(db_env):
    _, db_path = db_env
    add_union_cards(db_path, UNION_POSITIONS[:3])  # 缺右下
    res = union_rule(db_env)
    assert not res.passed
    assert any("部件数=3" in f["note"] for f in res.failures)


def test_vunion_duplicate_position_fails(db_env):
    _, db_path = db_env
    add_union_cards(db_path, ("左上", "左上", "左下", "右下"))  # 方位重复且缺右上
    res = union_rule(db_env)
    assert not res.passed
    assert any(f["note"] == "方位重复" for f in res.failures)
    assert any("方位缺失" in f["note"] for f in res.failures)


# ---- 规则 6：抽样比对 ----


def test_sampling_deterministic(db_env):
    raw_dir, db_path = db_env
    res1 = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "抽样比对")
    res2 = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "抽样比对")
    assert res1.passed and res1.checked == 1  # 5 张 × 5% 向上取整 = 1
    assert res1.details == res2.details  # 两次抽样清单一致（确定性）
    assert res1.details[0]["samples"] == [f"{SET_ID}-001"]  # 等距取样首张


def test_sampling_mismatch_fails(db_env):
    raw_dir, db_path = db_env
    # 改写被抽样卡（001）的 raw 卡名（force 重算 hash，保持 raw 有效）
    write_raw(
        raw_dir / "mikmoe" / SET_ID / "001.json",
        card_payload("001", name="被篡改的卡名"),
        source="mik_moe",
        force=True,
    )
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "抽样比对")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "name_full" for f in res.failures
    )


# ---- 报告渲染 ----


def test_report_written(db_env, tmp_path):
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-002", rarity="XXX")
    results = run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir)
    report = write_report(results, tmp_path / "reports" / "r.md", db_path=db_path, raw_dir=raw_dir)
    text = report.read_text(encoding="utf-8")
    assert "## 规则总览" in text and "失败明细" in text
    assert "抽样清单" in text and "| 系列 |" in text  # 抽样清单 + 对账表
    assert "同源自验" in text  # 与 PRD 的偏差如实注明


# ---- CLI 冒烟 ----

# typer 中带默认值的参数是 option（与现有 ingest/scrape 命令一致），
# 用 --raw-dir / --db-path 显式传入，保证默认路径（data/...）绝不被测试触到。


def test_cli_validate_ok(db_env, tmp_path):
    raw_dir, db_path = db_env
    report = tmp_path / "r.md"
    result = runner.invoke(
        app,
        [
            "validate", "--set", SET_ID, "--report", str(report),
            "--raw-dir", str(raw_dir), "--db-path", str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert report.is_file()
    assert "✓ 必填非空" in result.output


def test_cli_validate_fail_exit_nonzero(db_env, tmp_path):
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", name_full="")
    result = runner.invoke(
        app,
        [
            "validate", "--set", SET_ID, "--report", str(tmp_path / "r.md"),
            "--raw-dir", str(raw_dir), "--db-path", str(db_path),
        ],
    )
    assert result.exit_code == 1
    assert "✗ 必填非空" in result.output


def test_cli_validate_unknown_set(db_env):
    raw_dir, db_path = db_env
    result = runner.invoke(
        app,
        ["validate", "--set", "NOPE", "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    assert result.exit_code == 1


def test_cli_activate_ok(db_env):
    raw_dir, db_path = db_env
    result = runner.invoke(
        app,
        ["activate", "--set", SET_ID, "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    assert f"activated={CARD_COUNT}" in result.output
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert {c.status for c in session.query(Card)} == {"active"}
    engine.dispose()


def test_cli_activate_blocked_keeps_draft(db_env):
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-002", rarity="XXX")
    result = runner.invoke(
        app,
        ["activate", "--set", SET_ID, "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    assert result.exit_code == 1
    assert "枚举合法" in result.output
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert {c.status for c in session.query(Card)} == {"draft"}
    engine.dispose()

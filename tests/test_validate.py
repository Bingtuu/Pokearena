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
    """合成 raw 目录：count 张单卡 + 系列级 cards.json（cardsNum 默认=count 使对账通过）。

    cards 列表条目按真实 mik 形态填写（task 006：对账/raw 定位走条目
    setCode + cardIndex 去重口径，空列表会导致期望数为 0）。
    """
    set_dir = tmp_path / "raw" / "mikmoe" / SET_ID
    set_dir.mkdir(parents=True)
    entries = []
    for i in range(1, count + 1):
        index = f"{i:03d}"
        payload = card_payload(index)
        write_raw(set_dir / f"{index}.json", payload, source="mik_moe")
        entries.append(
            {
                "setCode": SET_ID,
                "cardIndex": index,
                "cardName": payload["data"]["name"],
                "rarity": "C",
                "cardType": "Pokemon",
            }
        )
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
                "cards": entries,
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
        "必填非空", "枚举合法", "赛制标记格式", "HP 数值范围", "evolves_from 外键",
        "能量成本合法且保序", "系列对账", "V-UNION 完整性", "抽样比对",
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


def test_vunion_all_positions_none_passes(db_env):
    """mik 无方位字段（task 005 SSP 实测）：全 None 只查 4 部件齐全，不判失败。"""
    _, db_path = db_env
    add_union_cards(db_path, (None, None, None, None))  # type: ignore[arg-type]
    res = union_rule(db_env)
    assert res.passed
    assert res.note and "方位数据不可得" in res.note


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


# ============================================================
# 新增辅助函数与夹具（task 032 扩展测试）
# ============================================================


def make_trainer_raw_dir(tmp_path: Path) -> Path:
    """合成只含训练家卡的 raw 目录（用于 energy trainer skip 测试）。"""
    set_dir = tmp_path / "raw" / "mikmoe" / "TRNR"
    set_dir.mkdir(parents=True)
    payload = {
        "code": 200,
        "data": {
            "name": "测试支援者",
            "nameEn": "",
            "setCode": "TRNR",
            "cardIndex": "001",
            "cardType": "Supporter",
            "regulationMark": "A",
            "rarity": "U",
            "description": "从卡组抽3张",
            "mechanic": None,
            "label": None,
        },
        "msg": "OK.",
    }
    write_raw(set_dir / "001.json", payload, source="mik_moe")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "测试训练家系列",
                "setCode": "TRNR",
                "setId": "TRNR",
                "releaseDate": "2024-01-01T00:00:00+08:00",
                "series": "Sun & Moon",
                "mainExpansion": True,
                "cardsNum": 1,
                "cards": [
                    {
                        "setCode": "TRNR",
                        "cardIndex": "001",
                        "cardName": "测试支援者",
                        "rarity": "U",
                        "cardType": "Supporter",
                    }
                ],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )
    return tmp_path / "raw"


@pytest.fixture()
def trainer_env(tmp_path):
    """只含训练家卡的 DB（用于 check_energy trainer skip 测试）。"""
    raw_dir = make_trainer_raw_dir(tmp_path)
    db_path = tmp_path / "trainer.db"
    result = ingest_set(raw_dir, "TRNR", db_path)
    assert result.card_count == 1 and not result.skipped
    return raw_dir, db_path


# ============================================================
# 规则 1：必填非空 — 源数据缺失豁免
# ============================================================


def test_required_source_missing_exemption(db_env):
    """text_raw 为空且 raw description 也为空 → 豁免（不算失败）。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", text_raw="", is_basic_energy=False)
    # 同时覆写 raw：description 置空，让 read_raw 发现源数据同样缺失
    base = card_payload("001", name="测试宝可梦001")
    write_raw(
        raw_dir / "mikmoe" / SET_ID / "001.json",
        base | {"data": {**base["data"], "description": ""}},
        source="mik_moe",
        force=True,
    )
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert res.passed
    assert res.note and "源数据缺失豁免" in res.note
    assert f"{SET_ID}-001" in res.note


def test_required_source_missing_not_exempted_when_raw_has_text(db_env):
    """text_raw 为空但 raw description 有文字 → 判失败（管线丢失）。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", text_raw="", is_basic_energy=False)
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "必填非空")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "text_raw" for f in res.failures
    )


# ============================================================
# 规则 2：枚举合法 — card_type 失败 + regulation_mark 无词表
# ============================================================


def test_enum_card_type_invalid_fails(db_env):
    """card_type 不在词表 → 规则 2 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", card_type="Trickster")
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "枚举合法")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "card_type" and f["value"] == "Trickster"
        for f in res.failures
    )


def test_enum_trainer_subtype_invalid_fails(db_env):
    """trainer_subtype 不在词表 → 规则 2 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", card_type="trainer", trainer_subtype="魔导师")
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "枚举合法")
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "trainer_subtype"
        for f in res.failures
    )


def test_enum_regulation_mark_no_vocab_note(db_env):
    """regulation_mark 无词表文件 → 规则 2 note 注明，不做枚举校验。"""
    raw_dir, db_path = db_env
    # 设置一个奇怪的 regulation_mark，枚举规则不应报错
    mutate_card(db_path, f"{SET_ID}-001", regulation_mark="???")
    res = get_rule(run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "枚举合法")
    # 枚举规则不应因 regulation_mark 失败（但赛制标记格式规则会失败）
    assert res.note and "regulation_mark" in res.note
    # 确认没有 regulation_mark 相关的 failures
    has_mark_failure = any(
        f.get("field") == "regulation_mark" for f in res.failures
    )
    assert not has_mark_failure


# ============================================================
# 规则 2 扩展：赛制标记格式
# ============================================================


def test_regulation_mark_format_valid_passes(db_env):
    """有效赛制标记 "G" → 通过。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", regulation_mark="G")
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "赛制标记格式"
    )
    assert res.passed
    assert res.checked == CARD_COUNT


def test_regulation_mark_format_invalid_fails(db_env):
    """无效赛制标记 "XYZ" → 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", regulation_mark="XYZ")
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "赛制标记格式"
    )
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["value"] == "XYZ"
        for f in res.failures
    )


def test_regulation_mark_format_none_passes(db_env):
    """regulation_mark=None → 通过（无赛制标记不校验格式）。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", regulation_mark=None, is_basic_energy=True)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "赛制标记格式"
    )
    assert res.passed
    # 确认这张卡没有被报 failure
    assert not any(
        f.get("card_id") == f"{SET_ID}-001" for f in res.failures
    )


# ============================================================
# 规则 N：HP 数值范围
# ============================================================


def test_hp_range_valid_passes(db_env):
    """hp=120 在合理范围 → 通过。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", hp=120)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    assert res.passed
    assert res.checked == CARD_COUNT


def test_hp_range_negative_fails(db_env):
    """hp=-1 → 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", hp=-1)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["value"] == -1 for f in res.failures
    )


def test_hp_range_zero_fails(db_env):
    """hp=0 低于 HP_MIN(10) → 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", hp=0)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    assert not res.passed


def test_hp_range_above_max_fails(db_env):
    """hp=9999 高于 HP_MAX(340) → 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", hp=9999)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["value"] == 9999 for f in res.failures
    )


def test_hp_range_none_non_pokemon_passes(db_env):
    """非宝可梦卡 hp=None → 不校验（通过）。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", card_type="trainer", hp=None, stage=None,
                types=None, weakness=None, resistance=None, retreat_cost=None,
                attacks=None, trainer_subtype="物品")
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    # 训练家卡 card_type != "pokemon"，不参与 HP 校验
    assert res.passed
    assert not any(
        f.get("card_id") == f"{SET_ID}-001" for f in res.failures
    )


def test_hp_range_boundary_min_passes(db_env):
    """hp=10 刚好在边界 → 通过。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", hp=10)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    assert res.passed


def test_hp_range_boundary_max_passes(db_env):
    """hp=340 刚好在边界 → 通过。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", hp=340)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "HP 数值范围"
    )
    assert res.passed


# ============================================================
# 规则 N+1：evolves_from 外键
# ============================================================


def test_evolves_from_invalid_fk_fails(db_env):
    """evolves_from_id 指向不存在的卡 → 失败。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", evolves_from_id="NONEXISTENT-999")
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "evolves_from 外键"
    )
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["value"] == "NONEXISTENT-999"
        for f in res.failures
    )


def test_evolves_from_id_none_passes(db_env):
    """evolves_from_id=None → 通过（无需校验外键）。"""
    raw_dir, db_path = db_env
    mutate_card(db_path, f"{SET_ID}-001", evolves_from_id=None)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "evolves_from 外键"
    )
    assert res.passed
    assert not any(
        f.get("card_id") == f"{SET_ID}-001" for f in res.failures
    )


# ============================================================
# 规则 3：能量成本合法且保序 — trainer skip + retreat_cost 不匹配
# ============================================================


def test_energy_trainer_card_passes(trainer_env):
    """训练家卡无招式 → 能量成本校验自然通过。"""
    raw_dir, db_path = trainer_env
    # raw_dir=None：仅做词表校验，训练家卡无 attacks，cost 循环不执行
    res = get_rule(
        run_validations(db_path, set_id="TRNR", raw_dir=None), "能量成本合法且保序"
    )
    assert res.passed
    assert res.checked == 1


def test_energy_retreat_cost_mismatch_fails(db_env):
    """DB retreat_cost 与 raw 不一致 → 失败。"""
    raw_dir, db_path = db_env
    # raw retreatCost=1，篡改 DB 为 3
    mutate_card(db_path, f"{SET_ID}-001", retreat_cost=3)
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=raw_dir), "能量成本合法且保序"
    )
    assert not res.passed
    assert any(
        f["card_id"] == f"{SET_ID}-001" and f["field"] == "retreat_cost"
        for f in res.failures
    )


# ============================================================
# 规则 4：系列对账 — raw_dir=None 回退
# ============================================================


def test_reconciliation_raw_dir_none_fallback(db_env):
    """raw_dir=None → 回退 expected_count 口径对账。"""
    _, db_path = db_env
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=None), "系列对账"
    )
    # 干净环境 expected_count=5, actual=5 → 通过
    assert res.passed
    assert res.details[0]["ok"] is True
    assert res.details[0]["expected"] == 5
    assert res.details[0]["actual"] == 5


# ============================================================
# 规则 6：抽样比对 — raw_dir=None 跳过
# ============================================================


def test_sampling_raw_dir_none_skip(db_env):
    """raw_dir=None → 抽样比对整条跳过。"""
    _, db_path = db_env
    res = get_rule(
        run_validations(db_path, set_id=SET_ID, raw_dir=None), "抽样比对"
    )
    assert res.passed
    assert res.checked == 0
    assert res.note and "未提供 raw_dir" in res.note

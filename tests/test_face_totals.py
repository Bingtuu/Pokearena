"""task 030 F-01：卡面分母种子（face_totals）单测。"""

import json
import sqlite3

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize import face_totals


def test_display_denominator_total():
    assert face_totals.display_denominator({"total": 207}, "009") == 207


def test_display_denominator_packs():
    entry = {"packs": {"09": 15, "11": 7}}
    assert face_totals.display_denominator(entry, "0913") == 15
    assert face_totals.display_denominator(entry, "1105") == 7
    # 包号未覆盖 / 非数字前缀 → None（只显分子）
    assert face_totals.display_denominator(entry, "1201") is None
    assert face_totals.display_denominator(entry, "FIG") is None


def test_display_denominator_no_seed():
    assert face_totals.display_denominator(None, "009") is None


def _make_db(tmp_path, set_cards: dict[str, list[str]]) -> sqlite3.Connection:
    """fixture 库：sets + cards 最小行。set_cards: set_id → number 列表。"""
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    for set_id, numbers in set_cards.items():
        con.execute(
            "INSERT INTO sets (set_id, name_zh, era, regulation_mark, source, fetched_at)"
            " VALUES (?, '测试', '朱&紫', 'G', 'test', '')",
            (set_id,),
        )
        for num in numbers:
            con.execute(
                "INSERT INTO cards (card_id, set_id, number, number_display, name_full,"
                " card_type, rarity, has_rule_box, is_tera, prize_cards, deck_limit,"
                " is_ace_spec, is_basic_energy, text_raw, source, fetched_at, status)"
                " VALUES (?, ?, ?, ?, '测试卡', 'pokemon', 'C', 0, 0, 1, 4, 0, 0,"
                " '', 'test', '2026-01-01', 'active')",
                (f"{set_id}-{num}", set_id, num, num),
            )
    con.commit()
    return con


def _make_tcgdex_raw(tmp_path, shells: list[dict]):
    raw_dir = tmp_path / "raw"
    (raw_dir / "tcgdex").mkdir(parents=True)
    (raw_dir / "tcgdex" / "zh-cn-sets.json").write_text(
        json.dumps({"sets": shells}), encoding="utf-8"
    )
    return raw_dir


def test_generate_seed_gate_and_measured(tmp_path):
    """sanity 门：official 超库内最大编号 → 冲突不播种；过门 → tcgdex 播种。"""
    con = _make_db(
        tmp_path,
        {
            "TST1": [f"{i:03d}" for i in range(1, 11)],
            "TST2": [f"{i:03d}" for i in range(1, 11)],
        },
    )
    con.close()
    raw_dir = _make_tcgdex_raw(
        tmp_path,
        [
            {"id": "TST1", "name": "过门", "cardCount": {"total": 10, "official": 10}},
            {"id": "TST2", "name": "超界", "cardCount": {"total": 12, "official": 12}},
            {"id": "OTHER", "name": "非本库", "cardCount": {"total": 5, "official": 5}},
        ],
    )
    result = face_totals.generate_seed(tmp_path / "t.db", raw_dir)
    assert result.totals["TST1"] == {"total": 10, "source": "tcgdex"}
    assert "TST2" not in result.totals
    assert any("TST2" in c for c in result.conflicts)
    assert "OTHER" not in result.totals  # 非本库系列静默跳过
    # 人工实测 5 例始终播种
    assert result.totals["CS1DC"] == {"total": 207, "source": "measured"}
    assert result.totals["CSM1cC"] == {"total": 151, "source": "measured"}


def test_generate_seed_cbb_measured_mismatch_gates(tmp_path):
    """CBB 包计数与实测不符 → 整包入冲突不播种（fixture 库无 CBB 数据必然不符）。"""
    con = _make_db(tmp_path, {"CBB3C": [f"11{i:02d}" for i in range(1, 8)]})
    con.close()
    raw_dir = _make_tcgdex_raw(tmp_path, [])
    result = face_totals.generate_seed(tmp_path / "t.db", raw_dir)
    # CBB3C 包 11 统计 7 张 = 实测 7 → 播种
    assert result.packs["CBB3C"]["packs"] == {"11": 7}
    # CBB1C/CBB2C 库内无数据 → 与实测不符 → 冲突
    assert any("CBB1C" in c for c in result.conflicts)
    assert any("CBB2C" in c for c in result.conflicts)


def test_apply_seed_to_sets(tmp_path):
    """种子 → sets.card_face_total：total 型播种，未覆盖/ packs 型置 NULL。"""
    con = _make_db(tmp_path, {"TST1": ["001"], "TST2": ["001"]})
    con.close()
    seed_path = tmp_path / "seed.yml"
    seed_path.write_text(
        "sets:\n  TST1: {total: 100, source: tcgdex}\n"
        "  TST2: {packs: {'09': 15}, source: derived_cbb}\n",
        encoding="utf-8",
    )
    applied = face_totals.apply_seed_to_sets(tmp_path / "t.db", seed_path)
    assert applied == 1
    con = sqlite3.connect(tmp_path / "t.db")
    rows = dict(con.execute("SELECT set_id, card_face_total FROM sets").fetchall())
    con.close()
    assert rows == {"TST1": 100, "TST2": None}

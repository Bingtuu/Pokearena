"""task 030 F-02/F-03：alias 标记与太晶识别单测。"""

import json
import sqlite3

from ptcgdb.mapping.tera import fill_tera
from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.aliases import mark_aliases


def _make_db(tmp_path, cards: list[dict], external_ids: list[tuple] | None = None):
    """fixture 库：cards 最小行 + external_ids。

    cards: {card_id, set_id, number, name_full, is_basic_energy}
    """
    db_path = tmp_path / "t.db"
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    sets = {c["set_id"] for c in cards}
    for set_id in sets:
        con.execute(
            "INSERT INTO sets (set_id, name_zh, era, regulation_mark, source, fetched_at)"
            " VALUES (?, '测试', '朱&紫', 'G', 'test', '')",
            (set_id,),
        )
    for c in cards:
        con.execute(
            "INSERT INTO cards (card_id, set_id, number, number_display, name_full,"
            " card_type, rarity, has_rule_box, is_tera, prize_cards, deck_limit,"
            " is_ace_spec, is_basic_energy, text_raw, source, fetched_at, status)"
            " VALUES (?, ?, ?, ?, ?, 'energy', '无标记', 0, 0, 1, 4, 0, ?,"
            " '', 'test', '2026-01-01', 'active')",
            (
                c["card_id"], c["set_id"], c["number"], c["number"], c["name_full"],
                1 if c.get("is_basic_energy") else 0,
            ),
        )
    for cid, system, ext in external_ids or []:
        con.execute(
            "INSERT INTO external_ids (card_id, system, external_id) VALUES (?, ?, ?)",
            (cid, system, ext),
        )
    con.commit()
    con.close()
    return db_path


# ---- F-02 alias ----


def test_mark_aliases_twin_rule(tmp_path):
    db_path = _make_db(
        tmp_path,
        [
            {"card_id": "CS1-431", "set_id": "CS1", "number": "431",
             "name_full": "基本斗能量", "is_basic_energy": True},
            {"card_id": "CS1-FIG", "set_id": "CS1", "number": "FIG",
             "name_full": "基本斗能量", "is_basic_energy": True},
            {"card_id": "CS2-DAR", "set_id": "CS2", "number": "DAR",
             "name_full": "基本恶能量", "is_basic_energy": True},  # 无孪生
            {"card_id": "CS3-016", "set_id": "CS3", "number": "016",
             "name_full": "基本草能量", "is_basic_energy": True},
            {"card_id": "CS3-035", "set_id": "CS3", "number": "035",
             "name_full": "基本草能量", "is_basic_energy": True},  # 双孪生
            {"card_id": "CS3-GRA", "set_id": "CS3", "number": "GRA",
             "name_full": "基本草能量", "is_basic_energy": True},
        ],
    )
    result = mark_aliases(db_path)
    assert result.marked == {"CS1-FIG": "CS1-431"}
    assert "无数字编号孪生" in result.questions["CS2-DAR"]
    assert "孪生多张" in result.questions["CS3-GRA"]
    # 幂等：重跑结果一致
    result2 = mark_aliases(db_path)
    assert result2.marked == result.marked
    assert result2.cleared == []


# ---- F-03 太晶 ----


def _make_ptcd_raw(tmp_path):
    raw_dir = tmp_path / "raw"
    (raw_dir / "pokemon-tcg-data" / "cards-en").mkdir(parents=True)
    (raw_dir / "pokemon-tcg-data" / "sets-en.json").write_text(
        json.dumps({"sets": [{"id": "sv3", "ptcgoCode": "OBF", "name": "Obsidian Flames"}]}),
        encoding="utf-8",
    )
    (raw_dir / "pokemon-tcg-data" / "cards-en" / "sv3.json").write_text(
        json.dumps({"cards": [
            {"id": "sv3-125", "number": "125", "name": "Charizard ex",
             "subtypes": ["Stage 2", "ex", "Tera"]},
            {"id": "sv3-25", "number": "25", "name": "Pidgeot ex",
             "subtypes": ["Stage 2", "ex"]},
        ]}),
        encoding="utf-8",
    )
    return raw_dir


def test_fill_tera_resolution(tmp_path):
    raw_dir = _make_ptcd_raw(tmp_path)
    db_path = _make_db(
        tmp_path,
        [
            {"card_id": "CN-162", "set_id": "CN", "number": "162", "name_full": "喷火龙ex"},
            {"card_id": "CN-025", "set_id": "CN", "number": "025", "name_full": "大比鸟ex"},
            {"card_id": "CN-999", "set_id": "CN", "number": "999", "name_full": "查无此卡"},
            {"card_id": "CN-888", "set_id": "CN", "number": "888", "name_full": "无桥卡"},
        ],
        external_ids=[
            ("CN-162", "mik_en", "OBF-125"),
            ("CN-025", "mik_en", "OBF-25"),
            ("CN-999", "mik_en", "OBF-999"),
        ],
    )
    result = fill_tera(db_path, raw_dir)
    assert result.tera == 1
    assert result.resolved_non_tera == 1
    assert result.missing_card == ["CN-999"]
    assert result.no_bridge == ["CN-888"]
    con = sqlite3.connect(db_path)
    rows = dict(con.execute("SELECT card_id, is_tera FROM cards").fetchall())
    con.close()
    assert rows["CN-162"] == 1
    assert rows["CN-025"] == 0
    assert rows["CN-999"] == 0  # 未解析不动


def test_fill_tera_unmapped_set(tmp_path):
    raw_dir = _make_ptcd_raw(tmp_path)
    db_path = _make_db(
        tmp_path,
        [{"card_id": "CN-001", "set_id": "CN", "number": "001", "name_full": "某卡"}],
        external_ids=[("CN-001", "mik_en", "XXX-001")],
    )
    result = fill_tera(db_path, raw_dir)
    assert result.unmapped_set == ["CN-001"]
    assert result.tera == 0

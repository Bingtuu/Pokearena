"""task 004 测试：黄金样本（真实 raw fixtures）逐字段断言 + 归组/进化链/派生单测。

零网络：fixtures 为 data/raw/mikmoe/CSM1aC 真实单卡文件的逐字拷贝；
cards.json（系列级）由测试内 write_raw 重建（保持 _meta hash 有效）。
CSM1aC 无基本能量卡（字段形态调查结论），特殊能量样本为 151 彩虹能量；
基本能量样本为 CSM1DC/DAR.json（task 005 实测 cardType="Basic Energy"）。
"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.normalize import derive, fields
from ptcgdb.normalize.fields import Questions, UnknownEnumError
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, CardNameGroup, CardRelation, NameGroup, Set
from ptcgdb.scrapers.raw_store import write_raw

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
FIXTURE_CARDS = ["001", "002", "003", "004", "139", "148", "151"]

CODE_MAP = fields.load_energy_code_map()


def make_raw_dir(tmp_path: Path) -> Path:
    """复制 fixtures 到 tmp raw 目录，并重建系列级 cards.json。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CSM1aC"
    set_dir.mkdir(parents=True)
    for name in FIXTURE_CARDS:
        shutil.copy(FIXTURE_DIR / f"{name}.json", set_dir / f"{name}.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "横空出世 赫",
                "setCode": "CSM1aC",
                "setId": "CSM1aC",
                "releaseDate": "2022-10-28T00:00:00+08:00",
                "series": "Sun & Moon",
                "mainExpansion": True,
                "cardsNum": 211,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )
    return raw_dir


@pytest.fixture()
def ingested(tmp_path):
    raw_dir = make_raw_dir(tmp_path)
    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CSM1aC", db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    return result, engine


# ---- 字段映射单测 ----


def test_parse_cost_groups_consecutive_preserving_order():
    assert fields.parse_cost("CCC", CODE_MAP) == [{"type": "无", "count": 3}]
    assert fields.parse_cost("RRRCC", CODE_MAP) == [
        {"type": "火", "count": 3},
        {"type": "无", "count": 2},
    ]
    assert fields.parse_cost("WY", CODE_MAP) == [
        {"type": "水", "count": 1},
        {"type": "妖", "count": 1},
    ]
    assert fields.parse_cost("PM", CODE_MAP) == [
        {"type": "超", "count": 1},
        {"type": "钢", "count": 1},
    ]


def test_parse_cost_zero_and_empty():
    assert fields.parse_cost("", CODE_MAP) == []
    assert fields.parse_cost("0", CODE_MAP) == []  # 无费用招式（CSM1aC 实测）


def test_parse_cost_unknown_code_raises():
    with pytest.raises(UnknownEnumError):
        fields.parse_cost("Z", CODE_MAP)


def test_parse_cost_full_modifier():
    """追加费用标记（TAG TEAM GX "WWC+"，CSM2aC 实测）→ (cost 保序, "+")。"""
    items, modifier = fields.parse_cost_full("WWC+", CODE_MAP)
    assert items == [{"type": "水", "count": 2}, {"type": "无", "count": 1}]
    assert modifier == "+"
    assert fields.parse_cost_full("RC", CODE_MAP) == (
        [{"type": "火", "count": 1}, {"type": "无", "count": 1}],
        None,
    )
    assert fields.parse_cost_full("", CODE_MAP) == ([], None)
    # 无费用招式带追加标记（"0+"，CSM2bC 实测）
    assert fields.parse_cost_full("0+", CODE_MAP) == ([], "+")
    # "+" 在非尾部 → 未知形态，不猜测
    with pytest.raises(UnknownEnumError):
        fields.parse_cost_full("C+C", CODE_MAP)
    # parse_cost 对含 "+" 的串抛错而非静默丢弃
    with pytest.raises(UnknownEnumError):
        fields.parse_cost("WWC+", CODE_MAP)


def test_parse_damage_forms():
    assert fields.parse_damage("20") == (20, None)
    assert fields.parse_damage("20+") == (20, "+")
    assert fields.parse_damage("30×") == (30, "×")
    assert fields.parse_damage("10-") == (10, "-")
    assert fields.parse_damage("") == (None, None)
    assert fields.parse_damage(None) == (None, None)
    with pytest.raises(UnknownEnumError):
        fields.parse_damage("??")


def test_split_owner_species():
    owners = fields.load_owners()
    assert derive.split_owner_species("火箭队的喵喵", owners) == ("火箭队", "喵喵")
    assert derive.split_owner_species("喷火龙GX", owners) == (None, "喷火龙")
    assert derive.split_owner_species("比克提尼◇", owners) == (None, "比克提尼")
    # 地区形态不是 owner，保留在 species 内
    assert derive.split_owner_species("阿罗拉 嘎啦嘎啦", owners) == (None, "阿罗拉 嘎啦嘎啦")


def test_name_group_key_rules():
    rules = derive.load_name_group_rules()
    # §6.2：博士的研究/老大的指令跨插画同名
    assert derive.name_group_key("博士的研究（奥可博士）", rules) == "博士的研究"
    assert derive.name_group_key("老大的指令", rules) == "老大的指令"
    # ex/GX 后缀不同名，不归并
    assert derive.name_group_key("喷火龙GX", rules) == "喷火龙GX"
    assert derive.name_group_key("喷火龙", rules) == "喷火龙"


def test_deck_limit_and_prize():
    assert derive.derive_deck_limit(None, False) == 4
    assert derive.derive_deck_limit("gx", False) == 4
    assert derive.derive_deck_limit("prism_star", False) == 1  # ◇ 卡面规则限 1
    assert derive.derive_deck_limit(None, True) == 1  # ACE SPEC
    assert derive.derive_prize_cards(None) == 1
    assert derive.derive_prize_cards("gx") == 2
    assert derive.derive_prize_cards("prism_star") == 1
    assert derive.derive_prize_cards("tag_team_gx") == 3


def test_resolve_evolution_chain_and_fallback():
    questions = Questions()
    records = [
        {"card_id": "S-001", "name_full": "小火龙", "species": "小火龙",
         "card_type": "pokemon", "evolves_from_text": None},
        {"card_id": "S-002", "name_full": "火恐龙", "species": "火恐龙",
         "card_type": "pokemon", "evolves_from_text": "小火龙"},
        {"card_id": "S-003", "name_full": "喷火龙GX", "species": "喷火龙",
         "card_type": "pokemon", "evolves_from_text": "火恐龙"},
        {"card_id": "S-004", "name_full": "阿罗拉 嘎啦嘎啦", "species": "阿罗拉 嘎啦嘎啦",
         "card_type": "pokemon", "evolves_from_text": "嘎啦嘎啦"},  # 系列内无此卡
        {"card_id": "S-005", "name_full": "扎奥博", "species": None,
         "card_type": "trainer", "evolves_from_text": None},
    ]
    derive.resolve_evolution(records, questions)
    assert records[1]["evolves_from_id"] == "S-001"
    assert records[2]["evolves_from_id"] == "S-002"
    assert records[2]["evolution_chain_id"] == "S-001"  # 链根共享
    assert records[0]["evolution_chain_id"] == "S-001"
    assert records[3]["evolves_from_id"] is None  # 未解析 → None + question
    assert any(q["field"] == "evolves_from_text" for q in questions.items)
    assert records[4]["evolution_chain_id"] is None  # 非宝可梦不进链


# ---- 黄金样本：真实 raw → 入库逐字段断言 ----


def test_ingest_golden_charizard_gx(ingested):
    result, engine = ingested
    assert result.card_count == len(FIXTURE_CARDS)
    assert result.skipped == []
    with Session(engine) as session:
        c = session.get(Card, "CSM1aC-004")
        assert c.number == "004"
        assert c.number_display == "004/211"
        assert c.name_full == "喷火龙GX"
        assert c.species == "喷火龙"
        assert c.owner is None
        assert c.card_type == "pokemon"
        assert c.regulation_mark == "A"
        assert c.rarity == "RR"
        assert c.stage == "2阶"
        assert c.hp == 250
        assert c.types == ["火"]
        assert c.evolves_from_text == "火恐龙"
        assert c.evolves_from_id == "CSM1aC-003"
        assert c.evolution_chain_id == "CSM1aC-002"  # 链根=小火龙
        assert c.rule_box_type == "gx"
        assert c.has_rule_box is True
        assert c.is_tera is False
        assert c.prize_cards == 2
        assert c.deck_limit == 4
        assert c.weakness == {"type": "水", "value": "×2"}
        assert c.resistance is None
        assert c.retreat_cost == 2
        assert c.attacks[1] == {
            "name": "红莲风暴",
            "cost": [{"type": "火", "count": 3}, {"type": "无", "count": 2}],
            "cost_modifier": None,
            "damage_base": 300,
            "damage_modifier": None,
            "effect_text": "将附着于这只宝可梦身上的3个【火】能量，放于弃牌区。",
        }
        # GX 招式无固定伤害
        assert c.attacks[2]["name"] == "愤怒驱逐GX"
        assert c.attacks[2]["damage_base"] is None
        assert c.attacks[2]["damage_modifier"] is None
        assert c.status == "draft"
        assert c.source == "mik_moe"
        # text_raw 与 raw description 逐字一致
        raw = json.loads((FIXTURE_DIR / "004.json").read_text(encoding="utf-8"))
        assert c.text_raw == raw["data"]["description"]


def test_ingest_golden_basic_pokemon(ingested):
    _, engine = ingested
    with Session(engine) as session:
        c = session.get(Card, "CSM1aC-001")
        assert c.name_full == "飞天螳螂"
        assert c.species == "飞天螳螂"
        assert c.stage == "基础"
        assert c.types == ["草"]
        assert c.has_rule_box is False
        assert c.rule_box_type is None
        assert c.prize_cards == 1
        assert c.deck_limit == 4
        assert c.attacks[0]["cost"] == [{"type": "无", "count": 1}]
        assert c.attacks[0]["damage_base"] is None
        assert c.evolution_chain_id == "CSM1aC-001"  # 自身即链根


def test_ingest_golden_stage1_ability(ingested):
    _, engine = ingested
    with Session(engine) as session:
        c = session.get(Card, "CSM1aC-003")
        assert c.stage == "1阶"
        assert c.evolves_from_id == "CSM1aC-002"
        assert c.evolution_chain_id == "CSM1aC-002"
        assert c.abilities[0]["name"] == "燃烧斗志"
        assert c.attacks[0]["cost"] == [
            {"type": "火", "count": 2},
            {"type": "无", "count": 1},
        ]


def test_ingest_golden_trainer_and_stadium_and_energy(ingested):
    result, engine = ingested
    with Session(engine) as session:
        sup = session.get(Card, "CSM1aC-139")
        assert sup.name_full == "扎奥博"
        assert sup.card_type == "trainer"
        assert sup.trainer_subtype == "支援者"
        assert sup.species is None
        assert sup.stage is None
        assert sup.has_rule_box is False

        stadium = session.get(Card, "CSM1aC-148")
        assert stadium.name_full == "火力工厂◇"
        assert stadium.trainer_subtype == "竞技场"
        assert stadium.rule_box_type == "prism_star"
        assert stadium.has_rule_box is True
        assert stadium.deck_limit == 1  # ◇ 卡面规则限 1
        assert stadium.prize_cards == 1

        energy = session.get(Card, "CSM1aC-151")
        assert energy.name_full == "彩虹能量"
        assert energy.card_type == "energy"
        assert energy.is_basic_energy is False
        assert energy.provides is None  # 特殊能量 provides 未结构化，见 questions
        assert any(
            q["card_id"] == "CSM1aC-151" and q["field"] == "provides"
            for q in result.questions.items
        )


def test_ingest_set_row_and_grouping_and_relations(ingested):
    result, engine = ingested
    with Session(engine) as session:
        s = session.get(Set, "CSM1aC")
        assert s.name_zh == "横空出世 赫"
        assert s.era == "太阳&月亮"
        assert s.expected_count == 211
        # fixtures 内赛制标记混合（004/151=A，其余=B）→ 逗号连接并记 question
        assert s.regulation_mark == "A,B"
        assert any(q["field"] == "regulation_mark" for q in result.questions.items)

        # 归组：GX 后缀不同名，组 key = name_full
        groups = {row.card_id: row.group_key for row in session.query(CardNameGroup)}
        assert groups["CSM1aC-004"] == "喷火龙GX"
        assert session.get(NameGroup, "喷火龙GX") is not None

        rels = {
            (r.card_id, r.related_card_id, r.relation_type)
            for r in session.query(CardRelation)
        }
        assert ("CSM1aC-004", "CSM1aC-003", "evolves_from") in rels
        assert ("CSM1aC-003", "CSM1aC-004", "evolves_to") in rels


def test_ingest_idempotent_rerun(ingested, tmp_path):
    _, engine = ingested
    result2 = ingest_set(tmp_path / "raw", "CSM1aC", tmp_path / "test.db")
    assert result2.card_count == len(FIXTURE_CARDS)
    with Session(engine) as session:
        assert session.query(Card).count() == len(FIXTURE_CARDS)


def test_unknown_enum_zero_guess(tmp_path):
    """未知枚举不猜测：卡片不入库 + question 上报。"""
    raw_dir = make_raw_dir(tmp_path)
    bad = json.loads((FIXTURE_DIR / "001.json").read_text(encoding="utf-8"))
    bad["data"]["pokemonAttr"]["energyType"] = "Z"  # 词表外属性码
    bad["data"]["cardIndex"] = "009"
    payload = {k: v for k, v in bad.items() if k != "_meta"}
    write_raw(raw_dir / "mikmoe" / "CSM1aC" / "009.json", payload, source="mik_moe")

    result = ingest_set(raw_dir, "CSM1aC", tmp_path / "test.db")
    assert result.card_count == len(FIXTURE_CARDS)
    assert result.skipped == ["009.json"]
    assert any(
        q["card_id"] == "CSM1aC-009" and "未知" in q["note"]
        for q in result.questions.items
    )


# ---- 基本能量黄金样本：CSM1DC/DAR（task 005 实测 cardType="Basic Energy"）----

FIXTURE_CSM1DC_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1DC"


def test_ingest_golden_basic_energy(tmp_path):
    """基本恶能量：cardType=Basic Energy → energy/is_basic_energy；空赛制标记存 NULL。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CSM1DC"
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_CSM1DC_DIR / "DAR.json", set_dir / "DAR.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "起始卡组 横空出世GX",
                "setCode": "CSM1DC",
                "setId": "CSM1DC",
                "releaseDate": "2022-10-28T00:00:00+08:00",
                "series": "Sun & Moon",
                "mainExpansion": False,
                "cardsNum": 345,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CSM1DC", db_path)
    assert result.card_count == 1
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "CSM1DC-DAR")
        assert c.name_full == "基本恶能量"
        assert c.number == "DAR"
        assert c.card_type == "energy"
        assert c.trainer_subtype is None
        assert c.is_basic_energy is True
        assert c.provides == ["恶"]
        assert c.regulation_mark is None  # 空赛制标记统一存 NULL
        assert c.rarity == "无标记"
        assert c.has_rule_box is False
        # 系列行：全部卡无赛制标记 → 空串
        assert session.get(Set, "CSM1DC").regulation_mark == ""
    engine.dispose()


# ---- TAG TEAM GX 黄金样本：CSM2aC/003（task 005 实测 mechanic=GX + label=TAG TEAM）----

FIXTURE_CSM2AC_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM2aC"


def test_ingest_golden_tag_team_gx(tmp_path):
    """水箭龟&波加曼GX：tag_team_gx/prize=3/cost 追加标记无损（"WWC+" → cost_modifier="+"）。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CSM2aC"
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_CSM2AC_DIR / "003.json", set_dir / "003.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "交相辉映 沐",
                "setCode": "CSM2aC",
                "setId": "CSM2aC",
                "releaseDate": "2023-01-18T00:00:00+08:00",
                "series": "Sun & Moon",
                "mainExpansion": True,
                "cardsNum": 194,  # mik 口径：含 23 张编号外 SR（172~194）
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CSM2aC", db_path)
    assert result.card_count == 1
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "CSM2aC-003")
        assert c.name_full == "水箭龟&波加曼GX"
        assert c.species == "水箭龟&波加曼"
        assert c.rule_box_type == "tag_team_gx"
        assert c.has_rule_box is True
        assert c.prize_cards == 3
        assert c.deck_limit == 4
        assert c.effect_tags is None  # TAG TEAM 由 rule_box 消费，不进 effect_tags
        gx_attack = c.attacks[1]
        assert gx_attack["name"] == "泡沫喷射器GX"
        assert gx_attack["cost"] == [{"type": "水", "count": 2}, {"type": "无", "count": 1}]
        assert gx_attack["cost_modifier"] == "+"
        assert gx_attack["damage_base"] == 100
        assert gx_attack["damage_modifier"] == "+"
    engine.dispose()


# ---- 宝可梦V 黄金样本：CSAC/001（task 005 实测 mechanic="V"）----

FIXTURE_CSAC_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSAC"


def test_ingest_golden_pokemon_v(tmp_path):
    """轰擂金刚猩V：mechanic="V" → rule_box_type=v、prize=2、species 去 V 后缀。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CSAC"
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_CSAC_DIR / "001.json", set_dir / "001.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "卡组构筑礼盒 极巨争锋",
                "setCode": "CSAC",
                "setId": "CSAC",
                "releaseDate": "2023-05-19T00:00:00+08:00",
                "series": "Sword & Shield",
                "mainExpansion": False,
                "cardsNum": 32,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CSAC", db_path)
    assert result.card_count == 1
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "CSAC-001")
        assert c.name_full == "轰擂金刚猩V"
        assert c.species == "轰擂金刚猩"
        assert c.rule_box_type == "v"
        assert c.has_rule_box is True
        assert c.prize_cards == 2
        assert c.deck_limit == 4
    engine.dispose()


# ---- 宝可梦VMAX 黄金样本：CS1DC/003（task 005 实测 mechanic="V" + stage="VMAX"）----

FIXTURE_CS1DC_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CS1DC"


def test_ingest_golden_pokemon_vmax(tmp_path):
    """巴大蝶VMAX：stage 覆盖 → rule_box_type=vmax、prize=3、stage='VMAX' 原值入库。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CS1DC"
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_CS1DC_DIR / "003.json", set_dir / "003.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "极巨争锋 V起始卡组",
                "setCode": "CS1DC",
                "setId": "CS1DC",
                "releaseDate": "2023-05-19T00:00:00+08:00",
                "series": "Sword & Shield",
                "mainExpansion": False,
                "cardsNum": 226,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CS1DC", db_path)
    assert result.card_count == 1
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "CS1DC-003")
        assert c.name_full == "巴大蝶VMAX"
        assert c.species == "巴大蝶"
        assert c.stage == "VMAX"
        assert c.rule_box_type == "vmax"
        assert c.has_rule_box is True
        assert c.prize_cards == 3
        assert c.deck_limit == 4
        assert c.hp == 300
        assert c.evolves_from_text == "巴大蝶V"
    engine.dispose()


# ---- V-UNION 黄金样本：SSP/109~112（task 005 实测 stage="V-UNION" 四部件同构）----

FIXTURE_SSP_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "SSP"


def test_ingest_golden_v_union(tmp_path):
    """皮卡丘V-UNION 四部件：v_union/prize=3/deck_limit=1；union_part_of 星形关系。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "SSP"
    set_dir.mkdir(parents=True)
    for n in ("109", "110", "111", "112"):
        shutil.copy(FIXTURE_SSP_DIR / f"{n}.json", set_dir / f"{n}.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "四方联结礼盒",
                "setCode": "SSP",
                "setId": "SSP",
                "releaseDate": "2023-09-01T00:00:00+08:00",
                "series": "Sword & Shield",
                "mainExpansion": False,
                "cardsNum": 300,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "SSP", db_path)
    assert result.card_count == 4
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "SSP-109")
        assert c.name_full == "皮卡丘V-UNION"
        assert c.species == "皮卡丘"
        assert c.stage == "V-UNION"
        assert c.rule_box_type == "v_union"
        assert c.prize_cards == 3
        assert c.deck_limit == 1
        assert c.union_position is None  # mik 无方位字段（task 005 实测）
        rels = {
            (r.card_id, r.related_card_id)
            for r in session.query(CardRelation).filter_by(relation_type="union_part_of")
        }
        # 星形边：110/111/112 → 109（组内最小 card_id）
        assert rels == {
            ("SSP-110", "SSP-109"),
            ("SSP-111", "SSP-109"),
            ("SSP-112", "SSP-109"),
        }
    engine.dispose()


def test_ingest_golden_vstar(tmp_path):
    """喷火龙VSTAR：stage="VSTAR"（mechanic=None）→ vstar/prize=2。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "SSP"
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_SSP_DIR / "143.json", set_dir / "143.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "四方联结礼盒",
                "setCode": "SSP",
                "setId": "SSP",
                "releaseDate": "2023-09-01T00:00:00+08:00",
                "series": "Sword & Shield",
                "mainExpansion": False,
                "cardsNum": 300,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "SSP", db_path)
    assert result.card_count == 1
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "SSP-143")
        assert c.name_full == "喷火龙VSTAR"
        assert c.species == "喷火龙"
        assert c.stage == "VSTAR"
        assert c.rule_box_type == "vstar"
        assert c.prize_cards == 2
        assert c.deck_limit == 4
        assert c.hp == 280
    engine.dispose()


FIXTURE_CS5BC_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CS5bC"


def test_ingest_radiant(tmp_path):
    """光辉妙蛙花：mechanic="Radiant" → radiant/prize=1/deck_limit=1（task 005 实测）。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CS5bC"
    set_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_CS5BC_DIR / "004.json", set_dir / "004.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "强化扩充包 终末炎舞",
                "setCode": "CS5bC",
                "setId": "CS5bC",
                "releaseDate": "2024-06-18T00:00:00+08:00",
                "series": "Sword & Shield",
                "mainExpansion": False,
                "cardsNum": 178,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CS5bC", db_path)
    assert result.card_count == 1
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "CS5bC-004")
        assert c.name_full == "光辉妙蛙花"
        assert c.rule_box_type == "radiant"
        assert c.prize_cards == 1
        assert c.deck_limit == 1
        assert c.rarity == "K"
        assert c.regulation_mark == "F"
    engine.dispose()


FIXTURE_SVP_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "SVP"


def test_ingest_ex_and_ancient_future(tmp_path):
    """朱紫 ex / 古代·未来 label（task 005 实测）：
    梦幻ex mechanic="ex" → ex/prize=2；轰鸣月ex label=Ancient → 古代；
    雄伟牙 非 ex + label=Ancient → rule_box 空 + 古代。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "SVP"
    set_dir.mkdir(parents=True)
    for n in ("003", "117", "253"):
        shutil.copy(FIXTURE_SVP_DIR / f"{n}.json", set_dir / f"{n}.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "朱&紫 特典卡",
                "setCode": "SVP",
                "setId": "SVP",
                "releaseDate": "2024-01-01T00:00:00+08:00",
                "series": "Scarlet & Violet",
                "mainExpansion": False,
                "cardsNum": 442,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "SVP", db_path)
    assert result.card_count == 3
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "SVP-003")
        assert c.name_full == "梦幻ex"
        assert c.rule_box_type == "ex"
        assert c.prize_cards == 2
        assert c.deck_limit == 4

        c = session.get(Card, "SVP-117")
        assert c.name_full == "轰鸣月ex"
        assert c.rule_box_type == "ex"
        assert c.prize_cards == 2
        assert "古代" in (c.effect_tags or "")

        c = session.get(Card, "SVP-253")
        assert c.name_full == "雄伟牙"
        assert c.rule_box_type is None
        assert "古代" in (c.effect_tags or "")
    engine.dispose()


FIXTURE_CSV7C_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSV7C"


def test_ingest_ace_spec(tmp_path):
    """ACE SPEC（task 005 实测）：物品/特殊能量 mechanic="ACE SPEC" →
    is_ace_spec=True、deck_limit=1、rule_box_type=None、rarity=ACE，不报未知枚举。"""
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CSV7C"
    set_dir.mkdir(parents=True)
    for n in ("178", "203"):
        shutil.copy(FIXTURE_CSV7C_DIR / f"{n}.json", set_dir / f"{n}.json")
    write_raw(
        set_dir / "cards.json",
        {
            "code": 200,
            "data": {
                "name": "补充包 星晶奇迹",
                "setCode": "CSV7C",
                "setId": "CSV7C",
                "releaseDate": "2025-01-01T00:00:00+08:00",
                "series": "Scarlet & Violet",
                "mainExpansion": True,
                "cardsNum": 261,
                "cards": [],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )

    db_path = tmp_path / "test.db"
    result = ingest_set(raw_dir, "CSV7C", db_path)
    assert result.card_count == 2
    assert result.skipped == []

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        c = session.get(Card, "CSV7C-178")
        assert c.name_full == "高级香氛"
        assert c.is_ace_spec is True
        assert c.deck_limit == 1
        assert c.rule_box_type is None
        assert c.rarity == "ACE"

        c = session.get(Card, "CSV7C-203")
        assert c.name_full == "新冲天能量"
        assert c.is_ace_spec is True
        assert c.deck_limit == 1
        assert c.rarity == "ACE"
    engine.dispose()

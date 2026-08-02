"""task 024 测试：JP 名字级映射——EN TCGdex id → dexId → 日文物种名 + 词表组合。

零网络：ptcd 卡数据 / PokéAPI 物种名表 / TCGdex 数据均为 fixture 构造。
设计前提（task 023 实测）：TCGdex EN/JA 卡 id 不共构 → 名字级映射（PRD v1.6）。
"""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from ptcgdb.mapping.en import fill_en
from ptcgdb.mapping.ja import (
    build_ja_name,
    fill_ja,
    load_ja_rules,
    load_ja_species,
    load_ptcd_dex_index,
)
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, ExternalId
from ptcgdb.scrapers.raw_store import write_raw

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
FIXTURE_CARDS = ["001", "002", "003", "004", "139", "148", "151"]

PTCD_SETS = [
    {"id": "sm3", "name": "Burning Shadows", "ptcgoCode": "BUS"},
]
TCGDEX_EN_SETS = [
    {"id": "sm3", "name": "Burning Shadows", "cardCount": {"total": 169}},
]
EN_CARDS = [
    {"id": "sm3-20", "localId": "20", "name": "Charizard GX"},
    {"id": "sm3-21", "localId": "21", "name": "Pikachu & Zekrom GX"},
    {"id": "sm3-22", "localId": "22", "name": "Galarian Zigzagoon"},
    {"id": "sm3-23", "localId": "23", "name": "Shaymin"},
]
PTCD_CARDS_SM3 = [
    {"id": "sm3-20", "number": "20", "name": "Charizard-GX", "nationalPokedexNumbers": [6]},
    {"id": "sm3-21", "number": "21", "name": "Pikachu & Zekrom-GX",
     "nationalPokedexNumbers": [25, 644]},
    {"id": "sm3-22", "number": "22", "name": "Galarian Zigzagoon",
     "nationalPokedexNumbers": [263]},
    {"id": "sm3-23", "number": "23", "name": "Shaymin", "nationalPokedexNumbers": [492]},
]
SPECIES_CSV = (
    "pokemon_species_id,local_language_id,name,genus\n"
    "6,9,Charizard,Flame Pokémon\n"
    "6,11,リザードン,かえんポケモン\n"
    "25,9,Pikachu,Mouse Pokémon\n"
    "25,11,ピカチュウ,ねずみポケモン\n"
    "263,9,Zigzagoon,Tiny Raccoon Pokémon\n"
    "263,11,ジグザグマ,あらいぐまポケモン\n"
    "492,9,Shaymin,Gratitude Pokémon\n"
    "492,11,シェイミ,かんしゃポケモン\n"
    "644,9,Zekrom,Deep Black Pokémon\n"
    "644,11,ゼクロム,こくいんポケモン\n"
)


def make_raw(tmp_path: Path) -> Path:
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
                "name": "横空出世 赫", "setCode": "CSM1aC", "setId": "CSM1aC",
                "releaseDate": "2022-10-28T00:00:00+08:00", "series": "Sun & Moon",
                "mainExpansion": True, "cardsNum": 211,
                "cards": [{"setCode": "CSM1aC", "cardIndex": n} for n in FIXTURE_CARDS],
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )
    write_raw(raw_dir / "pokemon-tcg-data" / "sets-en.json",
              {"sets": PTCD_SETS}, source="pokemon_tcg_data")
    write_raw(raw_dir / "pokemon-tcg-data" / "cards-en" / "sm3.json",
              {"cards": PTCD_CARDS_SM3}, source="pokemon_tcg_data")
    write_raw(raw_dir / "tcgdex" / "en-sets.json",
              {"sets": TCGDEX_EN_SETS}, source="tcgdex")
    write_raw(raw_dir / "tcgdex" / "en-cards.json",
              {"cards": EN_CARDS}, source="tcgdex")
    write_raw(raw_dir / "tcgdex" / "zh-cn-sets.json", {"sets": []}, source="tcgdex")
    write_raw(raw_dir / "pokeapi" / "pokemon-species-names.json",
              {"csv": SPECIES_CSV}, source="pokeapi")
    return raw_dir


@pytest.fixture()
def prepped(tmp_path):
    raw_dir = make_raw(tmp_path)
    db_path = tmp_path / "test.db"
    ingest_set(raw_dir, "CSM1aC", db_path)
    fill_en(db_path, raw_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.execute(delete(ExternalId))
        bridges = {
            "CSM1aC-001": ("BUS-20", "Charizard-GX", "pokemon"),
            "CSM1aC-002": ("BUS-21", "Pikachu & Zekrom-GX", "pokemon"),  # TAG TEAM
            "CSM1aC-003": ("BUS-22", "Galarian Zigzagoon", "pokemon"),
            "CSM1aC-004": ("BUS-23", "Shaymin Sky Forme", "pokemon"),  # 词表外 → question
            "CSM1aC-139": ("ZZZ-1", "Unknown Mon", "pokemon"),         # 无映射 → question
            "CSM1aC-148": ("BUS-24", "Professor's Research", "trainer"),  # 训练家
            "CSM1aC-151": ("BUS-25", "Grass Energy", "energy"),        # 基本能量词表
        }
        for card_id, (ext, name_en, card_type) in bridges.items():
            session.merge(ExternalId(card_id=card_id, system="mik_en", external_id=ext))
            card = session.get(Card, card_id)
            card.name_en = name_en
            card.card_type = card_type
        session.commit()
    engine.dispose()
    return raw_dir, db_path


def test_load_ja_species(prepped):
    raw_dir, _ = prepped
    species = load_ja_species(raw_dir)
    assert species[6] == "リザードン"
    assert species[263] == "ジグザグマ"


def test_load_ptcd_dex_index(prepped):
    raw_dir, _ = prepped
    dex = load_ptcd_dex_index(raw_dir)
    # TCGdex id → dexIds（经名字连接 sm3→sm3 + 编号归一）
    assert dex["sm3-20"] == [6]
    assert dex["sm3-21"] == [25, 644]
    assert dex["sm3-22"] == [263]


def test_build_ja_name():
    rules = load_ja_rules()
    ja = {6: "リザードン", 25: "ピカチュウ", 263: "ジグザグマ", 492: "シェイミ",
          644: "ゼクロム"}
    en = {6: "Charizard", 25: "Pikachu", 263: "Zigzagoon", 492: "Shaymin",
          644: "Zekrom"}
    # 纯物种
    assert build_ja_name("Charizard", [6], rules, ja, en) == "リザードン"
    # 机制尾缀
    assert build_ja_name("Charizard-GX", [6], rules, ja, en) == "リザードンGX"
    # 地区形态前缀（官方带半角空格：ガラル ジグザグマ）
    assert build_ja_name("Galarian Zigzagoon", [263], rules, ja, en) == "ガラル ジグザグマ"
    # 棱镜星
    assert build_ja_name("Shaymin Prism Star", [492], rules, ja, en) == "シェイミ◇"
    # TAG TEAM 多物种（dexIds 与成分顺序对齐）
    assert build_ja_name("Pikachu & Zekrom-GX", [25, 644], rules, ja, en) \
        == "ピカチュウ&ゼクロムGX"
    # 成分带前缀的 TAG TEAM
    assert build_ja_name("Raichu & Alolan Raichu-GX", [25, 25], rules,
                         {25: "ライチュウ"}, {25: "Raichu"}) == "ライチュウ&アローラ ライチュウGX"
    # 后置修饰（官方「种名 + 空格 + 修饰」：ガチグマ アカツキex）
    assert build_ja_name("Bloodmoon Ursaluna ex", [901], rules,
                         {901: "ガチグマ"}, {901: "Ursaluna"}) == "ガチグマ アカツキex"
    # オーガポン面具（同为后置修饰）
    assert build_ja_name("Teal Mask Ogerpon ex", [1017], rules,
                         {1017: "オーガポン"}, {1017: "Ogerpon"}) == "オーガポン みどりのめんex"
    # はくば/こくば（平假名连写，非漢字）
    assert build_ja_name("Shadow Rider Calyrex V", [898], rules,
                         {898: "バドレックス"}, {898: "Calyrex"}) == "こくばバドレックスV"
    # dexIds 顺序与成分错位（ptcd 实测）→ 池匹配
    assert build_ja_name("Mega Lopunny & Jigglypuff-GX", [39, 428], rules,
                         {39: "プリン", 428: "ミミロップ"},
                         {39: "Jigglypuff", 428: "Lopunny"}) == "メガミミロップ&プリンGX"
    # 训练家归属（"{X}'s" → "{JA}の"）
    assert build_ja_name("N's Zoroark", [571], rules,
                         {571: "ゾロアーク"}, {571: "Zoroark"}) == "Nのゾロアーク"
    # 词表外归属 → None
    assert build_ja_name("Giovanni's Persian", [53], rules,
                         {53: "ペルシアン"}, {53: "Persian"}) is None
    # 基本能量
    assert build_ja_name("Grass Energy", [], rules, ja, en) == "基本草エネルギー"
    # 词表外前缀 → None（不猜）
    assert build_ja_name("Shadow Lugia", [249], rules, {249: "ルギア"}, {249: "Lugia"}) is None
    # 词表外物种（dexId 不在表）→ None
    assert build_ja_name("MissingNo", [9999], rules, ja, en) is None
    # TAG TEAM 成分数与 dexIds 不齐 → None
    assert build_ja_name("Pikachu & Zekrom-GX", [25], rules, ja, en) is None
    # dexIds 缺口兜底：核心名反查 species_by_en（ptcd 缺 nationalPokedexNumbers）
    rev = {"fluttermane": 987}
    assert build_ja_name("Flutter Mane", [], rules, {987: "ハバタクカミ"},
                         {987: "Flutter Mane"}, rev) == "ハバタクカミ"
    # 兜底也不猜：反查不到 → None
    assert build_ja_name("MissingNo", [], rules, ja, en, rev) is None


def test_fill_ja(prepped):
    raw_dir, db_path = prepped
    result = fill_ja(db_path, raw_dir)
    # external_ids(system='tcgdex') 落库 = resolve 出 ID 的集合（4 张 sm3 卡）
    assert result.external_ids_written == 4
    # name_ja：Charizard-GX / TAG TEAM / Galarian Zigzagoon / Grass Energy
    assert result.name_ja_filled == 4
    assert result.questions["trainer"] == ["CSM1aC-148"]
    assert result.questions["no_set_map"] == ["CSM1aC-139"]
    assert result.questions["name_unmatched"] == ["CSM1aC-004"]
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Card, "CSM1aC-001").name_ja == "リザードンGX"
        assert session.get(Card, "CSM1aC-002").name_ja == "ピカチュウ&ゼクロムGX"
        assert session.get(Card, "CSM1aC-003").name_ja == "ガラル ジグザグマ"
        assert session.get(Card, "CSM1aC-151").name_ja == "基本草エネルギー"
        assert session.get(Card, "CSM1aC-148").name_ja is None
        ext = session.get(ExternalId, {"card_id": "CSM1aC-001", "system": "tcgdex"})
        assert ext.external_id == "sm3-20"
    engine.dispose()

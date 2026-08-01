"""task 023 测试：TCGdex 接入——setCodeEn→TCGdex ID 解析 + 系列级对账。

零网络：TCGdex / pokemon-tcg-data 响应均为 fixture 构造（write_raw 落 tmp raw 层）。
EN/JA 卡 id 不共构（task 023 实测），本任务只做 EN 侧解析与 zh-cn 系列壳对账。
"""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from ptcgdb.mapping.en import fill_en
from ptcgdb.mapping.tcgdex import load_set_map, reconcile_sets, resolve_en
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, ExternalId
from ptcgdb.scrapers.raw_store import write_raw

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
FIXTURE_CARDS = ["001", "002", "003", "004", "139", "148", "151"]
CARD_IDS = [f"CSM1aC-{n}" for n in FIXTURE_CARDS]

PTCD_SETS = [
    {"id": "sv2", "name": "Burning Shadows", "ptcgoCode": "BUS"},  # ptcd id 与 TCGdex 分叉
    {"id": "sv9", "name": "Paldea Evolved", "ptcgoCode": "PAL"},
    {"id": "sm3tg", "name": "Burning Shadows Trainer Gallery", "ptcgoCode": "BUS"},  # 同码子集
    {"id": "nopromo", "name": "No Ptcgo Set"},
]
TCGDEX_EN_SETS = [
    {"id": "sm3", "name": "Burning Shadows", "cardCount": {"total": 169}},
    {"id": "sm3tg", "name": "Burning Shadows Trainer Gallery", "cardCount": {"total": 30}},
    {"id": "sv02", "name": "Paldea Evolved", "cardCount": {"total": 279}},
    {"id": "svp", "name": "Scarlet & Violet Black Star Promos", "cardCount": {"total": 102}},
    {"id": "swshp", "name": "SWSH Black Star Promos", "cardCount": {"total": 307}},
]
EN_CARDS = [
    {"id": "sm3-20", "localId": "20", "name": "Charizard GX"},
    {"id": "sv02-45", "localId": "45", "name": "Pawmi"},
    {"id": "sm3-007", "localId": "007", "name": "Pikachu"},  # 零填充 localId 情形
    {"id": "swshp-SWSH017", "localId": "SWSH017", "name": "Toxtricity V"},  # 字母前缀编号
]
ZHCN_SETS = [
    {"id": "CSM1aC", "name": "横空出世 赫", "cardCount": {"total": 7, "official": 7}},
    {"id": "CSM9zC", "name": "不存在的系列", "cardCount": {"total": 5, "official": 5}},
]


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
    # TCGdex / pokemon-tcg-data 侧 fixture
    write_raw(
        raw_dir / "pokemon-tcg-data" / "sets-en.json",
        {"sets": PTCD_SETS}, source="pokemon_tcg_data",
    )
    write_raw(
        raw_dir / "tcgdex" / "en-sets.json",
        {"sets": TCGDEX_EN_SETS}, source="tcgdex",
    )
    write_raw(
        raw_dir / "tcgdex" / "en-cards.json",
        {"cards": EN_CARDS}, source="tcgdex",
    )
    write_raw(
        raw_dir / "tcgdex" / "zh-cn-sets.json",
        {"sets": ZHCN_SETS}, source="tcgdex",
    )
    return raw_dir


@pytest.fixture()
def prepped(tmp_path):
    raw_dir = make_raw(tmp_path)
    db_path = tmp_path / "test.db"
    ingest_set(raw_dir, "CSM1aC", db_path)
    fill_en(db_path, raw_dir)  # external_ids(mik_en) 先落（真实 fixture 值）
    # 覆盖为受控桥值 + 受控 name_en，构造五种解析情形
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.execute(delete(ExternalId))
        bridges = {
            "CSM1aC-001": ("BUS-20", "Charizard-GX"),   # 名字连接解析成功（名字归一匹配）
            "CSM1aC-002": ("PAL-45", "Pawmi"),          # 解析成功
            "CSM1aC-003": ("ZZZ-1", "Unknown"),         # setCodeEn 无映射
            "CSM1aC-004": ("BUS-99", "Nobody"),         # 卡 id 不存在
            "CSM1aC-139": ("BUS-20", "Totally Different"),  # 名字不匹配
            "CSM1aC-148": ("NOP-1", "No Ptcgo"),        # setCodeEn 无 ptcgoCode 映射
            "CSM1aC-151": ("BUS-7", "Pikachu"),         # 零填充回退命中 sm3-007
        }
        for card_id, (ext, name_en) in bridges.items():
            session.merge(ExternalId(card_id=card_id, system="mik_en", external_id=ext))
            session.get(Card, card_id).name_en = name_en
        session.commit()
    engine.dispose()
    return raw_dir, db_path


def test_load_set_map(prepped):
    raw_dir, _ = prepped
    # 名字连接：ptcd(ptcgoCode→name) × TCGdex en-sets(name→id)，ptcd 自身 id 不参与
    set_map = load_set_map(raw_dir, overrides_path=None)
    assert set_map == {"BUS": "sm3", "PAL": "sv02"}


def test_load_set_map_overrides(prepped, tmp_path):
    raw_dir, _ = prepped
    overrides = tmp_path / "overrides.yml"
    overrides.write_text("SVP: svp\n", encoding="utf-8")
    set_map = load_set_map(raw_dir, overrides_path=overrides)
    assert set_map["SVP"] == "svp"
    assert set_map["BUS"] == "sm3"  # 名字连接部分不受影响


def test_resolve_en(prepped):
    raw_dir, db_path = prepped
    result = resolve_en(db_path, raw_dir, overrides_path=None)
    assert result.total == 7
    assert sorted(result.resolved) == ["CSM1aC-001", "CSM1aC-002", "CSM1aC-151"]
    assert result.tcgdex_ids["CSM1aC-001"] == "sm3-20"
    assert result.tcgdex_ids["CSM1aC-002"] == "sv02-45"
    assert result.tcgdex_ids["CSM1aC-151"] == "sm3-007"  # 零填充回退
    assert sorted(result.unmapped_set) == ["NOP", "ZZZ"]
    assert result.missing_card == ["CSM1aC-004"]
    assert result.name_mismatch == ["CSM1aC-139"]
    # 名字归一：Charizard-GX ≡ Charizard GX（连字符/大小写不敏感）
    assert "CSM1aC-001" not in result.name_mismatch


def test_resolve_en_suffix_fallback(prepped, tmp_path):
    """字母前缀编号兜底：SP-17 → swshp-SWSH017（促销套 localId 带 SWSH 前缀）。"""
    raw_dir, db_path = prepped
    overrides = tmp_path / "overrides.yml"
    overrides.write_text("SP: swshp\n", encoding="utf-8")
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        row = session.get(ExternalId, {"card_id": "CSM1aC-148", "system": "mik_en"})
        row.external_id = "SP-17"
        session.get(Card, "CSM1aC-148").name_en = "Toxtricity V"
        session.commit()
    engine.dispose()
    result = resolve_en(db_path, raw_dir, overrides_path=overrides)
    assert result.tcgdex_ids["CSM1aC-148"] == "swshp-SWSH017"
    assert "CSM1aC-148" in result.resolved


def test_resolve_en_subset_fallback(prepped):
    """子集套解析：BUS-TG2 → sm3tg-TG02（TG 前缀 + 数字两位填充 + 子集套）。"""
    raw_dir, db_path = prepped
    write_raw(
        raw_dir / "tcgdex" / "en-cards.json",
        {"cards": EN_CARDS + [{"id": "sm3tg-TG02", "localId": "TG02", "name": "Eevee GX"}]},
        source="tcgdex", force=True,
    )
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        row = session.get(ExternalId, {"card_id": "CSM1aC-148", "system": "mik_en"})
        row.external_id = "BUS-TG2"
        session.get(Card, "CSM1aC-148").name_en = "Eevee-GX"
        session.commit()
    engine.dispose()
    result = resolve_en(db_path, raw_dir, overrides_path=None)
    assert result.tcgdex_ids["CSM1aC-148"] == "sm3tg-TG02"
    assert "CSM1aC-148" in result.resolved


def test_reconcile_sets(prepped):
    raw_dir, db_path = prepped
    report = reconcile_sets(db_path, raw_dir)
    matched = {r.set_id: r for r in report.rows if r.status == "ok"}
    assert "CSM1aC" in matched
    assert matched["CSM1aC"].tcgdex_total == 7
    assert matched["CSM1aC"].db_count == 7
    missing_in_db = [r.set_id for r in report.rows if r.status == "missing_in_db"]
    assert missing_in_db == ["CSM9zC"]
    missing_in_tcgdex = [r.set_id for r in report.rows if r.status == "missing_in_tcgdex"]
    assert missing_in_tcgdex == []  # 本 fixture 本库仅 CSM1aC，zh-cn 壳有收录

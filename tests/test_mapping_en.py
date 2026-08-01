"""task 022 测试：EN 映射填充（mik raw 英文桥 → name_en + external_ids(mik_en)）。

零网络：fixtures 为真实 raw 拷贝；无桥卡由 fixture 改构造（30thP 特典形态模拟）。
"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.mapping.en import fill_en
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, ExternalId
from ptcgdb.scrapers.raw_store import write_raw

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
FIXTURE_CARDS = ["001", "002", "003", "004", "139", "148", "151"]


def make_raw(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / "CSM1aC"
    set_dir.mkdir(parents=True)
    entries = [{"setCode": "CSM1aC", "cardIndex": name} for name in FIXTURE_CARDS]
    for name in FIXTURE_CARDS:
        shutil.copy(FIXTURE_DIR / f"{name}.json", set_dir / f"{name}.json")
    # 无英文桥的卡：复制 004 并剥掉桥字段与旧 _meta、改 cardIndex（模拟简中独占特典）
    doc = json.loads((FIXTURE_DIR / "004.json").read_text(encoding="utf-8"))
    doc.pop("_meta", None)
    for key in ("nameEn", "setCodeEn", "cardIndexEn"):
        doc["data"].pop(key, None)
    doc["data"]["cardIndex"] = "099"
    write_raw(set_dir / "099.json", doc, source="mik_moe")
    entries.append({"setCode": "CSM1aC", "cardIndex": "099"})
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
                "cards": entries,
            },
            "msg": "OK.",
        },
        source="mik_moe",
    )
    return raw_dir


@pytest.fixture()
def prepped(tmp_path):
    raw_dir = make_raw(tmp_path)
    db_path = tmp_path / "test.db"
    ingest_set(raw_dir, "CSM1aC", db_path)
    return raw_dir, db_path


def test_fill_en_basic(prepped):
    raw_dir, db_path = prepped
    result = fill_en(db_path, raw_dir)
    assert result.total == 8
    # name_en 由 ingest 入库时已填充（ingest.py:115），此处 already；external_ids 为本任务新增
    assert result.filled == 0
    assert result.already == 7
    assert result.no_bridge == ["CSM1aC-099"]
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        card = session.get(Card, "CSM1aC-004")
        assert card.name_en == "Charizard-GX"
        row = session.get(ExternalId, ("CSM1aC-004", "mik_en"))
        assert row is not None
        assert row.external_id == "BUS-20"
        # 无桥卡：无 name_en、无 external_ids 行
        assert session.get(Card, "CSM1aC-099").name_en is None
        assert session.get(ExternalId, ("CSM1aC-099", "mik_en")) is None
    engine.dispose()


def test_fill_en_idempotent(prepped):
    raw_dir, db_path = prepped
    first = fill_en(db_path, raw_dir)
    assert first.already == 7
    second = fill_en(db_path, raw_dir)
    assert second.filled == 0
    assert second.already == 7
    assert second.no_bridge == ["CSM1aC-099"]
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        count = session.query(ExternalId).filter_by(system="mik_en").count()
        assert count == 7  # 重跑不产生重复行
    engine.dispose()

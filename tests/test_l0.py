"""task 013 测试：L0 新卡增量管线。

零网络：fake scraper（duck-type 三个 fetch_* 方法）+ 真实 raw fixtures。
探测口径：新鲜 cardsNum vs 库内 sets.expected_count（不是 cards 行数——附赠能量卡
跨系列归属会让行数口径产生假缺口，task 005 教训）。
"""

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.monitor.l0 import (
    SetIncrement,
    detect_increments,
    refresh_snapshot_overrides,
    run_l0,
)
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, CardNameGroup, LegalitySnapshot, Meta, NameGroup, Set
from ptcgdb.scrapers.raw_store import write_raw

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
CARDS_INIT = ["001", "002", "003", "004", "139", "148"]
CARD_NEW = "151"
SET_ID = "CSM1aC"


def _card_payload(name: str) -> dict:
    doc = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    doc.pop("_meta", None)
    return doc


def _detail_payload(indices: list[str], cards_num: int) -> dict:
    return {
        "code": 200,
        "data": {
            "name": "横空出世 赫",
            "setCode": SET_ID,
            "setId": SET_ID,
            "releaseDate": "2022-10-28T00:00:00+08:00",
            "series": "Sun & Moon",
            "mainExpansion": True,
            "cardsNum": cards_num,
            "cards": [{"setCode": SET_ID, "cardIndex": i} for i in indices],
        },
        "msg": "OK.",
    }


def _products_payload(entries: list[dict]) -> dict:
    return {"code": 200, "data": {"list": entries}, "msg": "OK."}


class FakeScraper:
    """duck-type MikMoeScraper：记录调用，返回预置 payload。"""

    def __init__(self, products: dict, details: dict[str, dict], cards: dict[tuple, dict]):
        self.products = products
        self.details = details
        self.cards = cards
        self.calls: list = []

    def fetch_product_list(self) -> dict:
        self.calls.append(("product-list",))
        return self.products

    def fetch_product_detail(self, set_id: str) -> dict:
        self.calls.append(("product-detail", set_id))
        return self.details[set_id]

    def fetch_card_detail(self, set_code: str, card_index: str) -> dict:
        self.calls.append(("card-detail", set_code, card_index))
        return self.cards[(set_code, card_index)]


def _make_scraper(indices: list[str], cards_num: int) -> FakeScraper:
    return FakeScraper(
        products=_products_payload([
            {"setId": SET_ID, "name": "横空出世 赫", "cardsNum": cards_num}
        ]),
        details={SET_ID: _detail_payload(indices, cards_num)},
        cards={(SET_ID, i): _card_payload(i) for i in indices},
    )


def _setup_raw(tmp_path: Path, indices: list[str], cards_num: int) -> Path:
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / SET_ID
    set_dir.mkdir(parents=True)
    for name in indices:
        shutil.copy(FIXTURE_DIR / f"{name}.json", set_dir / f"{name}.json")
    write_raw(set_dir / "cards.json", _detail_payload(indices, cards_num), source="mik_moe")
    return raw_dir


def _ingest_and_activate(raw_dir: Path, db_path: Path) -> None:
    ingest_set(raw_dir, SET_ID, db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.execute(
            update(Card)
            .where(Card.set_id == SET_ID, Card.status == "draft")
            .values(status="active")
        )
        session.commit()
    engine.dispose()


def _active_count(db_path: Path) -> int:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        n = len(session.scalars(
            select(Card).where(Card.set_id == SET_ID, Card.status == "active")
        ).all())
    engine.dispose()
    return n


# ---- detect_increments ----


def _db_with_sets(tmp_path: Path, expected: dict[str, int]) -> Path:
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for set_id, count in expected.items():
            session.add(Set(
                set_id=set_id, name_zh=set_id, era="日月", release_date=None,
                regulation_mark="", expected_count=count, expected_secret_count=None,
                source="mik_moe", fetched_at="",
            ))
        session.commit()
    engine.dispose()
    return db_path


def test_detect_new_grown_unchanged_shrunk(tmp_path):
    db_path = _db_with_sets(tmp_path, {"A": 10, "B": 3, "C": 5})
    entries = [
        {"setId": "A", "cardsNum": 10},  # 不变
        {"setId": "B", "cardsNum": 5},   # grown
        {"setId": "C", "cardsNum": 3},   # 缩水 → suspicious
        {"setId": "D", "cardsNum": 2},   # new
    ]
    report = detect_increments(db_path, entries)
    by_id = {i.set_id: i for i in report.increments}
    assert set(by_id) == {"B", "D"}
    assert by_id["B"] == SetIncrement(set_id="B", kind="grown", expected=5, current=3)
    assert by_id["D"] == SetIncrement(set_id="D", kind="new", expected=2, current=None)
    assert [s.set_id for s in report.suspicious] == ["C"]
    assert report.suspicious[0].kind == "shrunk"


def test_detect_no_increments(tmp_path):
    db_path = _db_with_sets(tmp_path, {"A": 10})
    report = detect_increments(db_path, [{"setId": "A", "cardsNum": 10}])
    assert report.increments == []
    assert report.suspicious == []


# ---- run_l0 全链路 ----


def test_run_l0_full_chain(tmp_path):
    """初始 6 张 active → 上游 cardsNum 6→7 → 探测增量 → 抓新卡 → 入库 → 校验 → active。"""
    raw_dir = _setup_raw(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)
    assert _active_count(db_path) == 6

    all_cards = CARDS_INIT + [CARD_NEW]
    scraper = _make_scraper(all_cards, 7)
    result = run_l0(db_path, raw_dir, scraper, changelog_path=tmp_path / "CHANGELOG.md")

    assert result.dry_run is False
    assert [i.set_id for i in result.report.increments] == [SET_ID]
    assert result.report.increments[0].kind == "grown"
    assert result.activated == [SET_ID]
    assert result.blocked == {}
    # 只抓了缺失的新卡 151；product-detail 被强制刷新了一次
    card_calls = [c for c in scraper.calls if c[0] == "card-detail"]
    assert card_calls == [("card-detail", SET_ID, CARD_NEW)]
    assert ("product-detail", SET_ID) in scraper.calls
    # 新卡入库并 active，全系列 7 张 active
    assert _active_count(db_path) == 7
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        new_card = session.get(Card, f"{SET_ID}-{CARD_NEW}")
        assert new_card is not None and new_card.status == "active"
        assert session.get(Set, SET_ID).expected_count == 7
        # 后处理：data_version 已递增
        assert session.get(Meta, "data_version") is not None
    engine.dispose()
    # CHANGELOG 有条目
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert SET_ID in changelog


def test_run_l0_dry_run_read_only(tmp_path):
    """dry_run：只刷新 products.json（1 次请求），零额外请求，DB 不变。"""
    raw_dir = _setup_raw(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)

    scraper = _make_scraper(CARDS_INIT + [CARD_NEW], 7)
    result = run_l0(
        db_path, raw_dir, scraper, dry_run=True, changelog_path=tmp_path / "CHANGELOG.md"
    )

    assert result.dry_run is True
    assert [i.set_id for i in result.report.increments] == [SET_ID]
    assert result.activated == []
    assert scraper.calls == [("product-list",)]
    assert _active_count(db_path) == 6
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Set, SET_ID).expected_count == 6
        assert session.get(Meta, "data_version") is None
    engine.dispose()


def test_run_l0_validation_failure_blocks(tmp_path):
    """校验不过 → 系列进 blocked，不 activate，不做后处理。

    模拟上游新卡数据异常：detail 列出 152 但其 cardType 为未知枚举 →
    normalize 跳过入库，raw 对账期望 8 vs 库内 7 → 系列对账失败。
    """
    raw_dir = _setup_raw(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)

    bad = _card_payload(CARD_NEW)
    bad["data"]["cardType"] = "XX"
    indices = CARDS_INIT + [CARD_NEW, "152"]
    scraper = FakeScraper(
        products=_products_payload([{"setId": SET_ID, "name": "x", "cardsNum": 8}]),
        details={SET_ID: _detail_payload(indices, 8)},
        cards={**{(SET_ID, i): _card_payload(i) for i in indices if i != "152"},
               (SET_ID, "152"): bad},
    )
    result = run_l0(db_path, raw_dir, scraper, changelog_path=tmp_path / "CHANGELOG.md")

    assert result.activated == []
    assert SET_ID in result.blocked
    assert _active_count(db_path) == 6
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Meta, "data_version") is None
    engine.dispose()


# ---- refresh_snapshot_overrides 后处理 ----


def _seed_snapshot(db_path: Path, whitelist: list[str]) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(LegalitySnapshot(
            snapshot_id="standard-2026-01-01",
            format="standard",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            allowed_marks=["F"],
            allowed_basic_energy_types=[],
            whitelist_cards=[{"name_full": n, "note": None} for n in whitelist],
            banned_cards=[],
            mark_overrides=[],
            latest_text_overrides={},
            source_url=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()
    engine.dispose()


def test_refresh_snapshot_overrides(tmp_path):
    """同名归组 ≥2 印刷 → 当前快照 overrides 老→新；data_version 递增；CHANGELOG 条目。"""
    raw_dir = _setup_raw(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(NameGroup(group_key="测试组", display_name="测试组", rule_note=None))
        session.flush()
        for idx in ("001", "002"):
            session.add(CardNameGroup(card_id=f"{SET_ID}-{idx}", group_key="测试组"))
        session.commit()
    engine.dispose()
    _seed_snapshot(db_path, ["测试组"])

    version = refresh_snapshot_overrides(db_path, changelog_path=tmp_path / "CHANGELOG.md")

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        snap = session.get(LegalitySnapshot, "standard-2026-01-01")
        # 同系列同发售日 → card_id 降序，002 为最新，001 映射过去
        assert snap.latest_text_overrides == {f"{SET_ID}-001": f"{SET_ID}-002"}
        assert session.get(Meta, "data_version").value == version
    engine.dispose()
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert version in changelog


def test_refresh_snapshot_overrides_frozen_history(tmp_path):
    """历史快照（effective_to 非空）不被刷新。"""
    raw_dir = _setup_raw(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(NameGroup(group_key="测试组", display_name="测试组", rule_note=None))
        session.flush()
        for idx in ("001", "002"):
            session.add(CardNameGroup(card_id=f"{SET_ID}-{idx}", group_key="测试组"))
        session.add(LegalitySnapshot(
            snapshot_id="standard-2025-01-01",
            format="standard",
            effective_from=date(2025, 1, 1),
            effective_to=date(2025, 12, 31),  # 历史快照
            allowed_marks=["E"],
            allowed_basic_energy_types=[],
            whitelist_cards=[{"name_full": "测试组", "note": None}],
            banned_cards=[],
            mark_overrides=[],
            latest_text_overrides={},
            source_url=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()
    engine.dispose()

    refresh_snapshot_overrides(db_path, changelog_path=tmp_path / "CHANGELOG.md")

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        snap = session.get(LegalitySnapshot, "standard-2025-01-01")
        assert snap.latest_text_overrides == {}
    engine.dispose()


# ---- expected_count 延迟更新：校验阻断保留增量信号 ----


def test_l0_validation_blocked_preserves_increment_signal(tmp_path):
    """校验阻断后 expected_count 由 ingest_set 同步到上游最新值（非 L0 显式更新）。

    ingest_set 内部 merge Set 时已取 product detail 的 cardsNum 写入 expected_count；
    L0 的显式 expected_count 更新（activate 后那段）只在通过校验时才执行。
    阻断路径下 data_version 不递增、卡不 activate，但 expected_count 已被 ingest_set
    更新为上游最新值（避免下次 L0 重复探测同一增量）。
    """
    raw_dir = _setup_raw(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)

    # 确认初始 expected_count = 6
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Set, SET_ID).expected_count == 6
    engine.dispose()

    # 模拟上游 cardsNum 增长到 8 + 新卡数据异常 → 校验阻断
    bad = _card_payload(CARD_NEW)
    bad["data"]["cardType"] = "XX"
    indices = CARDS_INIT + [CARD_NEW, "152"]
    scraper = FakeScraper(
        products=_products_payload([{"setId": SET_ID, "name": "x", "cardsNum": 8}]),
        details={SET_ID: _detail_payload(indices, 8)},
        cards={
            **{(SET_ID, i): _card_payload(i) for i in indices if i != "152"},
            (SET_ID, "152"): bad,
        },
    )
    result = run_l0(db_path, raw_dir, scraper)

    assert SET_ID in result.blocked  # 校验阻断
    # ingest_set 已将 expected_count 同步为上游 cardsNum=8（merge Set）
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Set, SET_ID).expected_count == 8
    engine.dispose()

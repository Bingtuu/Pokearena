"""L0 新卡增量管线（task 013，PRD FR-5.1）。

每日总量探测：product-list 各系列 cardsNum vs 库内 sets.expected_count
（不是 cards 行数——附赠能量卡跨系列归属会让行数口径产生假缺口，task 005 教训）。
有增量 → 强制刷新该系列 cards.json → 断点续抓新卡 → ingest(draft)
→ FR-2.3 校验全过 → active；不过 → blocked，不做后处理。
合入后处理：刷新当前快照 latest_text_overrides + data_version 递增 + CHANGELOG。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from ptcgdb.legal.seed import WhitelistEntry
from ptcgdb.legal.versions import (
    _append_changelog_block,
    _bump_data_version,
    _latest_text_overrides,
)
from ptcgdb.normalize.ingest import ingest_set
from ptcgdb.orm import Card, LegalitySnapshot, Set
from ptcgdb.scrapers import mikmoe
from ptcgdb.scrapers.raw_store import write_raw
from ptcgdb.scrapers.runner import ScrapeRunner, _product_entries
from ptcgdb.validate import run_validations


@dataclass(frozen=True)
class SetIncrement:
    """一个系列的总量变化。"""

    set_id: str
    kind: str  # "new"（库内无记录）/ "grown"（cardsNum 增长）/ "shrunk"（缩水，可疑）
    expected: int  # 上游新鲜 cardsNum
    current: int | None  # 库内 sets.expected_count（无记录为 None）


@dataclass(frozen=True)
class DetectReport:
    increments: list[SetIncrement]  # new + grown，待处理
    suspicious: list[SetIncrement]  # shrunk，只报告不处理


@dataclass
class L0Result:
    report: DetectReport
    activated: list[str] = field(default_factory=list)
    blocked: dict[str, list[str]] = field(default_factory=dict)  # set_id -> 失败规则名
    data_version: str | None = None
    dry_run: bool = False


def detect_increments(
    db_path: Path, products_entries: list[dict[str, Any]]
) -> DetectReport:
    """比对新鲜 cardsNum vs 库内 sets.expected_count。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        current = dict(
            session.execute(select(Set.set_id, Set.expected_count)).all()
        )
    engine.dispose()

    increments: list[SetIncrement] = []
    suspicious: list[SetIncrement] = []
    for entry in products_entries:
        set_id = entry.get("setId")
        cards_num = entry.get("cardsNum")
        if not set_id or not isinstance(cards_num, int):
            continue
        known = current.get(set_id)
        if known is None:
            increments.append(
                SetIncrement(set_id=set_id, kind="new", expected=cards_num, current=None)
            )
        elif cards_num > known:
            increments.append(
                SetIncrement(set_id=set_id, kind="grown", expected=cards_num, current=known)
            )
        elif cards_num < known:
            suspicious.append(
                SetIncrement(set_id=set_id, kind="shrunk", expected=cards_num, current=known)
            )
    return DetectReport(increments=increments, suspicious=suspicious)


def refresh_snapshot_overrides(
    db_path: Path,
    *,
    changelog_path: Path = Path("CHANGELOG.md"),
    activated: list[str] | None = None,
) -> str:
    """合入后处理（FR-5.1）：重算全部当前快照的 latest_text_overrides（整体替换），
    data_version 递增 + CHANGELOG 条目。历史快照（effective_to 非空）不碰。
    activated 为本次合入的系列（写入 CHANGELOG）。返回新数据版本号。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        snapshots = session.scalars(
            select(LegalitySnapshot).where(LegalitySnapshot.effective_to.is_(None))
        ).all()
        refreshed: list[str] = []
        for snap in snapshots:
            whitelist = [
                WhitelistEntry(name_full=w["name_full"], note=w.get("note"))
                for w in (snap.whitelist_cards or [])
            ]
            snap.latest_text_overrides = _latest_text_overrides(session, whitelist)
            refreshed.append(snap.snapshot_id)
        version = _bump_data_version(session)
        session.commit()
    engine.dispose()

    items = []
    if activated:
        items.append(f"L0 增量合入：系列 {', '.join(activated)}")
    items.append(
        f"刷新当前快照 latest_text_overrides"
        f"（{', '.join(refreshed) if refreshed else '无当前快照'}）"
    )
    _append_changelog_block(changelog_path, version, "Changed", items)
    return version


def run_l0(
    db_path: Path,
    raw_dir: Path,
    scraper: Any,
    *,
    dry_run: bool = False,
    changelog_path: Path = Path("CHANGELOG.md"),
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> L0Result:
    """L0 主流程。dry_run 只刷新 products.json 并探测（只读，零额外请求）。

    on_event(event, payload) 事件钩子（task 015 通知用）：
    "increment" 每个增量系列一次；"activated" / "blocked" 每个系列一次；
    "postprocess" 后处理完成一次。
    """

    def emit(event: str, payload: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event, payload)

    runner = ScrapeRunner(raw_dir, scraper, db_path)

    # 1. 刷新产品清单（每轮唯一的固定请求）
    products_payload = scraper.fetch_product_list()
    write_raw(runner.products_path(), products_payload, source=mikmoe.SOURCE, force=True)
    entries = _product_entries(products_payload)

    # 2. 探测
    report = detect_increments(db_path, entries)
    result = L0Result(report=report, dry_run=dry_run)
    for inc in report.increments:
        emit("increment", {"set_id": inc.set_id, "kind": inc.kind,
                           "expected": inc.expected, "current": inc.current})
    if dry_run or not report.increments:
        return result

    # 3. 逐系列：刷新 cards.json → 续抓新卡 → ingest → 校验 → activate
    for inc in report.increments:
        sid = inc.set_id
        detail_payload = scraper.fetch_product_detail(sid)
        write_raw(runner.set_cards_path(sid), detail_payload, source=mikmoe.SOURCE, force=True)
        runner.scrape_cards(set_ids=[sid], force=False)
        ingest_set(raw_dir, sid, db_path)
        validations = run_validations(db_path, set_id=sid, raw_dir=raw_dir)
        failed = [r.rule for r in validations if not r.passed]
        if failed:
            result.blocked[sid] = failed
            emit("blocked", {"set_id": sid, "rules": failed})
            continue
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            session.execute(
                update(Card).where(Card.set_id == sid, Card.status == "draft")
                .values(status="active")
            )
            session.commit()
        engine.dispose()
        result.activated.append(sid)
        emit("activated", {"set_id": sid})

    # 4. 合入后处理（有合入才做）
    if result.activated:
        result.data_version = refresh_snapshot_overrides(
            db_path, changelog_path=changelog_path, activated=result.activated
        )
        emit("postprocess", {"data_version": result.data_version,
                             "activated": list(result.activated)})
    return result

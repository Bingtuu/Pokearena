"""采集运行器：组织三级链路抓取、断点续传、三清单日志、scrape_runs 落库。

三清单（FR-1.4）每次运行写入 `data/raw/runs/{run_id}/`：
- scraped.json：本轮处理成功的条目（action=fetched 实抓 / skipped 断点跳过）
- question.json：可疑条目（code!=200、data 为空、重试耗尽、字段缺失）
- missing.json：对账后"应有未抓到"的条目（raw 文件缺失或 hash 无效）
同时在 scrape_runs 表写一条运行记录（含 manifest_hash = 三清单的 sha256）。

熔断（CircuitOpenError）时立即中止本轮：已抓产物保留，清单与 run 记录照常落盘，
status 记为 "aborted"，由 CLI 输出告警并以非零码退出。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import ScrapeRun
from ptcgdb.scrapers import mikmoe
from ptcgdb.scrapers.http import CircuitOpenError
from ptcgdb.scrapers.mikmoe import MikMoeApiError, MikMoeScraper
from ptcgdb.scrapers.raw_store import canonical_json, is_valid_raw, read_raw, write_raw

STATUS_OK = "ok"
STATUS_ABORTED = "aborted"


@dataclass
class RunStats:
    """一次运行的三清单与计数。"""

    scraped: list[dict[str, Any]] = field(default_factory=list)
    question: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0  # 本轮应处理的总数（对账分母）
    aborted: bool = False


@dataclass
class RunResult:
    run_id: str
    stats: RunStats
    lists_path: Path


class ScrapeRunner:
    def __init__(
        self,
        raw_dir: Path,
        scraper: MikMoeScraper,
        db_path: Path | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.source_dir = self.raw_dir / mikmoe.RAW_SUBDIR
        self.scraper = scraper
        self.db_path = Path(db_path) if db_path else None

    # ---- 路径约定 ----
    def products_path(self) -> Path:
        return self.source_dir / "products.json"

    def set_cards_path(self, set_id: str) -> Path:
        return self.source_dir / set_id / "cards.json"

    def card_path(self, set_id: str, card_index: str) -> Path:
        return self.source_dir / set_id / f"{card_index}.json"

    # ---- 产品层 ----
    def ensure_products(self, *, force: bool = False) -> dict[str, Any]:
        """保证 products.json 在本地可用；缺失/无效时实抓。返回完整 raw 文档。"""
        if not force:
            doc = read_raw(self.products_path())
            if doc is not None:
                return doc
        payload = self.scraper.fetch_product_list()
        write_raw(self.products_path(), payload, source=mikmoe.SOURCE, force=force)
        return read_raw(self.products_path()) or {}

    def scrape_sets(self, *, force: bool = False) -> RunResult:
        """抓系列清单 + 各系列详情（product-detail）。"""
        run_id, started_at = _new_run_id()
        stats = RunStats()
        try:
            products_payload = self.scraper.fetch_product_list()
            write_raw(self.products_path(), products_payload, source=mikmoe.SOURCE, force=force)
            products = _product_entries(products_payload)
            stats.scraped.append(
                {"id": "product-list", "path": str(self.products_path()), "action": "fetched"}
            )
            stats.total = len(products)
            for product in products:
                set_id = product.get("setId")
                if not set_id:
                    stats.question.append(
                        {"id": None, "endpoint": mikmoe.ENDPOINT_PRODUCT_LIST,
                         "reason": "系列条目缺 setId 字段"}
                    )
                    continue
                path = self.set_cards_path(set_id)
                if not force and is_valid_raw(path):
                    stats.scraped.append({"id": set_id, "path": str(path), "action": "skipped"})
                    continue
                try:
                    payload = self.scraper.fetch_product_detail(set_id)
                except MikMoeApiError as exc:
                    stats.question.append(
                        {"id": set_id, "endpoint": exc.endpoint, "reason": str(exc)}
                    )
                    continue
                write_raw(path, payload, source=mikmoe.SOURCE, force=force)
                stats.scraped.append({"id": set_id, "path": str(path), "action": "fetched"})
        except CircuitOpenError:
            stats.aborted = True

        # 对账：product-list 里有、但 cards.json 缺失/无效的系列进 missing
        doc = read_raw(self.products_path())
        for product in _product_entries(doc or {}):
            set_id = product.get("setId")
            if set_id and not is_valid_raw(self.set_cards_path(set_id)):
                stats.missing.append({"id": set_id, "reason": "系列详情未抓到或 hash 无效"})

        return self._finish_run(run_id, started_at, stats)

    # ---- 单卡层 ----
    def scrape_cards(
        self, *, set_ids: list[str] | None = None, force: bool = False
    ) -> RunResult:
        """抓单卡（card 级断点续传：raw 文件存在且 hash 有效即跳过）。

        set_ids 为 None 时，取 products.json 中全部系列。
        """
        run_id, started_at = _new_run_id()
        stats = RunStats()
        try:
            products_doc = self.ensure_products()
            all_set_ids = [p.get("setId") for p in _product_entries(products_doc)]
            cards_num_map = {
                p.get("setId"): p.get("cardsNum")
                for p in _product_entries(products_doc)
            }
            targets = set_ids if set_ids else [s for s in all_set_ids if s]
            for set_id in targets:
                self._scrape_set_cards(
                    set_id, stats, force=force, cards_num_map=cards_num_map,
                )
        except CircuitOpenError:
            stats.aborted = True

        return self._finish_run(run_id, started_at, stats)

    def _scrape_set_cards(
        self, set_id: str, stats: RunStats, *, force: bool,
        cards_num_map: dict[str, int] | None = None,
    ) -> None:
        # 系列详情缺失时先补抓
        if force or not is_valid_raw(self.set_cards_path(set_id)):
            payload = self.scraper.fetch_product_detail(set_id)
            write_raw(self.set_cards_path(set_id), payload, source=mikmoe.SOURCE, force=force)
        doc = read_raw(self.set_cards_path(set_id))
        if doc is None:
            stats.question.append(
                {"id": set_id, "endpoint": mikmoe.ENDPOINT_PRODUCT_DETAIL,
                 "reason": "系列详情不可用，跳过该系列"}
            )
            return
        # cardsNum 对账：缓存条目数与 product-list 中的 cardsNum 不一致时自动重拉
        if not force and cards_num_map and set_id in cards_num_map:
            expected = cards_num_map[set_id]
            if expected is not None and isinstance(expected, int):
                data_check = doc.get("data") or {}
                cached_count = len(data_check.get("cards") or [])
                if expected != cached_count:
                    import logging
                    logging.warning(
                        f"{set_id}: cardsNum={expected} ≠ cached={cached_count}，重新拉取"
                    )
                    payload = self.scraper.fetch_product_detail(set_id)
                    write_raw(self.set_cards_path(set_id), payload,
                              source=mikmoe.SOURCE, force=True)
                    doc = read_raw(self.set_cards_path(set_id))
        data = doc.get("data") or {}
        cards = data.get("cards") or []
        stats.total += len(cards)
        for entry in cards:
            set_code = entry.get("setCode") or set_id
            card_index = entry.get("cardIndex")
            card_id = f"{set_id}-{card_index}"
            if not isinstance(card_index, str) or not card_index:
                stats.question.append(
                    {"id": card_id, "endpoint": mikmoe.ENDPOINT_CARD_DETAIL,
                     "reason": "系列详情中 cardIndex 缺失或非字符串"}
                )
                continue
            path = self.card_path(set_id, card_index)
            if not force and is_valid_raw(path):
                stats.scraped.append({"id": card_id, "path": str(path), "action": "skipped"})
                continue
            try:
                payload = self.scraper.fetch_card_detail(set_code, card_index)
            except MikMoeApiError as exc:
                stats.question.append(
                    {"id": card_id, "endpoint": exc.endpoint, "reason": str(exc)}
                )
                continue
            write_raw(path, payload, source=mikmoe.SOURCE, force=force)
            stats.scraped.append({"id": card_id, "path": str(path), "action": "fetched"})
        # 对账：该系列应有而未抓到的卡进 missing
        for entry in cards:
            card_index = entry.get("cardIndex")
            if isinstance(card_index, str) and card_index:
                if not is_valid_raw(self.card_path(set_id, card_index)):
                    stats.missing.append(
                        {"id": f"{set_id}-{card_index}", "reason": "单卡未抓到或 hash 无效"}
                    )

    # ---- 收尾：三清单 + scrape_runs ----
    def _finish_run(self, run_id: str, started_at: datetime, stats: RunStats) -> RunResult:
        return finish_run(self.raw_dir, self.db_path, run_id, started_at, stats)


def finish_run(
    raw_dir: Path,
    db_path: Path | None,
    run_id: str,
    started_at: datetime,
    stats: RunStats,
    *,
    source: str | None = None,
) -> RunResult:
    """三清单落盘 + scrape_runs 运行记录（卡牌/赛事 runner 共用）。

    source = scrape_runs.source 列（采集源标识）；None 时保持历史默认 mikmoe.SOURCE
    （向后兼容：mik 卡牌/赛事 runner 调用点不传）。
    """
    finished_at = datetime.now(UTC)
    lists_dir = raw_dir / "runs" / run_id
    lists_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("scraped", stats.scraped),
        ("question", stats.question),
        ("missing", stats.missing),
    ):
        (lists_dir / f"{name}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    manifest_hash = hashlib.sha256(
        canonical_json(
            {"scraped": stats.scraped, "question": stats.question, "missing": stats.missing}
        ).encode("utf-8")
    ).hexdigest()
    status = STATUS_ABORTED if stats.aborted else STATUS_OK
    if db_path is not None:
        apply_migrations(db_path)
        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            session.add(
                ScrapeRun(
                    run_id=run_id,
                    source=source or mikmoe.SOURCE,
                    started_at=started_at,
                    finished_at=finished_at,
                    card_count=stats.total,
                    ok_count=len(stats.scraped),
                    question_count=len(stats.question),
                    missing_count=len(stats.missing),
                    lists_path=str(lists_dir),
                    status=status,
                    manifest_hash=manifest_hash,
                )
            )
            session.commit()
        engine.dispose()
    return RunResult(run_id=run_id, stats=stats, lists_path=lists_dir)


def _product_entries(products_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """提取系列条目。product-list 实测 data 形态为 {"list": [...]}（兼容裸数组）。"""
    data = products_doc.get("data")
    if isinstance(data, dict):
        entries = data.get("list") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    return [e for e in entries if isinstance(e, dict)]


def _new_run_id() -> tuple[str, datetime]:
    started_at = datetime.now(UTC)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    return run_id, started_at

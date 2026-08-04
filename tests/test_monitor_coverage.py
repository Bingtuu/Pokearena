"""monitor 模块单元测试：detect_increments / _event_message / desktop_command /
Notifier / mark_proposal_applied / L0 dry_run。

全 mock：DB 用 tmp_path + sqlalchemy fixtures，网络/平台/subprocess 全部注入。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.monitor.l0 import detect_increments, run_l0
from ptcgdb.monitor.notify import (
    NOTIFY_EVENTS,
    Notifier,
    _event_message,
    _osascript_escape,
    _pwsh_escape,
    desktop_command,
    make_event_handler,
)
from ptcgdb.monitor.proposals import mark_proposal_applied
from ptcgdb.orm import Card, Meta, Set
from ptcgdb.scrapers.raw_store import write_raw

# ============================================================================
# detect_increments
# ============================================================================


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


def test_detect_new_series(tmp_path):
    """库内无记录 → kind='new'。"""
    db_path = _db_with_sets(tmp_path, {"A": 10})
    entries = [{"setId": "B", "cardsNum": 5}]
    report = detect_increments(db_path, entries)
    assert len(report.increments) == 1
    inc = report.increments[0]
    assert inc.set_id == "B"
    assert inc.kind == "new"
    assert inc.expected == 5
    assert inc.current is None
    assert report.suspicious == []


def test_detect_grown_series(tmp_path):
    """上游 cardsNum > 库内 expected_count → kind='grown'。"""
    db_path = _db_with_sets(tmp_path, {"A": 10})
    entries = [{"setId": "A", "cardsNum": 15}]
    report = detect_increments(db_path, entries)
    assert len(report.increments) == 1
    inc = report.increments[0]
    assert inc.set_id == "A"
    assert inc.kind == "grown"
    assert inc.expected == 15
    assert inc.current == 10


def test_detect_shrunk_suspicious(tmp_path):
    """上游 cardsNum < 库内 expected_count → suspicious，不进入 increments。"""
    db_path = _db_with_sets(tmp_path, {"A": 10})
    entries = [{"setId": "A", "cardsNum": 5}]
    report = detect_increments(db_path, entries)
    assert report.increments == []
    assert len(report.suspicious) == 1
    assert report.suspicious[0].kind == "shrunk"
    assert report.suspicious[0].expected == 5
    assert report.suspicious[0].current == 10


def test_detect_no_change(tmp_path):
    """cardsNum 与库内一致 → 既非增量也非可疑。"""
    db_path = _db_with_sets(tmp_path, {"A": 10, "B": 20})
    entries = [
        {"setId": "A", "cardsNum": 10},
        {"setId": "B", "cardsNum": 20},
    ]
    report = detect_increments(db_path, entries)
    assert report.increments == []
    assert report.suspicious == []


# ============================================================================
# _event_message
# ============================================================================


def test_event_message_increment():
    msg = _event_message("increment", {"set_id": "CSM1aC", "kind": "grown",
                                        "current": 6, "expected": 7})
    assert "CSM1aC" in msg
    assert "grown" in msg
    assert "6 → 7" in msg


def test_event_message_activated():
    msg = _event_message("activated", {"set_id": "CSM1aC"})
    assert "CSM1aC" in msg
    assert "active" in msg


def test_event_message_blocked():
    msg = _event_message("blocked", {"set_id": "CSM1aC",
                                      "rules": ["系列对账", "合法性"]})
    assert "CSM1aC" in msg
    assert "系列对账" in msg
    assert "合法性" in msg


def test_event_message_postprocess():
    msg = _event_message("postprocess", {"data_version": "v2.0.0",
                                          "activated": ["CSM1aC", "CSM1bC"]})
    assert "v2.0.0" in msg
    assert "CSM1aC" in msg
    assert "CSM1bC" in msg


def test_event_message_proposal():
    msg = _event_message("proposal", {"status": "needs_manual",
                                       "path": "proposals/20260801_standard.yaml"})
    assert "needs_manual" in msg
    assert "20260801_standard.yaml" in msg


def test_event_message_news():
    msg = _event_message("news", {"title": "关于标准赛制调整的通知",
                                   "href": "https://example.com/123"})
    assert "关于标准赛制调整的通知" in msg
    assert "https://example.com/123" in msg


def test_event_message_unknown_fallback():
    msg = _event_message("unknown_event", {"foo": "bar"})
    assert "foo" in msg or "bar" in msg  # str(payload)


# ============================================================================
# desktop_command 平台 + 转义
# ============================================================================


def test_desktop_command_windows(monkeypatch):
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    cmd = desktop_command("L0 增量", "新卡入库")
    assert cmd[0].startswith("powershell")
    joined = " ".join(cmd)
    assert "L0 增量" in joined
    assert "新卡入库" in joined
    assert "ToastNotification" in joined


def test_desktop_command_macos(monkeypatch):
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Darwin")
    cmd = desktop_command("标题", "消息")
    assert cmd[0] == "osascript"
    assert "-e" in cmd
    joined = " ".join(cmd)
    assert "标题" in joined
    assert "消息" in joined


def test_desktop_command_linux(monkeypatch):
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Linux")
    cmd = desktop_command("标题", "消息")
    assert cmd == ["notify-send", "标题", "消息"]


def test_desktop_windows_escape_single_quote(monkeypatch):
    """PowerShell 单引号转义：' → ''。"""
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    cmd = desktop_command("It's a test", "Don't panic")
    joined = " ".join(cmd)
    # 单引号被转义为两个单引号
    assert "It''s a test" in joined
    assert "Don''t panic" in joined


def test_desktop_macos_escape_double_quote(monkeypatch):
    """macOS osascript 双引号转义：\" → \\\"。"""
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Darwin")
    cmd = desktop_command('标题"引号', '消息"内容')
    joined = " ".join(cmd)
    # osascript 内双引号被转义
    assert '\\"' in joined


def test_desktop_windows_braces_preserved(monkeypatch):
    """大括号 {} 在 PowerShell toast 中不被 .format() 消费（用 .replace 不是 .format）。"""
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    cmd = desktop_command("测试 {ex} 标题", '{"json": "value"}')
    joined = " ".join(cmd)
    assert "{ex}" in joined
    assert '{"json": "value"}' in joined


# ============================================================================
# _pwsh_escape / _osascript_escape 单元
# ============================================================================


def test_pwsh_escape():
    assert _pwsh_escape("hello") == "hello"
    assert _pwsh_escape("it's") == "it''s"
    assert _pwsh_escape("a'b'c") == "a''b''c"


def test_osascript_escape():
    assert _osascript_escape("plain") == "plain"
    assert _osascript_escape('hello "world"') == 'hello \\"world\\"'
    assert _osascript_escape("path\\to\\file") == "path\\\\to\\\\file"


# ============================================================================
# Notifier.notify
# ============================================================================


def test_notifier_desktop_success(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    n = Notifier(desktop=True, runner=lambda cmd, **kw: calls.append(list(cmd)))
    sent = n.notify("L0", "增量检测")
    assert sent == ["desktop"]
    assert len(calls) == 1
    assert "L0" in " ".join(calls[0])


def test_notifier_desktop_failure_silent(monkeypatch):
    def boom(*a: Any, **k: Any) -> None:
        raise OSError("no powershell")

    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    n = Notifier(desktop=True, runner=boom)
    assert n.notify("t", "m") == []  # 静默，不抛异常


def test_notifier_desktop_disabled():
    n = Notifier(desktop=False)
    assert n.notify("t", "m") == []


def test_notifier_webhook_success():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        n = Notifier(desktop=False, webhook_url="https://hook.example.com/x", poster=client)
        sent = n.notify("标题", "内容", event="proposal", payload={"path": "p.yaml"})
    assert sent == ["webhook"]
    assert seen[0]["title"] == "标题"
    assert seen[0]["message"] == "内容"
    assert seen[0]["event"] == "proposal"
    assert seen[0]["payload"] == {"path": "p.yaml"}


def test_notifier_webhook_failure_silent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        n = Notifier(desktop=False, webhook_url="https://hook.example.com/x", poster=client)
        assert n.notify("t", "m") == []


def test_notifier_webhook_network_error_silent():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        n = Notifier(desktop=False, webhook_url="https://hook.example.com/x", poster=client)
        assert n.notify("t", "m") == []


# ============================================================================
# make_event_handler
# ============================================================================


def _recording_notifier() -> tuple[Notifier, list[tuple[str, str, str | None, dict | None]]]:
    records: list[tuple[str, str, str | None, dict | None]] = []

    class Rec(Notifier):
        def notify(self, title, message, *, event=None, payload=None):  # type: ignore[override]
            records.append((title, message, event, payload))
            return ["desktop"]

    return Rec(desktop=False), records


def test_make_event_handler_filters_non_notify_events():
    notifier, records = _recording_notifier()
    handler = make_event_handler(notifier)
    # 非通知事件应被过滤
    handler("unchanged", {"page_id": "regulation"})
    handler("baseline", {"page_id": "news"})
    handler("noop", {"page_id": "regulation"})
    assert records == []


def test_make_event_handler_passes_important_events():
    notifier, records = _recording_notifier()
    handler = make_event_handler(notifier)
    for event in sorted(NOTIFY_EVENTS):
        handler(event, {"set_id": "TEST", "kind": "new", "expected": 1, "current": 0,
                        "rules": [], "data_version": "v1", "activated": ["TEST"],
                        "status": "pending_review", "path": "p.yaml",
                        "title": "公告", "href": "u"})
    assert len(records) == len(NOTIFY_EVENTS)
    # 验证 event 被透传
    for (_title, _msg, event, _payload) in records:
        assert event in NOTIFY_EVENTS


# ============================================================================
# mark_proposal_applied
# ============================================================================


def _write_proposal_yaml(proposal_path: Path, status: str = "pending_review",
                         snapshot_id: str = "standard-2026-01-01",
                         extra: dict[str, Any] | None = None) -> None:
    doc: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "format": "standard",
        "status": status,
        "detected_at": "2026-08-01T00:00:00+00:00",
        "parse_errors": [],
    }
    if extra:
        doc.update(extra)
    proposal_path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_mark_proposal_applied_normal(tmp_path):
    path = tmp_path / "20260801_standard.yaml"
    _write_proposal_yaml(path, status="pending_review", snapshot_id="standard-2026-01-01")
    mark_proposal_applied(path, "standard-2026-01-01")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["status"] == "applied"
    assert doc["applied_snapshot_id"] == "standard-2026-01-01"
    assert "applied_at" in doc


def test_mark_proposal_applied_idempotent(tmp_path):
    """重复 mark 不报错，字段正常覆盖。"""
    path = tmp_path / "20260801_standard.yaml"
    _write_proposal_yaml(path, status="pending_review")
    mark_proposal_applied(path, "standard-2026-01-01")
    first_at = yaml.safe_load(path.read_text(encoding="utf-8"))["applied_at"]
    mark_proposal_applied(path, "standard-2026-01-01")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["status"] == "applied"
    assert doc["applied_snapshot_id"] == "standard-2026-01-01"
    # 第二次 applied_at 被覆盖为新的时间戳
    assert doc["applied_at"] != first_at


def test_mark_proposal_applied_needs_manual(tmp_path):
    """needs_manual 状态提案也可 mark applied（函数不做状态守卫）。"""
    path = tmp_path / "20260801_needs_manual.yaml"
    _write_proposal_yaml(path, status="needs_manual", snapshot_id="standard-2026-08-01")
    mark_proposal_applied(path, "standard-2026-08-01")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["status"] == "applied"
    assert doc["applied_snapshot_id"] == "standard-2026-08-01"
    assert "applied_at" in doc


def test_mark_proposal_applied_preserves_existing_fields(tmp_path):
    """已存在的无关字段在 mark 后保留。"""
    path = tmp_path / "20260801_standard.yaml"
    _write_proposal_yaml(path, status="pending_review",
                         extra={"custom_field": "keep_me", "diff": {"allowed_marks": {}}})
    mark_proposal_applied(path, "standard-2026-01-01")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["custom_field"] == "keep_me"
    assert doc["diff"] == {"allowed_marks": {}}
    assert doc["status"] == "applied"


# ============================================================================
# L0 dry_run
# ============================================================================

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw" / "mikmoe" / "CSM1aC"
SET_ID = "CSM1aC"
CARDS_INIT = ["001", "002", "003", "004", "139", "148"]


def _card_payload(name: str) -> dict:
    doc = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    doc.pop("_meta", None)
    return doc


def _products_payload(entries: list[dict]) -> dict:
    return {"code": 200, "data": {"list": entries}, "msg": "OK."}


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


class FakeScraper:
    """duck-type MikMoeScraper：记录调用，返回预置 payload。"""

    def __init__(self, products: dict, details: dict[str, dict],
                 cards: dict[tuple, dict]):
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


def _setup_raw_for_l0(tmp_path: Path, indices: list[str], cards_num: int) -> Path:
    import shutil
    raw_dir = tmp_path / "raw"
    set_dir = raw_dir / "mikmoe" / SET_ID
    set_dir.mkdir(parents=True)
    for name in indices:
        shutil.copy(FIXTURE_DIR / f"{name}.json", set_dir / f"{name}.json")
    write_raw(set_dir / "cards.json", _detail_payload(indices, cards_num), source="mik_moe")
    return raw_dir


def _ingest_and_activate(raw_dir: Path, db_path: Path) -> None:
    from ptcgdb.normalize.ingest import ingest_set
    ingest_set(raw_dir, SET_ID, db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        from sqlalchemy import update
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


def test_l0_dry_run_no_db_writes(tmp_path):
    """dry_run：只刷新 products.json，零额外请求，DB 不变。"""
    raw_dir = _setup_raw_for_l0(tmp_path, CARDS_INIT, 6)
    db_path = tmp_path / "test.db"
    _ingest_and_activate(raw_dir, db_path)
    assert _active_count(db_path) == 6

    # 确认初始 expected_count
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Set, SET_ID).expected_count == 6
        assert session.get(Meta, "data_version") is None
    engine.dispose()

    # 上游 cardsNum 增长到 7
    CARD_NEW = "151"
    all_cards = CARDS_INIT + [CARD_NEW]
    scraper = FakeScraper(
        products=_products_payload([{"setId": SET_ID, "name": "x", "cardsNum": 7}]),
        details={SET_ID: _detail_payload(all_cards, 7)},
        cards={(SET_ID, i): _card_payload(i) for i in all_cards},
    )

    result = run_l0(db_path, raw_dir, scraper, dry_run=True,
                    changelog_path=tmp_path / "CHANGELOG.md")

    # dry_run 标记
    assert result.dry_run is True
    # 增量探测正确
    assert len(result.report.increments) == 1
    inc = result.report.increments[0]
    assert inc.set_id == SET_ID
    assert inc.kind == "grown"
    assert inc.expected == 7
    assert inc.current == 6
    # 无 activate
    assert result.activated == []
    # 只请求了 product-list，无 product-detail / card-detail
    assert scraper.calls == [("product-list",)]
    # DB 不变
    assert _active_count(db_path) == 6
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        assert session.get(Set, SET_ID).expected_count == 6
        assert session.get(Meta, "data_version") is None
    engine.dispose()

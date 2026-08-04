"""task 015 测试：通知（FR-5.5）。

全 mock：desktop 注入 runner、webhook 用 httpx MockTransport、平台用 monkeypatch。
"""

import json
from typing import Any

import httpx

from ptcgdb.monitor.notify import (
    Notifier,
    _osascript_escape,
    desktop_command,
    make_event_handler,
)


def _ok_runner(*args: Any, **kwargs: Any) -> None:
    return None


# ---- 桌面通知 ----


def test_desktop_windows_toast_command(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    n = Notifier(desktop=True, runner=lambda *a, **k: calls.append(list(a[0])))
    sent = n.notify("标题", "内容")
    assert sent == ["desktop"]
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0].startswith("powershell")
    joined = " ".join(cmd)
    assert "标题" in joined and "内容" in joined
    assert "ToastNotification" in joined


def test_desktop_macos_linux(monkeypatch):
    calls: list[list[str]] = []
    runner = lambda *a, **k: calls.append(list(a[0]))  # noqa: E731
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Darwin")
    assert Notifier(desktop=True, runner=runner).notify("t", "m") == ["desktop"]
    assert calls[0][0] == "osascript"
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Linux")
    assert Notifier(desktop=True, runner=runner).notify("t", "m") == ["desktop"]
    assert calls[1][0] == "notify-send"


def test_desktop_failure_swallowed(monkeypatch):
    def boom(*a: Any, **k: Any) -> None:
        raise OSError("no powershell")

    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    n = Notifier(desktop=True, runner=boom)
    assert n.notify("t", "m") == []  # 失败静默，不中断管线


def test_desktop_disabled_skips():
    n = Notifier(desktop=False, runner=_ok_runner)
    assert n.notify("t", "m") == []


# ---- webhook ----


def test_webhook_posts_json():
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


def test_webhook_failure_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        n = Notifier(desktop=False, webhook_url="https://hook.example.com/x", poster=client)
        assert n.notify("t", "m") == []


# ---- 事件映射与过滤 ----


def _recording_notifier() -> tuple[Notifier, list[tuple[str, str]]]:
    sent: list[tuple[str, str]] = []

    class Rec(Notifier):
        def notify(self, title, message, *, event=None, payload=None):  # type: ignore[override]
            sent.append((title, message))
            return ["desktop"]

    return Rec(desktop=False, runner=_ok_runner), sent


def test_event_handler_notifies_important_only():
    notifier, sent = _recording_notifier()
    handler = make_event_handler(notifier)
    handler("unchanged", {"page_id": "regulation"})
    handler("baseline", {"page_id": "news"})
    assert sent == []  # unchanged/baseline 不打扰
    handler("blocked", {"set_id": "CSM1aC", "rules": ["系列对账"]})
    handler("proposal", {"page_id": "regulation", "format": "standard",
                         "status": "needs_manual", "path": "p.yaml"})
    handler("activated", {"set_id": "CSM1aC"})
    handler("news", {"title": "关于标准赛制调整的通知", "href": "u"})
    assert len(sent) == 4
    assert any("CSM1aC" in m and "系列对账" in m for _t, m in sent)
    assert any("needs_manual" in m for _t, m in sent)
    assert any("赛制调整" in m for _t, m in sent)


# ---- osascript 转义 ----


def test_osascript_escape_double_quote():
    assert _osascript_escape('hello "world"') == 'hello \\"world\\"'


def test_osascript_escape_backslash():
    assert _osascript_escape("path\\to\\file") == "path\\\\to\\\\file"


# ---- PowerShell toast 大括号 ----


def test_pwsh_toast_braces_in_title(monkeypatch):
    """标题含 {ex} 时 str.replace 不抛 KeyError（非 .format）。"""
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    cmd = desktop_command("测试 {ex} 标题", "hello")
    joined = " ".join(cmd)
    assert "{ex}" in joined  # 原样保留


def test_pwsh_toast_braces_in_message(monkeypatch):
    """消息含 JSON（含 {}）不触发格式化错误。"""
    monkeypatch.setattr("ptcgdb.monitor.notify.platform.system", lambda: "Windows")
    cmd = desktop_command("标题", '{"key": "value"}')
    joined = " ".join(cmd)
    assert '{"key": "value"}' in joined  # 原样保留

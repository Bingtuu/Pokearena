"""变更通知（task 015，PRD FR-5.5）。

本地桌面通知（必选，零新依赖）：Windows PowerShell toast / macOS osascript /
Linux notify-send；webhook（可选）：POST JSON。runner/poster 注入便于测试。
通知失败一律静默（返回空渠道列表），绝不中断数据管线。
"""

from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Callable
from typing import Any

import httpx

# 只对重要事件触发通知；unchanged/baseline/noop 不打扰
NOTIFY_EVENTS = {"increment", "activated", "blocked", "postprocess", "proposal", "news"}

_PWSH_TOAST = r"""
$mgr = 'Windows.UI.Notifications.ToastNotificationManager'
[$mgr, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).AppendChild($xml.CreateTextNode('{title}')) > $null
$nodes.Item(1).AppendChild($xml.CreateTextNode('{message}')) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ptcg-cn-db').Show($toast)
"""


def _osascript_escape(text: str) -> str:
    """转义 osascript 字符串中的双引号和反斜杠。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _pwsh_escape(text: str) -> str:
    return text.replace("'", "''")


def desktop_command(title: str, message: str) -> list[str]:
    """按平台构造桌面通知命令。"""
    system = platform.system()
    if system == "Windows":
        script = (_PWSH_TOAST
            .replace("{title}", _pwsh_escape(title))
            .replace("{message}", _pwsh_escape(message)))
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    if system == "Darwin":
        script = (
            f'display notification "{_osascript_escape(message)}"'
            f' with title "{_osascript_escape(title)}"'
        )
        return ["osascript", "-e", script]
    return ["notify-send", title, message]


class Notifier:
    """桌面 + webhook 双渠道通知器。

    runner: 执行桌面命令的 callable（默认 subprocess.run，超时 10s）。
    poster: 带 .post() 的 httpx.Client（webhook 用，默认每次新建）。
    """

    def __init__(
        self,
        desktop: bool = True,
        webhook_url: str | None = None,
        *,
        runner: Callable[..., Any] | None = None,
        poster: httpx.Client | None = None,
    ) -> None:
        self.desktop = desktop
        self.webhook_url = webhook_url
        self._runner = runner or (
            lambda cmd, **kw: subprocess.run(
                cmd, capture_output=True, timeout=10, check=False, **kw
            )
        )
        self._poster = poster

    def notify(
        self,
        title: str,
        message: str,
        *,
        event: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> list[str]:
        """发送通知，返回成功渠道列表；全部失败也不抛异常。"""
        sent: list[str] = []
        if self.desktop:
            try:
                self._runner(desktop_command(title, message))
                sent.append("desktop")
            except Exception:
                pass
        if self.webhook_url:
            body = {"title": title, "message": message,
                    "event": event, "payload": payload or {}}
            try:
                if self._poster is not None:
                    resp = self._poster.post(
                        self.webhook_url,
                        content=json.dumps(body, ensure_ascii=False),
                        headers={"Content-Type": "application/json"},
                    )
                else:
                    resp = httpx.post(self.webhook_url, json=body, timeout=10.0)
                if resp.status_code < 400:
                    sent.append("webhook")
            except Exception:
                pass
        return sent


_EVENT_TITLES = {
    "increment": "L0 发现卡牌增量",
    "activated": "L0 新卡已合入",
    "blocked": "L0 校验阻断",
    "postprocess": "L0 后处理完成",
    "proposal": "L1 新提案待确认",
    "news": "官网新公告",
}


def _event_message(event: str, payload: dict[str, Any]) -> str:
    if event == "increment":
        return (f"系列 {payload.get('set_id')}（{payload.get('kind')}）："
                f"{payload.get('current')} → {payload.get('expected')}")
    if event == "activated":
        return f"系列 {payload.get('set_id')} 校验全过，已 active"
    if event == "blocked":
        return f"系列 {payload.get('set_id')} 校验失败已阻断：{', '.join(payload.get('rules', []))}"
    if event == "postprocess":
        return (f"数据版本 {payload.get('data_version')}，"
                f"合入系列：{', '.join(payload.get('activated', []))}")
    if event == "proposal":
        return f"[{payload.get('status')}] {payload.get('path')}"
    if event == "news":
        return f"{payload.get('title')}（{payload.get('href')}）"
    return str(payload)


def make_event_handler(notifier: Notifier) -> Callable[[str, dict[str, Any]], None]:
    """把 Notifier 包装成 run_l0/run_l1 的 on_event 回调（过滤非重要事件）。"""

    def handler(event: str, payload: dict[str, Any]) -> None:
        if event not in NOTIFY_EVENTS:
            return
        notifier.notify(
            _EVENT_TITLES.get(event, f"ptcg-cn-db: {event}"),
            _event_message(event, payload),
            event=event,
            payload=payload,
        )

    return handler

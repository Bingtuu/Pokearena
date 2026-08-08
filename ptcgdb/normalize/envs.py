"""赛事环境推导：赛事日期 ∩ 赛区旋转日历段 → tournaments.env（PRD FR-9.1b，task 028）。

三家赛事数据源均不携带环境标号（CN mik 例外，自带 regulationMark/formatEnd），
统一由「赛事日期 ∩ config/tournament_envs.yml 赛区日历段」推导；未命中（早于
收集起点 / 日历缺口）→ None（不猜，调用方落 NULL + 记 monitor 异常）。
日历种子 append-only，官方旋转公告核实后追加新段，本模块不重读词表以外状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_CALENDAR_PATH = CONFIG_DIR / "tournament_envs.yml"

# 赛事数据源 → 赛区（tournaments.source 开放词表；未知源 → None，不猜）
SOURCE_REGION: dict[str, str] = {
    "mik_moe": "cn",
    "limitless": "en",
    "limitless_site": "en",  # 主站 HTML 人工收录通道（task 028），同为 EN 官方系列赛
    "pokemon_card_jp": "ja",
}


@dataclass(frozen=True)
class EnvSegment:
    """命中的日历段：env 落库值 + 交叉校验用赛制标记集合。"""

    env: str  # allowed_marks 顺序拼接（如 "GHI"，开放字符串）
    allowed_marks: tuple[str, ...]
    region: str


def _parse_day(raw: Any) -> date:
    return date.fromisoformat(str(raw))


def load_calendar(path: str | Path | None = None) -> dict[str, Any]:
    """加载赛区旋转日历种子（config/tournament_envs.yml）。"""
    path = Path(path) if path else DEFAULT_CALENDAR_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["regions"]


def alignment_window(calendar: dict[str, Any] | None = None) -> tuple[date, date]:
    """EN 对齐窗口 = 与 CN 当前段（最新一段）allowed_marks 相同的所有 EN 段的
    [最早 effective_from, 最晚 effective_to]。

    窗口是成本先验（FR-9.1a）：限定 Limitless 采集的翻页范围，减少无效请求；
    赛事是否真正可比对，最终判据是卡级映射 full（解析层职责）。
    effective_to 缺失视为 +∞（窗口右端取有界段的最大值）。
    当前种子真值：(2025-04-11, 2026-04-09)（G/H/I 赛季）。
    """
    calendar = calendar if calendar is not None else load_calendar()
    cn_segments = (calendar.get("cn") or {}).get("segments") or []
    if not cn_segments:
        raise ValueError("CN 赛区日历无段，无法推导对齐窗口")
    latest_cn = max(cn_segments, key=lambda seg: _parse_day(seg["effective_from"]))
    cn_marks = tuple(str(m) for m in latest_cn["allowed_marks"])
    starts: list[date] = []
    ends: list[date] = []
    for seg in (calendar.get("en") or {}).get("segments") or []:
        if tuple(str(m) for m in seg["allowed_marks"]) != cn_marks:
            continue
        starts.append(_parse_day(seg["effective_from"]))
        end_raw = seg.get("effective_to")
        if end_raw:
            ends.append(_parse_day(end_raw))
    if not starts:
        raise ValueError(f"EN 赛区日历无与 CN 当前段同标记（{''.join(cn_marks)}）的段")
    if not ends:
        raise ValueError("EN 对齐段全部无 effective_to，窗口右端无界，拒绝猜测")
    return min(starts), max(ends)


def derive_env(
    region: str | None,
    day: date | None,
    calendar: dict[str, Any] | None = None,
) -> EnvSegment | None:
    """赛事日期命中的唯一日历段（effective_from ≤ day ≤ effective_to|∞）。

    region 不在种子 / day 为空 / 无命中段（早于收集起点或日历缺口）→ None。
    """
    if region is None or day is None:
        return None
    calendar = calendar if calendar is not None else load_calendar()
    segments = (calendar.get(region) or {}).get("segments") or []
    for seg in segments:
        start = _parse_day(seg["effective_from"])
        end_raw = seg.get("effective_to")
        end = _parse_day(end_raw) if end_raw else None
        if start <= day and (end is None or day <= end):
            marks = tuple(str(m) for m in seg["allowed_marks"])
            return EnvSegment(env="".join(marks), allowed_marks=marks, region=region)
    return None

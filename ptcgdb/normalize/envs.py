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

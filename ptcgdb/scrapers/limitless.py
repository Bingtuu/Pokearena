"""Limitless TCG 赛事采集器（FR-9.1 M9-3 EN 对齐窗口接入，task 028）。

接口约定（2026-08-07 实测校准，fixtures 为手写小样本）：
- 均 GET `https://play.limitlesstcg.com/api/...`，响应为**裸数组**（无包装）；
- 匿名限速：响应头 `RateLimit: "50-in-5min"`（50 请求/5 分钟）→ 采集间隔 ≥6s/请求，
  由 HttpClient 限速器（DEFAULT_INTERVAL=6.5s 保险值）保证（FR-9.5 红线）；
- `/api/tournaments?game=PTCG&format=STANDARD&limit=1000&page=N`：按日期降序，
  翻页到头返回空数组；条目字段 game/name/date(UTC ISO)/format/id(24位hex)/players/organizerId；
- `/api/tournaments/{id}/standings`：排名 + deck/decklist（卡条目 = PTCGO set code +
  number + 英文名，跨语言映射在解析层做，不归本模块）；
- `/api/tournaments/{id}/pairings`：round/phase(1=瑞士轮 2=淘汰赛)/table/winner/player1/2，
  平局时 winner 可能为空字符串（本层原样落盘，容错在解析层）；
- 响应校验：HTTP 200 且 body 为 list（空 list 合法），否则抛 LimitlessApiError（进
  question 清单）。HTTP 非 200 由 HttpClient 层处理（5xx 重试 / 403 / 非 JSON 熔断）。

raw 落盘布局（append-only，配合 raw_store.write_raw 使用，见文件尾部路径函数）：
  data/raw/limitless/tournaments/list/page-NNNN.json
  data/raw/limitless/tournaments/standings/{tournamentId}.json
  data/raw/limitless/tournaments/pairings/{tournamentId}.json
注意：Limitless 响应为裸数组，落盘前由 runner 包装为 {"data": [...]}（write_raw 要求映射）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ptcgdb.scrapers.http import HttpClient

BASE_URL = "https://play.limitlesstcg.com"
SOURCE = "limitless"
RAW_SUBDIR = "limitless"  # data/raw/ 下的落盘子目录

# 匿名限速实测：RateLimit: "50-in-5min"（50 请求/5 分钟 = 6s/请求），取 6.5s 保险值（FR-9.5）
DEFAULT_INTERVAL = 6.5

ENDPOINT_TOURNAMENTS = "/api/tournaments"
DEFAULT_PAGE_SIZE = 1000  # 赛事清单页大小（2026-08-07 实测 limit=1000 可用，减少翻页成本）

# 赛事归类（FR-9.1a）：人数门 + 官方系列赛名称正则
MIN_PLAYERS = 32  # 小于 32 人的赛事不收（样本污染）

TIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("regional", re.compile(r"Regional Championship", re.IGNORECASE)),
    ("international", re.compile(r"International Championship", re.IGNORECASE)),
    ("special", re.compile(r"Special Event", re.IGNORECASE)),
    ("league_cup", re.compile(r"League Cup", re.IGNORECASE)),
)


class LimitlessApiError(RuntimeError):
    """业务级失败：HTTP 非 200 或 body 非数组（计为可疑，进 question 清单）。"""

    def __init__(self, endpoint: str, status: int | None, message: Any) -> None:
        super().__init__(f"{endpoint} 返回 status={status} message={message}")
        self.endpoint = endpoint
        self.status = status
        self.message = message


def _require_tournament_id(value: Any) -> str:
    """tournament_id 强校验：实测为 24 位 hex 字符串（照 _require_int 的精神）。"""
    if (
        not isinstance(value, str)
        or len(value) != 24
        or not all(c in "0123456789abcdefABCDEF" for c in value)
    ):
        raise TypeError(f"tournament_id 必须是 24 位 hex 字符串，收到 {value!r}")
    return value


def classify_tournament(name: Any, players: Any) -> tuple[str | None, str]:
    """赛事等级归类：返回 (规范 tier 或 None, 取舍理由)。

    规则（FR-9.1a）：
    - players < MIN_PLAYERS（32）→ 不收（样本污染，人数门）；
    - 名称不命中官方系列赛正则（大小写不敏感）→ 不收；
    - tier 为开放字符串：regional / international / special / league_cup
      （后续 ingest 扩词表映射系数，采集层只记规范 tier）。
    """
    if not isinstance(players, int) or isinstance(players, bool) or players < MIN_PLAYERS:
        return None, f"人数 {players} < {MIN_PLAYERS}（样本污染，FR-9.1a 人数门）"
    text = name if isinstance(name, str) else ""
    for tier, pattern in TIER_PATTERNS:
        if pattern.search(text):
            return tier, f"命中官方系列赛名称正则：{pattern.pattern}"
    return None, "未命中官方系列赛名称（Regional/International/Special Event/League Cup）"


class LimitlessScraper:
    """三个端点的薄封装；返回裸数组，由 runner 包装后交 raw 层落盘。"""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch_tournaments_page(
        self, page: int, limit: int = DEFAULT_PAGE_SIZE
    ) -> list[dict[str, Any]]:
        """赛事清单第 N 页（PTCG/STANDARD，按日期降序；翻页到头返回空数组）。"""
        return self._get(
            ENDPOINT_TOURNAMENTS,
            {"game": "PTCG", "format": "STANDARD", "limit": limit, "page": page},
        )

    def fetch_standings(self, tournament_id: str) -> list[dict[str, Any]]:
        """完整排名：placing/record/drop/deck/decklist（卡 = PTCGO set+number+英文名）。"""
        tid = _require_tournament_id(tournament_id)
        return self._get(f"{ENDPOINT_TOURNAMENTS}/{tid}/standings")

    def fetch_pairings(self, tournament_id: str) -> list[dict[str, Any]]:
        """对阵表：round/phase(1=瑞士轮 2=淘汰赛)/table/winner（平局可为空串）/player1/2。"""
        tid = _require_tournament_id(tournament_id)
        return self._get(f"{ENDPOINT_TOURNAMENTS}/{tid}/pairings")

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        # HTTP 200 且 body 为 list（空 list 合法）；非 list → LimitlessApiError
        body = self._http.get_json(endpoint, params)
        if not isinstance(body, list):
            raise LimitlessApiError(endpoint, 200, f"响应体不是数组: {type(body).__name__}")
        return body


# ---- raw 落盘路径约定（配合 raw_store.write_raw 使用）----

TOURNAMENTS_DIR = "tournaments"


def _page_name(page: int) -> str:
    return f"page-{page:04d}.json"


def tournament_list_path(base_dir: Path, page: int) -> Path:
    """赛事清单第 N 页：tournaments/list/page-NNNN.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "list" / _page_name(page)


def standings_path(base_dir: Path, tournament_id: str) -> Path:
    """完整排名：tournaments/standings/{tournamentId}.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "standings" / f"{tournament_id}.json"


def pairings_path(base_dir: Path, tournament_id: str) -> Path:
    """对阵表：tournaments/pairings/{tournamentId}.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "pairings" / f"{tournament_id}.json"

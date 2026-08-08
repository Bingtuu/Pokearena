"""Limitless 主站 HTML 人工收录通道（task 028 扩展：官方线下大赛上位卡组，API 覆盖不到的部分）。

与 scrapers/limitless.py（play.limitlesstcg.com JSON API）并列：主站 limitlesstcg.com
收录官方系列赛（NAIC/Regional/Special Event 等）的**人工核实**名次+卡组，无 record/
比分、无 pairings。本模块只做采集（解析+抓取），入库管线是下一步。

结构约定（2026-08-08 真实样本校准，fixtures 照此形态手写）：
- 索引页 `GET /tournaments?time={season}&format=standard&show=100`：数据行
  `<tr data-date="2026-06-10" data-country="US" data-name="NAIC 2026, New Orleans"
  data-format="standard" data-players="3752" data-winner="...">`，赛事链接
  `/tournaments/{数字id}` 在行内。**日期直接用 data-date（ISO），无需换算两位年份
  文本**（"10 Jun 26" 仅作 data-date 缺失时的兜底）。season 标签 = 起年两位+止年
  两位（如 2526 = 2025-08~2026-07 赛季）。
- **分页校准结论**：2526 赛季全量 42 行 < show=100 上限，页面不渲染任何翻页链接
  → 单赛季索引单页即可抓全；`?page=N` 参数**未实测**（页面无翻页 UI 可校），仅在
  某页恰好返回 100 行（= show 上限，可能截断）时作为 best-effort 猜测追加请求，
  runner 同时用"无新 tournament_id 即停"兜底（参数被忽略返回重复页也能正确终止）。
- 赛事页 `/tournaments/{数字id}`：standings 表行
  `<tr data-rank="1" data-name="..." data-country=".." data-deck="...">`，行内含
  `/decks/{archetypeId}`（可带 ?variant=N）与 `/decks/list/{decklistId}` 链接；
  名次/选手/卡组名全部在 data-* 属性里。实测 NAIC 2026 = 675 行（全部交表选手，
  非仅 Top Cut）。无 record/pairings（人工收录只有名次+卡组）。
- 卡组页 `/decks/list/{decklistId}`：`<title>{archetype} by {player} – Limitless
  </title>`（en dash U+2013）；卡条目 `<div class="decklist-card" data-set="MEG"
  data-number="104" data-lang="en">` 内 `<span class="card-count">4</span>` +
  `<span class="card-name">Mega Kangaskhan ex</span>`；分节标题
  `<div class="decklist-column-heading">Pokémon (22)</div>`（section 一并落盘——
  raw 是 append-only 快照，stat_scope 判定靠它，不抓则入库时无法回补）。

raw 落盘口径：**存解析后的结构化 JSON，不存原始 HTML**（HTML ~40-640KB/页 × 数千页
体量过大；与 mik 存原始响应不同，这里落"采集时点的解析快照"，原始页可由 url 重访）。
  data/raw/limitless_site/tournaments/index/{season}/page-N.json
  data/raw/limitless_site/tournaments/standings/{tournamentId}.json
  data/raw/limitless_site/decks/list/{decklistId}.json

限速：主站 HTML 无 API 限速头，按 ≥2s/请求红线自控取 2.5s（DEFAULT_INTERVAL）；
robots 全放行、ToS 无反爬（docs/data-sources.md §7）。项目无 bs4/lxml 依赖，
解析用正则（页面为机器生成的固定形态，fixtures 锁定结构）。
"""

from __future__ import annotations

import re
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any

from ptcgdb.scrapers.http import HttpClient

BASE_URL = "https://limitlesstcg.com"
SOURCE = "limitless_site"
RAW_SUBDIR = "limitless_site"  # data/raw/ 下的落盘子目录

# 主站 HTML 无限速头，按 ≥2s/请求红线自控取 2.5s（FR-9.5）
DEFAULT_INTERVAL = 2.5

INDEX_PAGE_SIZE = 100  # 索引页 show 参数上限（实测 2526 赛季 42 行，单页抓全）
MIN_PLAYERS = 32  # 人数门沿用 FR-9.1a（索引行 data-players）

# 主站赛事归类（FR-9.1a）：名称形态与 API 不同（"NAIC 2026, New Orleans" /
# "Regional Indianapolis, IN" / "Special Event Turin"），故独立于
# scrapers/limitless.py 的 TIER_PATTERNS 自带一套（SITE_ 前缀）。
SITE_TIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("international", re.compile(
        r"\b(NAIC|EUIC|LAIC|OCIC)\b|International Championship", re.IGNORECASE
    )),
    ("special", re.compile(r"Special Event", re.IGNORECASE)),
    ("regional", re.compile(r"\bRegional\b", re.IGNORECASE)),
    ("league_cup", re.compile(r"League Cup", re.IGNORECASE)),
)

# JP/亚洲国内赛事提示（白名单外的拒收理由细化：FR-9.1a 本轮只收 EN 官方系列赛，
# JP 对齐二期再议；命中者给明确理由而不是笼统"未命中"）。
JP_DOMESTIC_PATTERN = re.compile(
    r"Japan Championships|Champions League|Korean League|Premier Ball League|\bJCS\b",
    re.IGNORECASE,
)


class LimitlessSiteApiError(RuntimeError):
    """业务级失败：HTTP 非 200（计为可疑，进 question 清单）。"""

    def __init__(self, endpoint: str, status: int | None, message: Any) -> None:
        super().__init__(f"{endpoint} 返回 status={status} message={message}")
        self.endpoint = endpoint
        self.status = status
        self.message = message


# ---- 解析器（纯函数，输入 HTML 字符串 → 结构化 dict，零网络便于测试）----
# 解析对缺字段宽容：缺则 None，由调用方记 warning，不猜。

_ATTR_RE = re.compile(r"([\w-]+)=\"([^\"]*)\"")
_INDEX_ROW_RE = re.compile(r"<tr\b(?P<attrs>[^>]*)>(?P<body>.*?)</tr>", re.DOTALL)
_STANDINGS_ROW_RE = re.compile(
    r"<tr\b(?P<attrs>[^>]*\bdata-rank=\"[^\"]*\"[^>]*)>(?P<body>.*?)</tr>", re.DOTALL
)
_TOURNAMENT_LINK_RE = re.compile(r"href=\"/tournaments/(\d+)\"")
_DECKLIST_LINK_RE = re.compile(r"href=\"(/decks/list/(\d+))\"")
_ARCHETYPE_LINK_RE = re.compile(r"href=\"(/decks/(\d+)(\?variant=\d+)?)\"")
_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.DOTALL)
_HEADING_RE = re.compile(r'<div class="decklist-column-heading">(?P<label>[^<]+)</div>')
_CARD_OPEN_RE = re.compile(r'<div class="decklist-card"(?P<attrs>[^>]*)>')
_CARD_COUNT_RE = re.compile(r'<span class="card-count">(?P<count>\d+)</span>')
_CARD_NAME_RE = re.compile(r'<span class="card-name">(?P<name>.*?)</span>', re.DOTALL)
_TITLE_SUFFIX = "– Limitless"  # en dash U+2013

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2})\b")


def _attrs(tag_attrs: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _ATTR_RE.finditer(tag_attrs)}


def _parse_text_date(text: str) -> str | None:
    """兜底日期换算："10 Jun 26" → 2026-06-10。两位年份规则：≤50 → 20xx，>50 → 19xx。

    正常路径用 data-date（ISO），本规则仅在属性缺失时启用。
    """
    m = _TEXT_DATE_RE.search(text)
    if not m:
        return None
    day, mon, year2 = m.group(1), m.group(2).lower(), int(m.group(3))
    month = _MONTHS.get(mon)
    if month is None:
        return None
    year = 2000 + year2 if year2 <= 50 else 1900 + year2
    try:
        return date(year, month, int(day)).isoformat()
    except ValueError:
        return None


def _page_title(html: str) -> str | None:
    """<title>{主体} – Limitless</title> → 主体（HTML 反转义）。"""
    m = _TITLE_RE.search(html)
    if not m:
        return None
    title = unescape(m.group("title")).strip()
    if title.endswith(_TITLE_SUFFIX):
        title = title[: -len(_TITLE_SUFFIX)].strip()
    return title or None


def parse_index_page(html: str) -> list[dict[str, Any]]:
    """索引页 → [{tournament_id, name, date, players, country, url}]。

    数据行判据 = 带 data-date 属性或行内含 /tournaments/{id} 链接（表头 <th> 行与
    页头快捷链接天然排除）。字段缺失宽容：date 退化到 "10 Jun 26" 文本换算，
    其余缺则 None。
    """
    entries: list[dict[str, Any]] = []
    for m in _INDEX_ROW_RE.finditer(html):
        attrs = _attrs(m.group("attrs"))
        body = m.group("body")
        link = _TOURNAMENT_LINK_RE.search(body)
        day = attrs.get("data-date") or _parse_text_date(body)
        if day is None and link is None:
            continue  # 表头/非数据行
        players_raw = attrs.get("data-players")
        entries.append(
            {
                "tournament_id": link.group(1) if link else None,
                "name": unescape(attrs["data-name"]) if attrs.get("data-name") else None,
                "date": day,
                "players": int(players_raw) if players_raw and players_raw.isdigit() else None,
                "country": attrs.get("data-country") or None,
                "url": f"/tournaments/{link.group(1)}" if link else None,
            }
        )
    return entries


def parse_standings_page(html: str) -> dict[str, Any]:
    """赛事页 → {name, standings: [{placing, player, country, archetype_name,
    deck_url, decklist_id, archetype_url, archetype_id}]}。

    名次/选手/卡组名在 <tr> 的 data-* 属性；decklist/archetype 链接在行内。
    无卡组链接的行（未交表选手）decklist_id=None 保留原行，不猜。
    """
    standings: list[dict[str, Any]] = []
    for m in _STANDINGS_ROW_RE.finditer(html):
        attrs = _attrs(m.group("attrs"))
        body = m.group("body")
        deck_link = _DECKLIST_LINK_RE.search(body)
        arch_link = _ARCHETYPE_LINK_RE.search(body)
        rank_raw = attrs.get("data-rank")
        standings.append(
            {
                "placing": int(rank_raw) if rank_raw and rank_raw.isdigit() else None,
                "player": unescape(attrs["data-name"]) if attrs.get("data-name") else None,
                "country": attrs.get("data-country") or None,
                "archetype_name": unescape(attrs["data-deck"]) if attrs.get("data-deck") else None,
                "deck_url": deck_link.group(1) if deck_link else None,
                "decklist_id": deck_link.group(2) if deck_link else None,
                "archetype_url": arch_link.group(1) if arch_link else None,
                "archetype_id": arch_link.group(2) if arch_link else None,
            }
        )
    return {"name": _page_title(html), "standings": standings}


def parse_decklist_page(html: str) -> dict[str, Any]:
    """卡组页 → {archetype, player, cards: [{set, number, name, count, section}]}。

    archetype/player 从 <title> "{archetype} by {player} – Limitless" 解析
    （rsplit 一次 " by "，player 含 " by " 时归 player）；卡条目按
    decklist-column-heading 分节（Pokémon/Trainer/Energy 原文标签落 section）。
    缺 count/name 的卡条目字段为 None 保留，不猜。
    """
    title = _page_title(html)
    archetype = player = None
    if title:
        if " by " in title:
            archetype, player = (part.strip() or None for part in title.rsplit(" by ", 1))
        else:
            archetype = title

    # 事件流：分节标题与卡条目按文档位置排序，逐卡归属最近的分节
    events: list[tuple[int, str, re.Match[str]]] = []
    for m in _HEADING_RE.finditer(html):
        events.append((m.start(), "heading", m))
    for m in _CARD_OPEN_RE.finditer(html):
        events.append((m.start(), "card", m))
    events.sort(key=lambda e: e[0])

    cards: list[dict[str, Any]] = []
    section: str | None = None
    for i, (pos, kind, m) in enumerate(events):
        if kind == "heading":
            label = m.group("label").strip()
            section = label.split("(")[0].strip() or None  # "Pokémon (22)" → "Pokémon"
            continue
        end = events[i + 1][0] if i + 1 < len(events) else len(html)
        body = html[pos:end]
        attrs = _attrs(m.group("attrs"))
        count_m = _CARD_COUNT_RE.search(body)
        name_m = _CARD_NAME_RE.search(body)
        cards.append(
            {
                "set": attrs.get("data-set") or None,
                "number": attrs.get("data-number") or None,
                "name": unescape(name_m.group("name")).strip() if name_m else None,
                "count": int(count_m.group("count")) if count_m else None,
                "section": section,
            }
        )
    return {"archetype": archetype, "player": player, "cards": cards}


# ---- 赛事归类（FR-9.1a 主站变体）----


def classify_site_tournament(
    name: Any, players: Any, country: Any = None
) -> tuple[str | None, str]:
    """主站赛事等级归类：返回 (规范 tier 或 None, 取舍理由)。

    规则（FR-9.1a 主站变体）：
    - players < MIN_PLAYERS（32）→ 不收（人数门，与 API 通道一致）；
    - 名称命中 SITE_TIER_PATTERNS（NAIC/EUIC/LAIC/OCIC/International → international；
      Special Event → special；Regional → regional；League Cup → league_cup）→ 收；
    - JP/亚洲国内赛事（Japan Championships/Champions League/Korean League/
      Premier Ball League 等）→ 不收（本轮只收 EN 官方系列赛，JP 对齐二期再议）；
    - 其余不命中 → 不收。tier 为开放字符串，采集层只记规范 tier。
    """
    if not isinstance(players, int) or isinstance(players, bool) or players < MIN_PLAYERS:
        return None, f"人数 {players} < {MIN_PLAYERS}（样本污染，FR-9.1a 人数门）"
    text = name if isinstance(name, str) else ""
    for tier, pattern in SITE_TIER_PATTERNS:
        if pattern.search(text):
            return tier, f"命中官方系列赛名称正则：{pattern.pattern}"
    if JP_DOMESTIC_PATTERN.search(text):
        return None, "JP/亚洲国内赛事（FR-9.1a 本轮只收 EN 官方系列赛，JP 对齐二期再议）"
    return None, "未命中官方系列赛名称（NAIC/EUIC/LAIC/OCIC/Regional/Special Event/League Cup）"


# ---- 赛季标签 ----


def season_of_date(day: date) -> str:
    """日期所属赛季标签：赛季 = 8 月 ~ 次年 7 月，标签 = 起年两位+止年两位
    （2026-04-09 → "2526"；2025-08-01 → "2526"；2025-04-11 → "2425"）。"""
    start_year = day.year if day.month >= 8 else day.year - 1
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def seasons_for_window(window_from: date, window_to: date) -> list[str]:
    """覆盖窗口的赛季列表（窗口 2025-04-11~2026-04-09 → ["2425", "2526"]）。"""
    first = season_of_date(window_from)
    last = season_of_date(window_to)
    seasons = []
    year = 2000 + int(first[:2])
    while len(seasons) < 10:  # 保险上限：窗口不会跨 10 个赛季
        label = f"{year % 100:02d}{(year + 1) % 100:02d}"
        seasons.append(label)
        if label == last:
            break
        year += 1
    return seasons


# ---- 抓取封装 ----


def _require_numeric_id(kind: str, value: Any) -> str:
    """主站 id 强校验：数字字符串（照 limitless._require_tournament_id 的精神）。"""
    if not isinstance(value, str) or not value.isdigit():
        raise TypeError(f"{kind} 必须是数字字符串，收到 {value!r}")
    return value


class LimitlessSiteScraper:
    """主站三类页面的薄封装：get_text 抓 HTML → 解析器 → 结构化 dict。

    HTTP 200 校验：非 200 抛 LimitlessSiteApiError（进 question 清单）；
    403/5xx/熔断由 HttpClient 层处理。
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch_index_page(self, season: str, page: int = 1) -> list[dict[str, Any]]:
        """赛季索引第 N 页。page>1 时追加 ?page=N（未实测校准参数，见模块 docstring：
        仅在恰好 100 行边界触发，runner 用"无新 id 即停"兜底）。"""
        params: dict[str, Any] = {"time": season, "format": "standard", "show": INDEX_PAGE_SIZE}
        if page > 1:
            params["page"] = page
        html = self._get("/tournaments", params)
        return parse_index_page(html)

    def fetch_standings(self, tournament_id: str) -> dict[str, Any]:
        """赛事页 standings（名次+选手+卡组链接；无 record/pairings）。"""
        tid = _require_numeric_id("tournament_id", tournament_id)
        html = self._get(f"/tournaments/{tid}")
        result = parse_standings_page(html)
        result["tournament_id"] = tid
        return result

    def fetch_decklist(self, decklist_id: str) -> dict[str, Any]:
        """卡组页（title 解析 archetype/player；卡条目 set+number+count+section）。"""
        did = _require_numeric_id("decklist_id", decklist_id)
        html = self._get(f"/decks/list/{did}")
        result = parse_decklist_page(html)
        result["decklist_id"] = did
        return result

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        status, text = self._http.get_text(endpoint, params)
        if status != 200:
            raise LimitlessSiteApiError(
                endpoint, status, f"HTTP 非 200（前 80 字符: {text[:80]!r}）"
            )
        return text


# ---- raw 落盘路径约定（配合 raw_store.write_raw 使用）----

TOURNAMENTS_DIR = "tournaments"


def index_path(base_dir: Path, season: str, page: int) -> Path:
    """赛季索引第 N 页：tournaments/index/{season}/page-N.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "index" / season / f"page-{page}.json"


def standings_path(base_dir: Path, tournament_id: str) -> Path:
    """赛事页 standings：tournaments/standings/{tournamentId}.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "standings" / f"{tournament_id}.json"


def decklist_path(base_dir: Path, decklist_id: str) -> Path:
    """卡组页：decks/list/{decklistId}.json。"""
    return base_dir / RAW_SUBDIR / "decks" / "list" / f"{decklist_id}.json"

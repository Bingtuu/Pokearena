"""tcg.mik.moe 赛事采集器（FR-9.1，task 027）。

接口约定见 docs/data-sources.md §1"赛事 API"小节：
- 与卡牌端点同风格：均 POST `https://tcg.mik.moe/api/v3/...`，响应包装 `{code, data, msg}`；
- 响应校验同卡牌接口：HTTP 200 且 body code==200 且 data 非空，否则抛 MikMoeApiError；
- 采集纪律（FR-9.5）：2s/请求（HttpClient 限速器保证）；rank-individual 默认 64/页与
  top64 对齐，只拉上位卡组；player_ref 只存 pinCode（解析层职责）。

真实 API 校准（2026-08-02 探测，fixtures 为真实响应脱敏版）：
- seriesId / tournamentId / deckId 必须传 **int**（传 str 报 10002，与 cardIndex
  必须传 str 的规则相反）；本模块对 id 参数做强类型校验，非 int 直接 TypeError；
- series-list / tournament/list / detail 的条目主键字段为 `id`（不是 seriesId/
  tournamentId）；series-list 响应无 total/pages，翻页以空 list 或不足页终止；
- deck-static-by-tour **只传 {tournamentId}**，多传任何参数报 10002；
- 可预期空结果（不是故障）→ MikMoeNotReadyError：rank-individual 对进行中赛事
  返回 code=400（"赛事未结束"）；deck-static 对无数据赛事返回 code=10002。

raw 落盘布局（append-only，配合 raw_store.write_raw 使用，见文件尾部路径函数）：
  data/raw/mikmoe/tournaments/series-list/page-NNNN.json
  data/raw/mikmoe/tournaments/list/{seriesId}/page-NNNN.json
  data/raw/mikmoe/tournaments/detail/{tournamentId}.json
  data/raw/mikmoe/tournaments/rank-individual/{tournamentId}/page-NNNN.json
  data/raw/mikmoe/decks/detail/{deckId}.json
  data/raw/mikmoe/decks/deck-static-by-tour/{tournamentId}.json
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ptcgdb.scrapers.http import HttpClient
from ptcgdb.scrapers.mikmoe import RAW_SUBDIR, MikMoeApiError

ENDPOINT_SERIES_LIST = "/api/v3/tournament/series-list"
ENDPOINT_TOURNAMENT_LIST = "/api/v3/tournament/list"
ENDPOINT_TOURNAMENT_DETAIL = "/api/v3/tournament/detail"
ENDPOINT_RANK_INDIVIDUAL = "/api/v3/tournament/rank-individual"
ENDPOINT_DECK_DETAIL = "/api/v3/deck/detail"
ENDPOINT_DECK_STATIC_BY_TOUR = "/api/v3/deck/deck-static-by-tour"
ENDPOINT_REGULATION_LIST = "/api/v3/tournament/regulation-list"

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 100  # 清单类端点默认页大小
RANK_PAGE_SIZE = 64  # rank-individual 默认 64/页，与 top64 对齐（FR-9.5）


class MikMoeNotReadyError(MikMoeApiError):
    """可预期空结果（不是故障）：进行中赛事无排名 / 赛事无 Meta 数据。

    调用方（runner）按 question 清单处理并跳过，不触发熔断。
    """


def _require_int(value: Any, name: str) -> int:
    """id 参数强校验：实测 mik 赛事端点只接受 int（传 str 报 10002）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须传 int（实测传 str 报 10002），收到 {value!r}")
    return value


class MikMoeTournamentScraper:
    """赛事端点薄封装；返回完整响应包装（含 code/data/msg），由 raw 层原样落盘。"""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch_series_list(
        self, page: int = DEFAULT_PAGE, page_size: int = DEFAULT_PAGE_SIZE
    ) -> dict[str, Any]:
        """赛事系列清单：name/startDate/endDate/status/tournamentNum/link（官方公告页）。"""
        return self._post(ENDPOINT_SERIES_LIST, {"page": page, "pageSize": page_size})

    def fetch_tournament_list(
        self,
        series_id: int,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """系列下具体赛事：name/endDate/location/type/division/participantCount/isQual/isTeam。"""
        return self._post(
            ENDPOINT_TOURNAMENT_LIST,
            {"seriesId": _require_int(series_id, "series_id"),
             "page": page, "pageSize": page_size},
        )

    def fetch_tournament_detail(self, tournament_id: int) -> dict[str, Any]:
        """赛事详情：regulation / regulationMark（GHI）/ formatEnd（截止系列）。"""
        return self._post(
            ENDPOINT_TOURNAMENT_DETAIL,
            {"tournamentId": _require_int(tournament_id, "tournament_id")},
        )

    def fetch_rank_individual(
        self,
        tournament_id: int,
        page: int = DEFAULT_PAGE,
        page_size: int = RANK_PAGE_SIZE,
    ) -> dict[str, Any]:
        """完整排名：rank/points/players[].pinCode/decks[].deckId + variant 归类。

        默认 64/页与 top64 对齐（FR-9.5 只拉上位卡组）。进行中赛事返回
        code=400（"赛事未结束"）→ MikMoeNotReadyError（可预期空结果）。
        """
        return self._post(
            ENDPOINT_RANK_INDIVIDUAL,
            {"tournamentId": _require_int(tournament_id, "tournament_id"),
             "page": page, "pageSize": page_size},
        )

    def fetch_deck_detail(self, deck_id: int) -> dict[str, Any]:
        """卡组构成：卡标识 = setCode+cardIndex（与本库主键一致），含 count/deckCode。"""
        return self._post(
            ENDPOINT_DECK_DETAIL, {"deckId": _require_int(deck_id, "deck_id")}
        )

    def fetch_deck_static_by_tour(self, tournament_id: int) -> dict[str, Any]:
        """Meta 统计：每 variant 的 count/share/points/topcutTimes（抽样对账用）。

        实测只接受 {tournamentId} 一个参数，多传任何参数报 10002；对无数据
        赛事返回 code=10002 → MikMoeNotReadyError（可预期空结果）。
        """
        return self._post(
            ENDPOINT_DECK_STATIC_BY_TOUR,
            {"tournamentId": _require_int(tournament_id, "tournament_id")},
        )

    def fetch_regulation_list(self) -> dict[str, Any]:
        """赛制词表（"赛制标记-截止系列"形态，如 GHI-CSV10C）。"""
        return self._post(ENDPOINT_REGULATION_LIST, {})

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        # 与 MikMoeScraper 同规则：HTTP 200 且 body code==200 且 data 非空
        body = self._http.post_json(endpoint, payload)
        if not isinstance(body, dict):
            raise MikMoeApiError(endpoint, None, f"响应体不是对象: {type(body).__name__}")
        code = body.get("code")
        data = body.get("data")
        # 可预期空结果（不是故障）：进行中赛事无排名（400）/ 赛事无 Meta 数据（10002）
        if endpoint == ENDPOINT_RANK_INDIVIDUAL and code == 400:
            raise MikMoeNotReadyError(endpoint, code, body.get("msg"))
        if endpoint == ENDPOINT_DECK_STATIC_BY_TOUR and code == 10002:
            raise MikMoeNotReadyError(endpoint, code, body.get("msg"))
        if code != 200 or data in (None, "", [], {}):
            raise MikMoeApiError(endpoint, code, body.get("msg"))
        return body


# ---- raw 落盘路径约定（配合 raw_store.write_raw 使用）----

TOURNAMENTS_DIR = "tournaments"
DECKS_DIR = "decks"


def _page_name(page: int) -> str:
    return f"page-{page:04d}.json"


def series_list_path(base_dir: Path, page: int) -> Path:
    """series-list 第 N 页：tournaments/series-list/page-NNNN.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "series-list" / _page_name(page)


def tournament_list_path(base_dir: Path, series_id: str, page: int) -> Path:
    """系列下赛事清单第 N 页：tournaments/list/{seriesId}/page-NNNN.json。"""
    return (
        base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "list" / series_id / _page_name(page)
    )


def tournament_detail_path(base_dir: Path, tournament_id: str) -> Path:
    """赛事详情：tournaments/detail/{tournamentId}.json。"""
    return base_dir / RAW_SUBDIR / TOURNAMENTS_DIR / "detail" / f"{tournament_id}.json"


def rank_individual_path(base_dir: Path, tournament_id: str, page: int) -> Path:
    """排名第 N 页：tournaments/rank-individual/{tournamentId}/page-NNNN.json。"""
    return (
        base_dir
        / RAW_SUBDIR
        / TOURNAMENTS_DIR
        / "rank-individual"
        / tournament_id
        / _page_name(page)
    )


def deck_detail_path(base_dir: Path, deck_id: str) -> Path:
    """卡组构成：decks/detail/{deckId}.json。"""
    return base_dir / RAW_SUBDIR / DECKS_DIR / "detail" / f"{deck_id}.json"


def deck_static_path(base_dir: Path, tournament_id: str) -> Path:
    """Meta 统计：decks/deck-static-by-tour/{tournamentId}.json。"""
    return (
        base_dir / RAW_SUBDIR / DECKS_DIR / "deck-static-by-tour" / f"{tournament_id}.json"
    )

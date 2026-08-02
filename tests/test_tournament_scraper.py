"""task 027 赛事采集器测试：端点/参数/错误处理/raw 路径约定。

全部用 httpx MockTransport，零网络。fixtures 为 2026-08-02 真实 API 探测响应
（.scratch/probe_out，nickname 已脱敏）。
真实校准要点：seriesId/tournamentId/deckId 必须传 int（传 str 报 10002，与
cardIndex 规则相反）；deck-static-by-tour 只传 {tournamentId}；rank 对进行中
赛事返回 code=400（"赛事未结束"，可预期空结果 → MikMoeNotReadyError）。
"""

import json
from pathlib import Path

import httpx
import pytest
from tenacity import wait_none

from ptcgdb.scrapers import HttpClient, MikMoeApiError, RateLimiter
from ptcgdb.scrapers.mikmoe_tournament import (
    MikMoeNotReadyError,
    MikMoeTournamentScraper,
    deck_detail_path,
    deck_static_path,
    rank_individual_path,
    series_list_path,
    tournament_detail_path,
    tournament_list_path,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tournaments"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_scraper(handler) -> MikMoeTournamentScraper:
    client = HttpClient(
        "https://tcg.mik.moe",
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(interval=0),
        retry_wait=wait_none(),
    )
    return MikMoeTournamentScraper(client)


def read_body_json(request):
    return json.loads(request.content.decode("utf-8"))


def routing_handler(routes):
    """routes: {path: envelope}；同时记录每个端点收到的请求体。"""

    calls = {}

    def handler(request):
        path = request.url.path
        assert path in routes, f"unexpected path {path}"
        calls.setdefault(path, []).append(read_body_json(request))
        return httpx.Response(200, json=routes[path])

    handler.calls = calls
    return handler


ROUTES = {
    "/api/v3/tournament/series-list": load_fixture("series_list.json"),
    "/api/v3/tournament/list": load_fixture("tournament_list.json"),
    "/api/v3/tournament/detail": load_fixture("tournament_detail.json"),
    "/api/v3/tournament/rank-individual": load_fixture("rank_individual.json"),
    "/api/v3/deck/detail": load_fixture("deck_detail.json"),
    "/api/v3/deck/deck-static-by-tour": load_fixture("deck_static_by_tour.json"),
    "/api/v3/tournament/regulation-list": {
        "code": 200,
        "data": {"list": ["GHI-CSV10C", "HI-CSV9C"]},
        "msg": "",
    },
}


# ---- 端点与请求体 ----


def test_fetch_series_list():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_series_list(page=2, page_size=50)
    assert body["data"]["list"][0]["id"] == 54
    assert handler.calls["/api/v3/tournament/series-list"] == [
        {"page": 2, "pageSize": 50}
    ]


def test_fetch_tournament_list():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_tournament_list(54)
    assert body["data"]["list"][0]["id"] == 3215
    # seriesId 必须传 int（实测传 str 报 10002）；默认翻页参数
    assert handler.calls["/api/v3/tournament/list"] == [
        {"seriesId": 54, "page": 1, "pageSize": 100}
    ]


def test_fetch_tournament_detail():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_tournament_detail(3211)
    assert body["data"]["regulationMark"] == "FGH"
    assert handler.calls["/api/v3/tournament/detail"] == [{"tournamentId": 3211}]


def test_fetch_rank_individual_default_page_size_64():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_rank_individual(3211)
    assert body["data"]["list"][0]["decks"][0]["deckId"] == 610080
    # 默认 64/页与 top64 对齐（FR-9.5）
    assert handler.calls["/api/v3/tournament/rank-individual"] == [
        {"tournamentId": 3211, "page": 1, "pageSize": 64}
    ]


def test_fetch_deck_detail():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_deck_detail(610080)
    assert body["data"]["cards"][0]["cardName"] == "玛纳霏"
    assert handler.calls["/api/v3/deck/detail"] == [{"deckId": 610080}]


def test_fetch_deck_static_by_tour_only_tournament_id():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_deck_static_by_tour(3211)
    assert body["data"]["list"][0]["name"] == "喷火龙"
    # 实测：只传 {tournamentId}，多传 topcut/points/isVariant 任何参数都 10002
    assert handler.calls["/api/v3/deck/deck-static-by-tour"] == [{"tournamentId": 3211}]


def test_fetch_regulation_list():
    handler = routing_handler(ROUTES)
    scraper = make_scraper(handler)
    body = scraper.fetch_regulation_list()
    assert body["data"]["list"] == ["GHI-CSV10C", "HI-CSV9C"]
    assert handler.calls["/api/v3/tournament/regulation-list"] == [{}]


# ---- id 必须传 int（与 cardIndex 必须 str 相反，2026-08-02 实测）----


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.fetch_tournament_list("54"),
        lambda s: s.fetch_tournament_detail("3211"),
        lambda s: s.fetch_rank_individual("3211"),
        lambda s: s.fetch_deck_detail("610080"),
        lambda s: s.fetch_deck_static_by_tour("3211"),
    ],
)
def test_ids_must_be_int(call):
    scraper = make_scraper(lambda r: httpx.Response(200, json=load_fixture("series_list.json")))
    with pytest.raises(TypeError):
        call(scraper)


# ---- 错误处理 ----


def test_api_error_on_bad_code():
    def handler(request):
        return httpx.Response(200, json={"code": 10002, "data": None, "msg": "内部错误"})

    scraper = make_scraper(handler)
    with pytest.raises(MikMoeApiError) as exc_info:
        scraper.fetch_tournament_detail(3211)
    assert exc_info.value.code == 10002


def test_api_error_on_empty_data():
    def handler(request):
        return httpx.Response(200, json={"code": 200, "data": {}, "msg": ""})

    scraper = make_scraper(handler)
    with pytest.raises(MikMoeApiError):
        scraper.fetch_rank_individual(9999)


def test_api_error_on_non_dict_body():
    def handler(request):
        return httpx.Response(200, json=[1, 2, 3])

    scraper = make_scraper(handler)
    with pytest.raises(MikMoeApiError):
        scraper.fetch_series_list()


def test_rank_ongoing_tournament_raises_not_ready():
    """进行中赛事 rank 返回 code=400（"赛事未结束"）→ 可预期空结果，不是故障。"""
    def handler(request):
        return httpx.Response(200, json=load_fixture("rank_ongoing.json"))

    scraper = make_scraper(handler)
    with pytest.raises(MikMoeNotReadyError) as exc_info:
        scraper.fetch_rank_individual(3469)
    assert exc_info.value.code == 400
    # NotReady 是 MikMoeApiError 的子类（调用方按 question 处理，不熔断）
    assert isinstance(exc_info.value, MikMoeApiError)


def test_deck_static_no_data_raises_not_ready():
    """deck-static 对无数据赛事返回 10002 → 同样按可预期空结果处理。"""
    def handler(request):
        return httpx.Response(200, json={"code": 10002, "data": None, "msg": "内部错误"})

    scraper = make_scraper(handler)
    with pytest.raises(MikMoeNotReadyError):
        scraper.fetch_deck_static_by_tour(3211)


# ---- raw 落盘路径约定 ----


def test_raw_paths(tmp_path):
    base = tmp_path / "raw"
    assert (
        series_list_path(base, 3)
        == base / "mikmoe" / "tournaments" / "series-list" / "page-0003.json"
    )
    assert (
        tournament_list_path(base, "54", 1)
        == base / "mikmoe" / "tournaments" / "list" / "54" / "page-0001.json"
    )
    assert (
        tournament_detail_path(base, "3211")
        == base / "mikmoe" / "tournaments" / "detail" / "3211.json"
    )
    assert (
        rank_individual_path(base, "3211", 12)
        == base / "mikmoe" / "tournaments" / "rank-individual" / "3211" / "page-0012.json"
    )
    assert deck_detail_path(base, "610080") == base / "mikmoe" / "decks" / "detail" / "610080.json"
    assert (
        deck_static_path(base, "3211")
        == base / "mikmoe" / "decks" / "deck-static-by-tour" / "3211.json"
    )

"""task 028 扩展测试：Limitless 主站 HTML 人工收录通道（解析器 / 归类 / runner / CLI）。

全部零网络：get_text 用 httpx MockTransport，runner 用 fixtures 背书的假 scraper
（鸭子类型，无 HTTP）。fixtures 为手写小样本，照 2026-08-08 真实样本结构（索引行
data-* 属性 / standings data-rank 行 / 卡组页 decklist-card + card-count span）：
index = 7 场（NAIC international / Special Event Turin / Regional Indianapolis /
Korean League（JP 拒）/ Japan Championships（JP 拒）/ 16 人小 regional（人数门拒）/
2024 旧 regional（窗口外））；standings 4 行（含 ?variant archetype、共享 decklist、
未交表无链接行）；decklist 3 节 4 卡（含 &#039; 实体）。覆盖：
- get_text：200 返回 (status, text)、HTML 不触发"非 JSON"熔断、404 原样返回、
  403 熔断、5xx 重试；
- 三解析器：字段提取 / HTML 实体反转义 / 缺字段宽容 None / 文本日期兜底换算；
- classify_site_tournament 矩阵：四种官方 tier（主站名称形态）、大小写、<32 人拒、
  JP/亚洲国内赛事拒、非官方名拒；
- 赛季标签：season_of_date / seasons_for_window；
- runner：窗口过滤 / 赛季推导与显式 seasons / accepted 抓 standings+去重 decklist /
  满页翻页与"无新 id"兜底 / 断点续传 / 熔断 aborted / missing 对账 / 取舍决策落 stats；
- CLI 冒烟：scrape limitless-site。
"""

from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tenacity import wait_none
from typer.testing import CliRunner

from ptcgdb import cli
from ptcgdb.orm import ScrapeRun
from ptcgdb.scrapers import CircuitOpenError, HttpClient, RateLimiter
from ptcgdb.scrapers.limitless_site import (
    BASE_URL,
    INDEX_PAGE_SIZE,
    LimitlessSiteApiError,
    LimitlessSiteScraper,
    classify_site_tournament,
    decklist_path,
    index_path,
    parse_decklist_page,
    parse_index_page,
    parse_standings_page,
    season_of_date,
    seasons_for_window,
    standings_path,
)
from ptcgdb.scrapers.limitless_site_runner import LimitlessSiteScrapeRunner
from ptcgdb.scrapers.raw_store import is_valid_raw, read_raw

FIXTURES = Path(__file__).parent / "fixtures" / "limitless_site"

T_NALC = "518"  # NAIC 2026（international 3752 人，2026-06-10）→ accepted
T_TURIN = "540"  # Special Event Turin（special 2033 人）→ accepted
T_INDY = "559"  # Regional Indianapolis（regional 1974 人）→ accepted
T_KOREA = "561"  # Korean League Season 3 → rejected（JP/亚洲国内）
T_JCS = "555"  # Japan Championships 2026 → rejected（JP 国内）
T_SMALL = "548"  # Regional Smallville 16 人 < 32 → rejected（人数门）
T_OLD = "410"  # Regional Oldtown 2024-11-09 → 窗口外


def load_html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


INDEX_ENTRIES = parse_index_page(load_html("index_2526.html"))


# ---- get_text：与 get_json 共享限速/退避/熔断，差别只在解析 ----


def make_client(handler, **kwargs) -> HttpClient:
    kwargs.setdefault("rate_limiter", RateLimiter(interval=0))
    kwargs.setdefault("retry_wait", wait_none())
    return HttpClient(BASE_URL, transport=httpx.MockTransport(handler), **kwargs)


def test_get_text_returns_status_and_html():
    def handler(request):
        assert request.method == "GET"
        assert request.url.params["time"] == "2526"
        return httpx.Response(200, text="<html>ok</html>")

    client = make_client(handler)
    assert client.get_text("/tournaments", {"time": "2526"}) == (200, "<html>ok</html>")


def test_get_text_html_does_not_trip_non_json_circuit():
    # HTML（非 JSON）是 get_text 的正常响应，不触发"响应非 JSON"熔断
    client = make_client(lambda r: httpx.Response(200, text="<html>not json</html>"))
    status, text = client.get_text("/x")
    assert status == 200 and "not json" in text


def test_get_text_404_returned_not_raised():
    client = make_client(lambda r: httpx.Response(404, text="not found"))
    assert client.get_text("/x") == (404, "not found")


def test_get_text_circuit_open_on_403():
    client = make_client(lambda r: httpx.Response(403, text="Forbidden"))
    with pytest.raises(CircuitOpenError, match="403"):
        client.get_text("/x")


def test_get_text_retries_on_5xx():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 2:
            return httpx.Response(503, text="server busy")
        return httpx.Response(200, text="ok")

    client = make_client(handler)
    assert client.get_text("/x") == (200, "ok")
    assert calls == 2


# ---- parse_index_page ----


def test_parse_index_page_fields():
    assert len(INDEX_ENTRIES) == 7
    first = INDEX_ENTRIES[0]
    assert first == {
        "tournament_id": T_NALC,
        "name": "NAIC 2026, New Orleans",
        "date": "2026-06-10",  # data-date ISO 直取，不碰 "10 Jun 26" 文本
        "players": 3752,
        "country": "US",
        "url": "/tournaments/518",
    }
    by_id = {e["tournament_id"]: e for e in INDEX_ENTRIES}
    assert by_id[T_TURIN]["name"] == "Special Event Turin"
    assert by_id[T_JCS]["country"] == "JP"
    assert by_id[T_SMALL]["players"] == 16


def test_parse_index_page_text_date_fallback():
    # data-date 缺失时兜底 "10 Jun 26" 文本换算（两位年份 ≤50 → 20xx，>50 → 19xx）
    html = (
        '<table><tr data-country="US" data-name="Regional X" '
        'data-players="100"><td>10 Jun 26</td>'
        '<td><a href="/tournaments/700">Regional X</a></td></tr>'
        '<tr data-country="US" data-name="Regional Y" data-players="100">'
        '<td>15 Aug 97</td><td><a href="/tournaments/701">Regional Y</a></td></tr></table>'
    )
    entries = parse_index_page(html)
    assert entries[0]["date"] == "2026-06-10"
    assert entries[1]["date"] == "1997-08-15"


def test_parse_index_page_missing_fields_tolerant():
    html = (
        '<table><tr data-date="2026-06-10" data-country="US">'
        "<td>10 Jun 26</td><td>无链接无名单元</td></tr></table>"
    )
    (entry,) = parse_index_page(html)
    assert entry["date"] == "2026-06-10"
    assert entry["tournament_id"] is None and entry["url"] is None
    assert entry["name"] is None and entry["players"] is None


# ---- parse_standings_page ----


def test_parse_standings_page_fields():
    result = parse_standings_page(load_html("standings.html"))
    assert result["name"] == "NAIC 2026, New Orleans"  # <title> 去 "– Limitless" 后缀
    rows = result["standings"]
    assert len(rows) == 4
    assert rows[0] == {
        "placing": 1,
        "player": "James Kowalski",
        "country": "US",
        "archetype_name": "Lillie's Clefairy",  # data-deck HTML 实体反转义
        "deck_url": "/decks/list/28249",
        "decklist_id": "28249",
        "archetype_url": "/decks/326",
        "archetype_id": "326",
    }
    # ?variant=N 保留在 archetype_url，archetype_id 取数字部分
    assert rows[1]["archetype_url"] == "/decks/284?variant=3"
    assert rows[1]["archetype_id"] == "284"
    # 共享 decklist：第 2、3 名同表
    assert rows[2]["decklist_id"] == rows[1]["decklist_id"] == "28236"
    # 未交表选手：无链接行字段 None 保留，不猜
    assert rows[3]["decklist_id"] is None
    assert rows[3]["deck_url"] is None
    assert rows[3]["archetype_id"] is None
    assert rows[3]["placing"] == 4


# ---- parse_decklist_page ----


def test_parse_decklist_page_fields():
    result = parse_decklist_page(load_html("decklist.html"))
    # title "Lillie&#039;s Clefairy by James Kowalski – Limitless" → archetype + player
    assert result["archetype"] == "Lillie's Clefairy"
    assert result["player"] == "James Kowalski"
    cards = result["cards"]
    assert len(cards) == 4
    assert cards[0] == {
        "set": "JTG", "number": "56", "name": "Lillie's Clefairy ex",
        "count": 4, "section": "Pokémon",
    }
    assert cards[2]["name"] == "Boss's Orders"  # &#039; 实体反转义
    assert cards[2]["section"] == "Trainer"
    assert cards[3] == {
        "set": "MEE", "number": "2", "name": "Fire Energy",
        "count": 10, "section": "Energy",
    }
    assert sum(c["count"] for c in cards) == 20  # 4+4+2+10


def test_parse_decklist_page_missing_count_tolerant():
    html = (
        "<title>X Box by Some One – Limitless</title>"
        '<div class="decklist-column-heading">Pokémon (1)</div>'
        '<div class="decklist-card" data-set="TWM" data-number="25" data-lang="en">'
        '<a class="card-link" href="/cards/TWM/25">'
        '<span class="card-name">Teal Mask Ogerpon ex</span></a></div>'
    )
    result = parse_decklist_page(html)
    assert result["archetype"] == "X Box" and result["player"] == "Some One"
    (card,) = result["cards"]
    assert card["count"] is None  # 缺 card-count span → None，不猜
    assert card["name"] == "Teal Mask Ogerpon ex"
    assert card["section"] == "Pokémon"


def test_parse_decklist_page_title_without_by():
    result = parse_decklist_page("<title>Lone Archetype – Limitless</title>")
    assert result["archetype"] == "Lone Archetype"
    assert result["player"] is None


# ---- classify_site_tournament 矩阵（主站名称形态）----


def test_classify_official_tiers_site_names():
    assert classify_site_tournament("NAIC 2026, New Orleans", 3752)[0] == "international"
    assert classify_site_tournament("EUIC 2026, London", 4010)[0] == "international"
    assert classify_site_tournament("LAIC 2025–26, São Paulo", 2117)[0] == "international"
    assert classify_site_tournament("OCIC 2026", 1500)[0] == "international"
    assert classify_site_tournament("Regional Indianapolis, IN", 1974)[0] == "regional"
    assert classify_site_tournament("Special Event Turin", 2033)[0] == "special"
    assert classify_site_tournament("Toronto League Cup", 48)[0] == "league_cup"


def test_classify_case_insensitive_site():
    assert classify_site_tournament("naic 2026", 100)[0] == "international"
    assert classify_site_tournament("SPECIAL EVENT LIMA", 100)[0] == "special"


def test_classify_rejects_jp_domestic():
    for name in (
        "Japan Championships 2026",
        "Champions League Tokyo",
        "Korean League Season 3",
        "Indonesia Premier Ball League",
    ):
        tier, reason = classify_site_tournament(name, 1000)
        assert tier is None
        assert "JP/亚洲国内赛事" in reason


def test_classify_players_gate_site():
    assert classify_site_tournament("Regional X", 31)[0] is None
    assert classify_site_tournament("Regional X", 32)[0] == "regional"
    assert classify_site_tournament("Regional X", None)[0] is None


def test_classify_rejects_unknown_name_site():
    tier, reason = classify_site_tournament("Professor Oak Casual Meetup", 120)
    assert tier is None
    assert "未命中官方系列赛" in reason


# ---- 赛季标签 ----


def test_season_of_date():
    assert season_of_date(date(2025, 4, 11)) == "2425"  # 4 月 → 上赛季
    assert season_of_date(date(2025, 8, 1)) == "2526"  # 8 月起新赛季
    assert season_of_date(date(2026, 4, 9)) == "2526"
    assert season_of_date(date(2026, 7, 31)) == "2526"


def test_seasons_for_window():
    assert seasons_for_window(date(2025, 4, 11), date(2026, 4, 9)) == ["2425", "2526"]
    assert seasons_for_window(date(2026, 1, 1), date(2026, 4, 9)) == ["2526"]


# ---- LimitlessSiteScraper：HTTP 200 校验 + id 强校验 ----


def test_scraper_non_200_raises():
    scraper = LimitlessSiteScraper(make_client(lambda r: httpx.Response(404, text="nf")))
    with pytest.raises(LimitlessSiteApiError):
        scraper.fetch_standings("518")


def test_scraper_id_must_be_numeric():
    scraper = LimitlessSiteScraper(make_client(lambda r: httpx.Response(200, text="")))
    for bad in ("abc", "518x", 518, None, "aaaaaaaaaaaaaaaaaaaaaaa1"):
        with pytest.raises(TypeError):
            scraper.fetch_standings(bad)
        with pytest.raises(TypeError):
            scraper.fetch_decklist(bad)


def test_scraper_fetch_parses_pages():
    def handler(request):
        if request.url.path == "/tournaments":
            assert request.url.params["format"] == "standard"
            assert request.url.params["show"] == str(INDEX_PAGE_SIZE)
            assert "page" not in request.url.params  # 第 1 页不带 page 参数
            return httpx.Response(200, text=load_html("index_2526.html"))
        if request.url.path == f"/tournaments/{T_NALC}":
            return httpx.Response(200, text=load_html("standings.html"))
        if request.url.path == "/decks/list/28249":
            return httpx.Response(200, text=load_html("decklist.html"))
        return httpx.Response(404, text="nf")

    scraper = LimitlessSiteScraper(make_client(handler))
    assert len(scraper.fetch_index_page("2526")) == 7
    standings = scraper.fetch_standings(T_NALC)
    assert standings["tournament_id"] == T_NALC
    assert len(standings["standings"]) == 4
    decklist = scraper.fetch_decklist("28249")
    assert decklist["decklist_id"] == "28249"
    assert decklist["archetype"] == "Lillie's Clefairy"


# ---- runner：假 scraper（鸭子类型，无 HTTP）----


class FakeSiteScraper:
    """fixtures 背书的假 scraper；fail_on/circuit_on 注入故障。

    index_pages: {season: {page: [entry...]}}；standings/decklist 默认用 fixtures。
    """

    def __init__(self, index_pages=None, fail_on=(), circuit_on=()):
        self.index_pages = index_pages if index_pages is not None else {"2526": {1: INDEX_ENTRIES}}
        self.fail_on = set(fail_on)
        self.circuit_on = set(circuit_on)
        self.calls = []

    def _maybe_fail(self, kind, endpoint):
        if kind in self.circuit_on:
            raise CircuitOpenError("HTTP 403")
        if kind in self.fail_on:
            raise LimitlessSiteApiError(endpoint, 404, "HTTP 非 200")

    def fetch_index_page(self, season, page=1):
        self.calls.append(("index", season, page))
        self._maybe_fail("index", "/tournaments")
        return self.index_pages.get(season, {}).get(page, [])

    def fetch_standings(self, tournament_id):
        self.calls.append(("standings", tournament_id))
        self._maybe_fail("standings", f"/tournaments/{tournament_id}")
        result = parse_standings_page(load_html("standings.html"))
        result["tournament_id"] = tournament_id
        return result

    def fetch_decklist(self, decklist_id):
        self.calls.append(("decklist", decklist_id))
        self._maybe_fail("decklist", f"/decks/list/{decklist_id}")
        result = parse_decklist_page(load_html("decklist.html"))
        result["decklist_id"] = decklist_id
        return result


def make_runner(tmp_path, scraper):
    return LimitlessSiteScrapeRunner(tmp_path / "raw", scraper, tmp_path / "test.db")


def decisions(result):
    """stats.scraped 中的取舍决策条目（action=accepted/rejected）。"""
    return [r for r in result.stats.scraped if r["action"] in ("accepted", "rejected")]


def test_scrape_full_flow(tmp_path):
    scraper = FakeSiteScraper()
    result = make_runner(tmp_path, scraper).scrape()
    raw = tmp_path / "raw"

    # 默认窗口 = EN 对齐窗口（2025-04-11 ~ 2026-04-09）……fixture 日期都在 2026-04~06，
    # 超出默认窗口右端！用显式窗口罩住 fixture（见 test_explicit_window）——
    # 这里默认窗口下 7 场全部窗口外，total=0。
    assert result.stats.total == 0
    assert decisions(result) == []

    # 显式窗口罩住 fixture 日期
    scraper2 = FakeSiteScraper()
    result2 = make_runner(tmp_path, scraper2).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    assert result2.stats.total == 3  # NAIC / Turin / Indianapolis
    by_id = {r["id"]: r for r in decisions(result2)}
    assert set(by_id) == {T_NALC, T_TURIN, T_INDY, T_KOREA, T_JCS, T_SMALL}  # T_OLD 窗口外
    assert by_id[T_NALC]["action"] == "accepted" and by_id[T_NALC]["tier"] == "international"
    assert by_id[T_TURIN]["action"] == "accepted" and by_id[T_TURIN]["tier"] == "special"
    assert by_id[T_INDY]["action"] == "accepted" and by_id[T_INDY]["tier"] == "regional"
    assert by_id[T_KOREA]["action"] == "rejected" and "JP/亚洲国内赛事" in by_id[T_KOREA]["reason"]
    assert by_id[T_JCS]["action"] == "rejected" and "JP/亚洲国内赛事" in by_id[T_JCS]["reason"]
    assert by_id[T_SMALL]["action"] == "rejected" and "人数" in by_id[T_SMALL]["reason"]
    assert all({"name", "tier", "reason", "players", "date"} <= set(r) for r in by_id.values())

    # 落盘：索引页 + 3 场 accepted standings + 去重后 2 个 decklist（28236 共享只抓一次）
    assert is_valid_raw(index_path(raw, "2526", 1))
    for tid in (T_NALC, T_TURIN, T_INDY):
        assert is_valid_raw(standings_path(raw, tid))
    for tid in (T_KOREA, T_JCS, T_SMALL, T_OLD):
        assert not standings_path(raw, tid).exists()
    assert is_valid_raw(decklist_path(raw, "28249"))
    assert is_valid_raw(decklist_path(raw, "28236"))

    # raw 内容 = 解析后 JSON 快照（standings 带 tournament_id；decklist 带 cards/section）
    doc = read_raw(standings_path(raw, T_NALC))
    assert doc["tournament_id"] == T_NALC
    assert doc["standings"][0]["decklist_id"] == "28249"
    deck = read_raw(decklist_path(raw, "28249"))
    assert deck["cards"][0]["section"] == "Pokémon"
    assert deck["_meta"]["source"] == "limitless_site"

    # decklist 抓取去重：首场抓 2 个，后两场文件已存在零请求
    deck_calls = [c for c in scraper2.calls if c[0] == "decklist"]
    assert sorted(c[1] for c in deck_calls) == ["28236", "28249"]

    assert not result2.stats.aborted
    assert result2.stats.question == []
    assert result2.stats.missing == []

    # 三清单 + scrape_runs 行
    for name in ("scraped", "question", "missing"):
        assert (result2.lists_path / f"{name}.json").is_file()
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result2.run_id)
        assert row is not None
        assert row.status == "ok"
        assert row.card_count == 3
    engine.dispose()


def test_default_seasons_cover_window(tmp_path):
    # seasons 缺省 = 覆盖窗口的赛季列表：默认对齐窗口 → 2425 + 2526 各抓一页索引
    scraper = FakeSiteScraper()
    make_runner(tmp_path, scraper).scrape()
    index_calls = [c for c in scraper.calls if c[0] == "index"]
    assert ("index", "2425", 1) in index_calls
    assert ("index", "2526", 1) in index_calls


def test_explicit_seasons_limit_index_fetch(tmp_path):
    scraper = FakeSiteScraper()
    make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    index_calls = [c for c in scraper.calls if c[0] == "index"]
    assert index_calls == [("index", "2526", 1)]  # 42 行 < 100 → 不翻页


def test_pagination_full_page_then_stop(tmp_path):
    # 第 1 页恰好 100 行（= show 上限，可能截断）→ 试第 2 页；第 2 页未满 → 停
    filler = [
        {"tournament_id": f"9{i:03}", "name": "Unknown Meetup", "date": "2026-05-01",
         "players": 10, "country": "US", "url": f"/tournaments/9{i:03}"}
        for i in range(INDEX_PAGE_SIZE)
    ]
    pages = {"2526": {1: filler, 2: INDEX_ENTRIES[:1]}}  # 第 2 页只有 NAIC
    scraper = FakeSiteScraper(index_pages=pages)
    result = make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    index_calls = [c for c in scraper.calls if c[0] == "index"]
    assert ("index", "2526", 2) in index_calls
    assert ("index", "2526", 3) not in index_calls  # 第 2 页未满 → 停
    assert result.stats.total == 1  # NAIC


def test_pagination_no_new_ids_stops(tmp_path):
    # page 参数被忽略返回重复页：第 2 页与第 1 页同 id → 无新 id 即停（兜底）
    pages = {"2526": {1: INDEX_ENTRIES, 2: INDEX_ENTRIES}}
    # 把第 1 页伪装成满页（复制到 100 条，id 相同不影响——满页判据是行数）
    full_page = INDEX_ENTRIES * (INDEX_PAGE_SIZE // len(INDEX_ENTRIES) + 1)
    pages["2526"][1] = full_page[:INDEX_PAGE_SIZE]
    pages["2526"][2] = full_page[:INDEX_PAGE_SIZE]  # 与第 1 页完全相同
    scraper = FakeSiteScraper(index_pages=pages)
    make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    index_calls = [c for c in scraper.calls if c[0] == "index"]
    assert ("index", "2526", 2) in index_calls
    assert ("index", "2526", 3) not in index_calls  # 无新 id → 停


def test_resume_skips_existing_files(tmp_path):
    scraper = FakeSiteScraper()
    runner = make_runner(tmp_path, scraper)
    runner.scrape(date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"])
    call_count = len(scraper.calls)

    result = runner.scrape(date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"])
    assert len(scraper.calls) == call_count  # 零新请求（索引与详情全部断点跳过）
    fetch_actions = {r["action"] for r in result.stats.scraped}
    assert fetch_actions <= {"skipped", "accepted", "rejected"}
    assert result.stats.missing == []


def test_circuit_abort_marks_run_aborted(tmp_path):
    scraper = FakeSiteScraper(circuit_on={"standings"})
    result = make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    assert result.stats.aborted is True

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row.status == "aborted"
    engine.dispose()


def test_api_error_question_and_missing(tmp_path):
    scraper = FakeSiteScraper(fail_on={"decklist"})
    result = make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    # 3 场 accepted 的 decklist 全部失败进 question（每场 2 个去重 id，raw 未落 → 每场都试）
    assert len(result.stats.question) == 6
    assert all("decks/list" in q["id"] for q in result.stats.question)
    # 对账：decklist raw 缺失进 missing（去重后 2 个）；standings 正常
    assert len(result.stats.missing) == 2
    assert is_valid_raw(standings_path(tmp_path / "raw", T_NALC))
    assert not result.stats.aborted


def test_max_tournaments_truncates(tmp_path):
    scraper = FakeSiteScraper()
    result = make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01",
        seasons=["2526"], max_tournaments=1,
    )
    assert result.stats.total == 1
    assert is_valid_raw(standings_path(tmp_path / "raw", T_NALC))
    assert not standings_path(tmp_path / "raw", T_TURIN).exists()
    assert [r["id"] for r in decisions(result)] == [T_NALC]


def test_malformed_index_entry_goes_question(tmp_path):
    bad = [{"tournament_id": None, "name": "No Link Cup", "date": "2026-05-01",
            "players": 100, "country": "US", "url": None}]
    scraper = FakeSiteScraper(index_pages={"2526": {1: bad}})
    result = make_runner(tmp_path, scraper).scrape(
        date_from="2026-04-01", date_to="2026-07-01", seasons=["2526"]
    )
    assert len(result.stats.question) == 1
    assert "缺 tournament_id/date" in result.stats.question[0]["reason"]


# ---- CLI：ptcgdb scrape limitless-site ----


def _patch_cli(monkeypatch, fake):
    class DummyHttp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(cli, "HttpClient", DummyHttp)
    monkeypatch.setattr(cli, "LimitlessSiteScraper", lambda http: fake)


def test_cli_scrape_limitless_site(tmp_path, monkeypatch):
    _patch_cli(monkeypatch, FakeSiteScraper())
    result = CliRunner().invoke(
        cli.app,
        [
            "scrape", "limitless-site",
            "--date-from", "2026-04-01", "--date-to", "2026-07-01",
            "--seasons", "2526",
            "--raw-dir", str(tmp_path / "raw"),
            "--db-path", str(tmp_path / "test.db"),
        ],
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
    assert "accepted=3" in result.output
    assert "rejected=3" in result.output
    assert is_valid_raw(standings_path(tmp_path / "raw", T_NALC))
    assert is_valid_raw(decklist_path(tmp_path / "raw", "28249"))


def test_cli_scrape_limitless_site_bad_date_exit_2(tmp_path, monkeypatch):
    _patch_cli(monkeypatch, FakeSiteScraper())
    result = CliRunner().invoke(
        cli.app,
        [
            "scrape", "limitless-site",
            "--date-from", "not-a-date",
            "--raw-dir", str(tmp_path / "raw"),
            "--db-path", str(tmp_path / "test.db"),
        ],
    )
    assert result.exit_code == 2
    assert "日期格式错误" in result.output

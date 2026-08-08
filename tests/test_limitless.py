"""task 028 测试：Limitless EN 赛事采集层（get_json / 归类 / 对齐窗口 / runner / CLI）。

全部零网络：get_json 用 httpx MockTransport，runner 用 fixtures 背书的假 scraper
（鸭子类型，无 HTTP）。fixtures 为手写小样本（照 2026-08-07 实测响应形态）：
tournaments_page = 5 场赛事（regional 850 人 / league_cup 48 人 / 非官方 120 人 /
regional 12 人 / 窗口外 2024 旧 regional）；standings 2 条（含 deck/decklist）；
pairings 3 条（含平局 winner=""）。覆盖：
- get_json：限速/退避/熔断语义与 post_json 一致；
- LimitlessScraper：裸数组校验（非 list → LimitlessApiError）、tournament_id 强校验；
- classify_tournament 矩阵：四种官方 tier、大小写、<32 人拒、非官方名拒；
- alignment_window 对当前种子 = (2025-04-11, 2026-04-09)；
- runner：窗口过滤 / 分页终止 / accepted 抓详情 / rejected 只记录 / 断点续传 /
  熔断 aborted / missing 对账 / 取舍决策全部落 stats；
- CLI 冒烟：scrape limitless。
"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tenacity import wait_none
from typer.testing import CliRunner

from ptcgdb import cli
from ptcgdb.normalize.envs import alignment_window
from ptcgdb.orm import ScrapeRun
from ptcgdb.scrapers import CircuitOpenError, HttpClient, RateLimiter, TransientHttpError
from ptcgdb.scrapers.limitless import (
    BASE_URL,
    ENDPOINT_TOURNAMENTS,
    MIN_PLAYERS,
    LimitlessApiError,
    LimitlessScraper,
    classify_tournament,
    pairings_path,
    standings_path,
    tournament_list_path,
)
from ptcgdb.scrapers.limitless_runner import LimitlessScrapeRunner
from ptcgdb.scrapers.raw_store import is_valid_raw, read_raw

FIXTURES = Path(__file__).parent / "fixtures" / "limitless"

T1 = "aaaaaaaaaaaaaaaaaaaaaaa1"  # regional 850 人，2026-03-15，窗口内 → accepted
T2 = "aaaaaaaaaaaaaaaaaaaaaaa2"  # league_cup 48 人，2025-11-02，窗口内 → accepted
T3 = "aaaaaaaaaaaaaaaaaaaaaaa3"  # 非官方名 120 人 → rejected
T4 = "aaaaaaaaaaaaaaaaaaaaaaa4"  # regional 12 人 < 32 → rejected
T5 = "aaaaaaaaaaaaaaaaaaaaaaa5"  # regional 500 人，2024-06-01 → 窗口外（早于收集起点）


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---- get_json：与 post_json 对称的限速/退避/熔断语义 ----


def make_client(handler, **kwargs) -> HttpClient:
    kwargs.setdefault("rate_limiter", RateLimiter(interval=0))
    kwargs.setdefault("retry_wait", wait_none())
    return HttpClient(BASE_URL, transport=httpx.MockTransport(handler), **kwargs)


def test_get_json_basic_with_params():
    def handler(request):
        assert request.method == "GET"
        params = request.url.params
        assert params["game"] == "PTCG"
        assert params["format"] == "STANDARD"
        assert params["page"] == "1"
        return httpx.Response(200, json=[{"id": "x"}])

    client = make_client(handler)
    body = client.get_json("/api/tournaments", {"game": "PTCG", "format": "STANDARD", "page": 1})
    assert body == [{"id": "x"}]


def test_get_json_retry_succeeds_after_transient_failures():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, text="server busy")
        return httpx.Response(200, json=[])

    client = make_client(handler)
    assert client.get_json("/x") == []
    assert calls == 3


def test_get_json_retry_gives_up_after_max_attempts():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    client = make_client(handler)
    with pytest.raises(TransientHttpError):
        client.get_json("/x")
    assert calls == 3  # 最多重试 3 次后放弃


def test_get_json_circuit_open_on_403():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="Forbidden")

    client = make_client(handler)
    with pytest.raises(CircuitOpenError, match="403"):
        client.get_json("/x")
    assert calls == 1  # 403 不重试，立即熔断


def test_get_json_circuit_open_on_non_json():
    def handler(request):
        return httpx.Response(200, text="<html>Please verify you are human</html>")

    client = make_client(handler)
    with pytest.raises(CircuitOpenError, match="非 JSON"):
        client.get_json("/x")


def test_get_json_circuit_open_after_five_consecutive_failures():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler, max_attempts=1)
    for _ in range(5):
        with pytest.raises(TransientHttpError):
            client.get_json("/x")
    assert calls == 5
    with pytest.raises(CircuitOpenError, match="连续 5 次"):
        client.get_json("/x")
    assert calls == 5  # 熔断后不再发出请求


def test_get_json_pacing_uses_limiter():
    now = [100.0]
    sleeps = []

    def fake_sleep(d):
        sleeps.append(d)
        now[0] += d

    limiter = RateLimiter(
        interval=6.5, clock=lambda: now[0], sleep=fake_sleep
    )

    def handler(request):
        return httpx.Response(200, json=[])

    client = make_client(handler, rate_limiter=limiter)
    client.get_json("/x")  # 首次不限速
    client.get_json("/x")
    assert sleeps == [6.5]  # 第二次补满 6.5s 间隔（Limitless 50req/5min 保险值）


# ---- LimitlessScraper：裸数组校验 + id 强校验 ----


def test_scraper_accepts_bare_list_including_empty():
    scraper = LimitlessScraper(make_client(lambda r: httpx.Response(200, json=[])))
    assert scraper.fetch_tournaments_page(99) == []  # 空 list 合法（翻页到头）


def test_scraper_rejects_non_list_body():
    def handler(request):
        return httpx.Response(200, json={"error": "not found"})

    scraper = LimitlessScraper(make_client(handler))
    with pytest.raises(LimitlessApiError):
        scraper.fetch_standings(T1)


def test_tournament_id_must_be_24_hex():
    scraper = LimitlessScraper(make_client(lambda r: httpx.Response(200, json=[])))
    for bad in (T1[:-1], "z" * 24, 123, None):
        with pytest.raises(TypeError):
            scraper.fetch_standings(bad)


# ---- classify_tournament 矩阵 ----


def test_classify_official_tiers():
    assert classify_tournament("Charlotte Regional Championship", 850)[0] == "regional"
    assert classify_tournament("EUIC International Championship", 2000)[0] == "international"
    assert classify_tournament("Toronto Special Event", 200)[0] == "special"
    assert classify_tournament("Toronto League Cup", 48)[0] == "league_cup"


def test_classify_case_insensitive():
    assert classify_tournament("charlotte regional championship", 850)[0] == "regional"
    assert classify_tournament("LEAGUE CUP", 32)[0] == "league_cup"


def test_classify_players_gate():
    # 人数门（FR-9.1a）：< 32 不收；32 边界收；缺人数不收
    assert classify_tournament("Regional Championship", MIN_PLAYERS - 1)[0] is None
    assert classify_tournament("Regional Championship", MIN_PLAYERS)[0] == "regional"
    assert classify_tournament("Regional Championship", None)[0] is None


def test_classify_rejects_non_official_name():
    tier, reason = classify_tournament("Professor Oak Casual Meetup", 120)
    assert tier is None
    assert "未命中官方系列赛" in reason


# ---- alignment_window ----


def test_alignment_window_current_seed():
    # 种子真值：CN 当前段 G/H/I → EN G/H/I 段 (2025-04-11, 2026-04-09)
    assert alignment_window() == (date(2025, 4, 11), date(2026, 4, 9))


def test_alignment_window_custom_calendar():
    calendar = {
        "cn": {"segments": [{"effective_from": "2026-01-01", "allowed_marks": ["X", "Y"]}]},
        "en": {
            "segments": [
                {  # 同标记有界段
                    "effective_from": "2025-01-01",
                    "effective_to": "2025-12-31",
                    "allowed_marks": ["X", "Y"],
                },
                {  # 同标记无界段（effective_to 缺失视为 +∞，右端取有界段最大值）
                    "effective_from": "2026-01-01",
                    "allowed_marks": ["X", "Y"],
                },
                {  # 不同标记：不计入窗口
                    "effective_from": "2024-01-01",
                    "effective_to": "2024-12-31",
                    "allowed_marks": ["W"],
                },
            ]
        },
    }
    assert alignment_window(calendar) == (date(2025, 1, 1), date(2025, 12, 31))


def test_alignment_window_no_matching_segment_raises():
    calendar = {
        "cn": {"segments": [{"effective_from": "2026-01-01", "allowed_marks": ["X"]}]},
        "en": {"segments": [{"effective_from": "2025-01-01", "allowed_marks": ["W"]}]},
    }
    with pytest.raises(ValueError, match="同标记"):
        alignment_window(calendar)


# ---- runner：假 scraper（鸭子类型，无 HTTP）----


class FakeLimitlessScraper:
    """fixtures 背书的假 scraper；fail_on/circuit_on 注入故障。"""

    def __init__(self, pages=None, fail_on=(), circuit_on=()):
        self.pages = pages if pages is not None else {1: load_fixture("tournaments_page.json")}
        self.fail_on = set(fail_on)
        self.circuit_on = set(circuit_on)
        self.calls = []

    def _maybe_fail(self, kind, endpoint):
        if kind in self.circuit_on:
            raise CircuitOpenError("HTTP 403")
        if kind in self.fail_on:
            raise LimitlessApiError(endpoint, 200, "响应体不是数组: dict")

    def fetch_tournaments_page(self, page, limit=100):
        self.calls.append(("list", page))
        self._maybe_fail("list", ENDPOINT_TOURNAMENTS)
        return self.pages.get(page, [])

    def fetch_standings(self, tournament_id):
        self.calls.append(("standings", tournament_id))
        self._maybe_fail("standings", f"/api/tournaments/{tournament_id}/standings")
        return load_fixture("standings.json")

    def fetch_pairings(self, tournament_id):
        self.calls.append(("pairings", tournament_id))
        self._maybe_fail("pairings", f"/api/tournaments/{tournament_id}/pairings")
        return load_fixture("pairings.json")


def make_runner(tmp_path, scraper):
    return LimitlessScrapeRunner(tmp_path / "raw", scraper, tmp_path / "test.db")


def decisions(result):
    """stats.scraped 中的取舍决策条目（action=accepted/rejected）。"""
    return [r for r in result.stats.scraped if r["action"] in ("accepted", "rejected")]


def test_scrape_full_flow(tmp_path):
    scraper = FakeLimitlessScraper()
    result = make_runner(tmp_path, scraper).scrape()
    raw = tmp_path / "raw"

    # 默认窗口 = EN 对齐窗口（2025-04-11 ~ 2026-04-09）
    assert result.stats.total == 2  # accepted 场数（T1 regional / T2 league_cup）
    by_id = {r["id"]: r for r in decisions(result)}
    assert set(by_id) == {T1, T2, T3, T4}  # 窗口外 T5 不记取舍细节
    assert by_id[T1]["action"] == "accepted" and by_id[T1]["tier"] == "regional"
    assert by_id[T2]["action"] == "accepted" and by_id[T2]["tier"] == "league_cup"
    assert by_id[T3]["action"] == "rejected" and "未命中官方系列赛" in by_id[T3]["reason"]
    assert by_id[T4]["action"] == "rejected" and "人数" in by_id[T4]["reason"]
    assert all({"name", "tier", "reason", "players", "date"} <= set(r) for r in by_id.values())

    # 落盘：清单页 + accepted 两场的 standings/pairings；rejected/窗口外不抓详情
    assert is_valid_raw(tournament_list_path(raw, 1))
    for tid in (T1, T2):
        assert is_valid_raw(standings_path(raw, tid))
        assert is_valid_raw(pairings_path(raw, tid))
    for tid in (T3, T4, T5):
        assert not standings_path(raw, tid).exists()
        assert not pairings_path(raw, tid).exists()

    # raw 内容 = 裸数组包装 {"data": [...]}，卡条目为 PTCGO set+number+英文名
    doc = read_raw(standings_path(raw, T1))
    card = doc["data"][0]["decklist"]["pokemon"][0]
    assert card == {"count": 3, "set": "SCR", "number": "57", "name": "Slowpoke"}
    pairings = read_raw(pairings_path(raw, T1))["data"]
    assert pairings[1]["winner"] == ""  # 平局空串原样落盘（容错在解析层）

    # 分页终止：页内最旧赛事（T5 2024-06-01）早于窗口 → 本页处理完即停，不抓第 2 页
    assert ("list", 1) in scraper.calls
    assert ("list", 2) not in scraper.calls
    assert ("standings", T3) not in scraper.calls

    assert not result.stats.aborted
    assert result.stats.question == []
    assert result.stats.missing == []

    # 三清单 + scrape_runs 行
    for name in ("scraped", "question", "missing"):
        assert (result.lists_path / f"{name}.json").is_file()
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row is not None
        assert row.status == "ok"
        assert row.card_count == 2
    engine.dispose()


def test_pagination_empty_page_stops(tmp_path):
    pages = {1: load_fixture("tournaments_page.json")[:1], 2: []}  # 只有 T1（窗口内）
    scraper = FakeLimitlessScraper(pages=pages)
    make_runner(tmp_path, scraper).scrape()
    assert ("list", 2) in scraper.calls  # 空页 → 停
    assert ("list", 3) not in scraper.calls


def test_pagination_continues_while_in_window(tmp_path):
    entries = load_fixture("tournaments_page.json")
    pages = {1: entries[:1], 2: entries[1:2], 3: []}  # T1、T2 分页，均窗口内
    scraper = FakeLimitlessScraper(pages=pages)
    result = make_runner(tmp_path, scraper).scrape()
    assert ("list", 1) in scraper.calls
    assert ("list", 2) in scraper.calls  # 页内最旧仍在窗口内 → 继续翻页
    assert ("list", 3) in scraper.calls
    assert ("list", 4) not in scraper.calls
    assert result.stats.total == 2


def test_explicit_window_overrides_default(tmp_path):
    scraper = FakeLimitlessScraper()
    result = make_runner(tmp_path, scraper).scrape(
        date_from="2026-01-01", date_to="2026-04-09"
    )
    by_id = {r["id"]: r for r in decisions(result)}
    assert set(by_id) == {T1}  # T2~T4 落在显式窗口外，只计数不记细节
    assert result.stats.total == 1
    assert is_valid_raw(standings_path(tmp_path / "raw", T1))
    assert not standings_path(tmp_path / "raw", T2).exists()


def test_resume_skips_existing_files(tmp_path):
    scraper = FakeLimitlessScraper()
    runner = make_runner(tmp_path, scraper)
    runner.scrape()
    call_count = len(scraper.calls)

    result = runner.scrape()
    assert len(scraper.calls) == call_count  # 零新请求（清单页与详情全部断点跳过）
    fetch_actions = {r["action"] for r in result.stats.scraped}
    assert fetch_actions <= {"skipped", "accepted", "rejected"}
    assert result.stats.missing == []


def test_circuit_abort_marks_run_aborted(tmp_path):
    scraper = FakeLimitlessScraper(circuit_on={"standings"})
    result = make_runner(tmp_path, scraper).scrape()
    assert result.stats.aborted is True

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row.status == "aborted"
    engine.dispose()


def test_api_error_question_and_missing(tmp_path):
    scraper = FakeLimitlessScraper(fail_on={"pairings"})
    result = make_runner(tmp_path, scraper).scrape()
    # 两场 accepted 的 pairings 全部失败进 question
    assert len(result.stats.question) == 2
    assert all("pairings" in q["id"] for q in result.stats.question)
    # 对账：pairings raw 缺失进 missing；standings 正常
    assert len(result.stats.missing) == 2
    assert is_valid_raw(standings_path(tmp_path / "raw", T1))
    assert not result.stats.aborted


def test_max_tournaments_truncates(tmp_path):
    scraper = FakeLimitlessScraper()
    result = make_runner(tmp_path, scraper).scrape(max_tournaments=1)
    assert result.stats.total == 1
    assert is_valid_raw(standings_path(tmp_path / "raw", T1))
    assert not standings_path(tmp_path / "raw", T2).exists()
    assert [r["id"] for r in decisions(result)] == [T1]


def test_malformed_list_entry_goes_question(tmp_path):
    pages = {1: [{"name": "No ID Cup", "date": "2025-11-02T18:00:00.000Z", "players": 48}]}
    scraper = FakeLimitlessScraper(pages=pages)
    result = make_runner(tmp_path, scraper).scrape()
    assert len(result.stats.question) == 1
    assert "缺 id/date" in result.stats.question[0]["reason"]


# ---- CLI：ptcgdb scrape limitless ----


def test_cli_scrape_limitless(tmp_path, monkeypatch):
    fake = FakeLimitlessScraper()

    class DummyHttp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(cli, "HttpClient", DummyHttp)
    monkeypatch.setattr(cli, "LimitlessScraper", lambda http: fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "scrape", "limitless",
            "--raw-dir", str(tmp_path / "raw"),
            "--db-path", str(tmp_path / "test.db"),
        ],
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
    assert "accepted=2" in result.output
    assert "rejected=2" in result.output
    assert is_valid_raw(standings_path(tmp_path / "raw", T1))


def test_cli_scrape_limitless_bad_date_exit_2(tmp_path, monkeypatch):
    fake = FakeLimitlessScraper()

    class DummyHttp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(cli, "HttpClient", DummyHttp)
    monkeypatch.setattr(cli, "LimitlessScraper", lambda http: fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "scrape", "limitless",
            "--date-from", "not-a-date",
            "--raw-dir", str(tmp_path / "raw"),
            "--db-path", str(tmp_path / "test.db"),
        ],
    )
    assert result.exit_code == 2
    assert "日期格式错误" in result.output

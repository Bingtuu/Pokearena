"""task 027：赛事采集 runner 测试（series-list → list → detail/rank → deck 链路）。

fixture 背书的假 scraper（鸭子类型，无 HTTP），零网络。fixtures 为 2026-08-02
真实 API 探测响应（nickname 已脱敏）：series 54/55/56；list-54 = 西安超级赛 4 场
（3215 预赛/3211 正赛/3216 少年/3210 儿童）；rank fixture 32 条排名、32 个 distinct
deckId（610080 为首）。覆盖：
- 全链路落盘路径、三清单 + scrape_runs；断点续传（二跑全 skipped、零新请求）；
- MikMoeApiError → question + missing 对账；MikMoeNotReadyError（进行中赛事
  code=400）→ 优雅跳过不抓卡组、不中止；CircuitOpenError → aborted；
- --series-id 过滤 / --max-tournaments 截断 / --top-n 页大小透传。
"""

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.orm import ScrapeRun
from ptcgdb.scrapers import MikMoeApiError
from ptcgdb.scrapers.http import CircuitOpenError
from ptcgdb.scrapers.mikmoe_tournament import (
    MikMoeNotReadyError,
    deck_detail_path,
    deck_static_path,
    rank_individual_path,
    series_list_path,
    tournament_detail_path,
    tournament_list_path,
)
from ptcgdb.scrapers.raw_store import is_valid_raw
from ptcgdb.scrapers.tournament_runner import TournamentScrapeRunner

FIXTURES = Path(__file__).parent / "fixtures" / "tournaments"

# 真实 fixture 的常量（list-54 = 西安超级赛 4 场；rank fixture 32 个 distinct deckId）
TOURNAMENT_IDS = (3215, 3211, 3216, 3210)
DECK_IDS_COUNT = 32
FIRST_DECK_ID = 610080


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeTournamentScraper:
    """fixture 背书的假赛事采集器；fail_on 抛 MikMoeApiError，not_ready_on 抛
    MikMoeNotReadyError（可预期空结果）。"""

    def __init__(self, fail_on=(), not_ready_on=()):
        self.calls = []
        self.fail_on = set(fail_on)
        self.not_ready_on = set(not_ready_on)

    def _maybe_fail(self, key, endpoint):
        if key in self.not_ready_on:
            raise MikMoeNotReadyError(endpoint, 400, "赛事未结束")
        if key in self.fail_on:
            raise MikMoeApiError(endpoint, 10002, "内部错误")

    def fetch_series_list(self, page=1, page_size=100):
        self.calls.append(("series-list", page))
        self._maybe_fail("series-list", "/api/v3/tournament/series-list")
        return load_fixture("series_list.json")

    def fetch_tournament_list(self, series_id, page=1, page_size=100):
        self.calls.append(("list", series_id, page))
        self._maybe_fail("list", "/api/v3/tournament/list")
        return load_fixture("tournament_list.json")

    def fetch_tournament_detail(self, tournament_id):
        self.calls.append(("detail", tournament_id))
        self._maybe_fail("detail", "/api/v3/tournament/detail")
        return {
            "code": 200,
            "data": {
                "id": int(tournament_id),
                "regulation": "Standard",
                "regulationMark": "FGH",
                "formatEnd": "CSV9C",
            },
            "msg": "",
        }

    def fetch_rank_individual(self, tournament_id, page=1, page_size=64):
        self.calls.append(("rank", tournament_id, page, page_size))
        self._maybe_fail("rank", "/api/v3/tournament/rank-individual")
        return load_fixture("rank_individual.json")

    def fetch_deck_detail(self, deck_id):
        self.calls.append(("deck", deck_id))
        self._maybe_fail("deck", "/api/v3/deck/detail")
        return load_fixture("deck_detail.json")

    def fetch_deck_static_by_tour(self, tournament_id):
        self.calls.append(("static", tournament_id))
        self._maybe_fail("static", "/api/v3/deck/deck-static-by-tour")
        return load_fixture("deck_static_by_tour.json")


def make_runner(tmp_path, scraper):
    return TournamentScrapeRunner(tmp_path / "raw", scraper, tmp_path / "test.db")


def actions(result):
    return {r["id"]: r["action"] for r in result.stats.scraped}


# ---- 全链路 ----


def test_scrape_full_flow(tmp_path):
    scraper = FakeTournamentScraper()
    result = make_runner(tmp_path, scraper).scrape(series_id="54")
    raw = tmp_path / "raw"

    # 落盘路径（采集器路径约定）
    assert is_valid_raw(series_list_path(raw, 1))
    assert is_valid_raw(tournament_list_path(raw, "54", 1))
    for tid in TOURNAMENT_IDS:
        assert is_valid_raw(tournament_detail_path(raw, str(tid)))
        assert is_valid_raw(rank_individual_path(raw, str(tid), 1))
        assert is_valid_raw(deck_static_path(raw, str(tid)))
    assert is_valid_raw(deck_detail_path(raw, str(FIRST_DECK_ID)))

    # 只处理系列 54（id 以 int 透传给采集器）；rank 只拉第 1 页、默认 64/页
    assert ("list", 54, 1) in scraper.calls
    assert ("list", 55, 1) not in scraper.calls
    assert ("rank", 3215, 1, 64) in scraper.calls
    assert not result.stats.aborted
    assert result.stats.question == []
    assert result.stats.missing == []
    # 卡组跨赛事去重：4 场同一份 rank fixture，32 个 distinct deckId 只实抓 32 次
    assert sum(1 for c in scraper.calls if c[0] == "deck") == DECK_IDS_COUNT
    assert set(actions(result).values()) <= {"fetched", "skipped"}
    assert "fetched" in set(actions(result).values())

    # 三清单 + scrape_runs 行
    for name in ("scraped", "question", "missing"):
        assert (result.lists_path / f"{name}.json").is_file()
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row is not None
        assert row.source == "mik_moe"
        assert row.status == "ok"
    engine.dispose()


def test_scrape_resume_skips_existing(tmp_path):
    scraper = FakeTournamentScraper()
    runner = make_runner(tmp_path, scraper)
    runner.scrape(series_id="54")
    call_count = len(scraper.calls)

    result = runner.scrape(series_id="54")
    assert len(scraper.calls) == call_count  # 零新请求（级联清单也未重抓）
    assert set(actions(result).values()) == {"skipped"}


def test_scrape_series_filter_none_match(tmp_path):
    scraper = FakeTournamentScraper()
    result = make_runner(tmp_path, scraper).scrape(series_id="99")
    assert ("list", 54, 1) not in scraper.calls
    assert result.stats.scraped != []  # series-list 本身仍落盘
    assert not is_valid_raw(tournament_detail_path(tmp_path / "raw", "3215"))


def test_scrape_max_tournaments(tmp_path):
    scraper = FakeTournamentScraper()
    make_runner(tmp_path, scraper).scrape(series_id="54", max_tournaments=1)
    raw = tmp_path / "raw"
    assert is_valid_raw(tournament_detail_path(raw, "3215"))
    assert not (raw / "mikmoe" / "tournaments" / "detail" / "3211.json").exists()


def test_scrape_top_n_page_size(tmp_path):
    scraper = FakeTournamentScraper()
    make_runner(tmp_path, scraper).scrape(series_id="54", top_n=32)
    assert ("rank", 3215, 1, 32) in scraper.calls


def test_scrape_api_error_question_and_missing(tmp_path):
    scraper = FakeTournamentScraper(fail_on={"deck"})
    result = make_runner(tmp_path, scraper).scrape(series_id="54")
    # 每场赛事 32 个卡组 × 4 场 = 128 次失败进 question
    assert len(result.stats.question) == 4 * DECK_IDS_COUNT
    assert all("deck" in q["id"] for q in result.stats.question)
    # 对账：卡组 raw 缺失进 missing（按 raw 路径去重，32 个卡组）
    assert len(result.stats.missing) == DECK_IDS_COUNT
    assert not result.stats.aborted


def test_scrape_not_ready_skips_tournament_gracefully(tmp_path):
    """进行中赛事 rank 返回 code=400 → MikMoeNotReadyError：跳过该场（不抓卡组）、
    记 question，不中止本轮。"""
    scraper = FakeTournamentScraper(not_ready_on={"rank"})
    result = make_runner(tmp_path, scraper).scrape(series_id="54")
    # 4 场赛事的 rank 全部 NotReady → 4 条 question，零卡组请求
    assert len(result.stats.question) == len(TOURNAMENT_IDS)
    assert all("rank" in q["id"] for q in result.stats.question)
    assert sum(1 for c in scraper.calls if c[0] == "deck") == 0
    assert not result.stats.aborted


def test_scrape_circuit_abort(tmp_path):
    class BoomScraper(FakeTournamentScraper):
        def fetch_series_list(self, page=1, page_size=100):
            raise CircuitOpenError("HTTP 403")

    result = make_runner(tmp_path, BoomScraper()).scrape()
    assert result.stats.aborted is True

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row.status == "aborted"
    engine.dispose()


# ---- CLI：ptcgdb scrape tourneys ----

from typer.testing import CliRunner  # noqa: E402

from ptcgdb import cli  # noqa: E402


def test_cli_scrape_tourneys(tmp_path, monkeypatch):
    fake = FakeTournamentScraper()

    class DummyHttp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(cli, "HttpClient", DummyHttp)
    monkeypatch.setattr(cli, "MikMoeTournamentScraper", lambda http: fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "scrape", "tourneys",
            "--series-id", "54",
            "--top-n", "32",
            "--raw-dir", str(tmp_path / "raw"),
            "--db-path", str(tmp_path / "test.db"),
        ],
    )
    assert result.exit_code == 0
    assert "run_id=" in result.output
    assert "status=ok" in result.output
    assert ("rank", 3215, 1, 32) in fake.calls
    assert is_valid_raw(tournament_detail_path(tmp_path / "raw", "3215"))

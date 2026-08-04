"""task 003 测试：限速器 / 退避 / 熔断 / raw 落盘 / 断点续传 / 三清单 + scrape_runs。

全部用 httpx MockTransport，零网络。限速器 interval=0、退避 wait_none()。
"""

import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tenacity import wait_none

from ptcgdb.orm import ScrapeRun
from ptcgdb.scrapers import (
    CircuitOpenError,
    HttpClient,
    MikMoeApiError,
    MikMoeScraper,
    RateLimiter,
    ScrapeRunner,
    TransientHttpError,
)
from ptcgdb.scrapers.raw_store import content_hash, is_valid_raw, read_raw, write_raw


def make_client(handler, **kwargs) -> HttpClient:
    kwargs.setdefault("rate_limiter", RateLimiter(interval=0))
    kwargs.setdefault("retry_wait", wait_none())
    return HttpClient(
        "https://tcg.mik.moe", transport=httpx.MockTransport(handler), **kwargs
    )


def ok_envelope(data):
    return {"code": 200, "data": data, "msg": ""}


# ---- 限速器 ----


def test_rate_limiter_paces_requests():
    now = [100.0]
    sleeps = []

    def fake_sleep(d):
        sleeps.append(d)
        now[0] += d

    limiter = RateLimiter(
        interval=2.0, slow_interval=5.0, clock=lambda: now[0], sleep=fake_sleep
    )
    limiter.wait()  # 首次请求不限速
    assert sleeps == []
    now[0] += 0.5
    limiter.wait()
    assert sleeps == [1.5]  # 补满 2 秒间隔
    now[0] += 0.5
    limiter.wait()
    assert sleeps == [1.5, 1.5]

    limiter.report_error()  # 连续出错 → 降速到 5 秒
    now[0] += 1.0
    limiter.wait()
    assert sleeps[-1] == 4.0

    limiter.report_success()  # 成功 → 恢复 2 秒
    now[0] += 1.0
    limiter.wait()
    assert sleeps[-1] == 1.0


def test_rate_limiter_zero_interval_never_sleeps():
    sleeps = []
    limiter = RateLimiter(interval=0, slow_interval=0, sleep=sleeps.append)
    for _ in range(3):
        limiter.wait()
    assert sleeps == []


# ---- 退避与熔断 ----


def test_retry_succeeds_after_transient_failures():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, text="server busy")
        return httpx.Response(200, json=ok_envelope([1]))

    client = make_client(handler)
    assert client.post_json("/x", {}) == ok_envelope([1])
    assert len(calls) == 3


def test_retry_gives_up_after_max_attempts():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    client = make_client(handler)
    with pytest.raises(TransientHttpError):
        client.post_json("/x", {})
    assert calls == 3  # 最多重试 3 次后放弃


def test_circuit_open_on_403():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="Forbidden")

    client = make_client(handler)
    with pytest.raises(CircuitOpenError, match="403"):
        client.post_json("/x", {})
    assert calls == 1  # 403 不重试，立即熔断


def test_circuit_open_on_non_json():
    def handler(request):
        return httpx.Response(200, text="<html>请完成人机验证</html>")

    client = make_client(handler)
    with pytest.raises(CircuitOpenError, match="非 JSON"):
        client.post_json("/x", {})


def test_circuit_open_after_five_consecutive_failures():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler, max_attempts=1)
    for _ in range(5):
        with pytest.raises(TransientHttpError):
            client.post_json("/x", {})
    assert calls == 5
    with pytest.raises(CircuitOpenError, match="连续 5 次"):
        client.post_json("/x", {})
    assert calls == 5  # 熔断后不再发出请求


# ---- mikmoe 封装 ----


def test_card_index_must_be_string():
    scraper = MikMoeScraper(make_client(lambda r: httpx.Response(200, json=ok_envelope({}))))
    with pytest.raises(TypeError):
        scraper.fetch_card_detail("CSM1aC", 1)  # 传整数会报 10002，本地直接拒绝


def test_api_error_on_bad_code_or_empty_data():
    def handler(request):
        return httpx.Response(200, json={"code": 10002, "data": None, "msg": "内部错误"})

    scraper = MikMoeScraper(make_client(handler))
    with pytest.raises(MikMoeApiError):
        scraper.fetch_product_list()


# ---- raw 落盘 ----


def test_write_raw_skip_valid_and_force(tmp_path):
    path = tmp_path / "a.json"
    assert write_raw(path, ok_envelope({"x": 1}), source="mik_moe") is True
    assert is_valid_raw(path)
    # 存在且 hash 有效 → 跳过（append-only 语义）
    assert write_raw(path, ok_envelope({"x": 2}), source="mik_moe") is False
    assert read_raw(path)["data"]["x"] == 1
    # force 重抓覆盖
    assert write_raw(path, ok_envelope({"x": 2}), source="mik_moe", force=True) is True
    doc = read_raw(path)
    assert doc["data"]["x"] == 2
    assert doc["_meta"]["source"] == "mik_moe"
    assert doc["_meta"]["content_hash"] == content_hash(ok_envelope({"x": 2}))
    # 损坏文件视为无效
    path.write_text("not json", encoding="utf-8")
    assert not is_valid_raw(path)
    assert read_raw(path) is None


# ---- runner：三清单 + 断点续传 + scrape_runs ----

PRODUCTS = ok_envelope({"list": [{"setId": "TEST1", "name": "测试系列", "cardsNum": 2}]})
DETAIL = ok_envelope(
    {
        "setId": "TEST1",
        "cardsNum": 2,
        "cards": [
            {"setCode": "TEST1", "cardIndex": "001", "cardName": "卡一"},
            {"setCode": "TEST1", "cardIndex": "002", "cardName": "卡二"},
        ],
    }
)
CARD1 = ok_envelope({"name": "卡一", "setCode": "TEST1", "cardIndex": "001"})
CARD2 = ok_envelope({"name": "卡二", "setCode": "TEST1", "cardIndex": "002"})


def make_runner(tmp_path, handler):
    client = make_client(handler)
    runner = ScrapeRunner(tmp_path / "raw", MikMoeScraper(client), tmp_path / "test.db")
    return runner


def read_body_json(request):
    return json.loads(request.content.decode("utf-8"))


def test_scrape_cards_lists_and_run_row(tmp_path):
    def handler(request):
        if request.url.path == "/api/v3/card/product-list":
            return httpx.Response(200, json=PRODUCTS)
        if request.url.path == "/api/v3/card/product-detail":
            return httpx.Response(200, json=DETAIL)
        if request.url.path == "/api/v3/card/card-detail":
            body = read_body_json(request)
            assert isinstance(body["cardIndex"], str)  # cardIndex 必须字符串
            if body["cardIndex"] == "001":
                return httpx.Response(200, json=CARD1)
            return httpx.Response(200, json={"code": 10002, "data": None, "msg": "内部错误"})
        raise AssertionError(f"unexpected path {request.url.path}")

    result = make_runner(tmp_path, handler).scrape_cards(set_ids=["TEST1"])
    stats = result.stats
    assert stats.total == 2
    assert [r["id"] for r in stats.scraped] == ["TEST1-001"]
    assert len(stats.question) == 1 and stats.question[0]["id"] == "TEST1-002"
    assert len(stats.missing) == 1 and stats.missing[0]["id"] == "TEST1-002"
    assert not stats.aborted

    # 三清单落盘
    for name in ("scraped", "question", "missing"):
        assert (result.lists_path / f"{name}.json").is_file()
    # raw 文件落盘且带 _meta
    doc = read_raw(tmp_path / "raw" / "mikmoe" / "TEST1" / "001.json")
    assert doc["data"]["name"] == "卡一"
    assert doc["_meta"]["source"] == "mik_moe"

    # scrape_runs 行
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row is not None
        assert row.source == "mik_moe"
        assert row.status == "ok"
        assert row.card_count == 2
        assert row.ok_count == 1
        assert row.question_count == 1
        assert row.missing_count == 1
        assert row.lists_path == str(result.lists_path)
        assert row.manifest_hash and row.finished_at is not None
    engine.dispose()


def test_resume_skips_existing_files(tmp_path):
    card_calls = []

    def handler(request):
        if request.url.path == "/api/v3/card/product-list":
            return httpx.Response(200, json=PRODUCTS)
        if request.url.path == "/api/v3/card/product-detail":
            return httpx.Response(200, json=DETAIL)
        if request.url.path == "/api/v3/card/card-detail":
            idx = read_body_json(request)["cardIndex"]
            card_calls.append(idx)
            return httpx.Response(200, json=CARD1 if idx == "001" else CARD2)
        raise AssertionError(f"unexpected path {request.url.path}")

    runner = make_runner(tmp_path, handler)
    # 预置 001 的有效 raw 文件 → 断点续传应跳过它
    write_raw(
        runner.card_path("TEST1", "001"), CARD1, source="mik_moe"
    )
    result = runner.scrape_cards(set_ids=["TEST1"])
    assert card_calls == ["002"]  # 001 未发请求
    actions = {r["id"]: r["action"] for r in result.stats.scraped}
    assert actions == {"TEST1-001": "skipped", "TEST1-002": "fetched"}
    assert result.stats.missing == []

    # 重跑：全部跳过，零请求
    card_calls.clear()
    result2 = runner.scrape_cards(set_ids=["TEST1"])
    assert card_calls == []
    assert all(r["action"] == "skipped" for r in result2.stats.scraped)


def test_scrape_sets_writes_products_and_details(tmp_path):
    def handler(request):
        if request.url.path == "/api/v3/card/product-list":
            return httpx.Response(200, json=PRODUCTS)
        if request.url.path == "/api/v3/card/product-detail":
            assert read_body_json(request) == {"setId": "TEST1"}
            return httpx.Response(200, json=DETAIL)
        raise AssertionError(f"unexpected path {request.url.path}")

    result = make_runner(tmp_path, handler).scrape_sets()
    assert is_valid_raw(tmp_path / "raw" / "mikmoe" / "products.json")
    assert is_valid_raw(tmp_path / "raw" / "mikmoe" / "TEST1" / "cards.json")
    assert result.stats.missing == []
    assert len(result.stats.scraped) == 2  # product-list + TEST1 详情


def test_circuit_abort_marks_run_aborted(tmp_path):
    def handler(request):
        return httpx.Response(403, text="Forbidden")

    result = make_runner(tmp_path, handler).scrape_cards(set_ids=["TEST1"])
    assert result.stats.aborted is True

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(engine) as session:
        row = session.get(ScrapeRun, result.run_id)
        assert row.status == "aborted"
    engine.dispose()


# ---- Batch 1: 增量采集 cardsNum 对账 ----

PRODUCTS_WITH_CARDS_NUM = {
    "code": 200,
    "data": {
        "list": [
            {"setId": "TEST1", "name": "Test Set", "cardsNum": 5},
        ]
    },
    "msg": "OK",
}

DETAIL_WITH_3_CARDS = {
    "code": 200,
    "data": {
        "setId": "TEST1",
        "cards": [
            {"setCode": "TEST1", "cardIndex": "001"},
            {"setCode": "TEST1", "cardIndex": "002"},
            {"setCode": "TEST1", "cardIndex": "003"},
        ],
    },
    "msg": "OK",
}

DETAIL_WITH_5_CARDS = {
    "code": 200,
    "data": {
        "setId": "TEST1",
        "cards": [
            {"setCode": "TEST1", "cardIndex": "001"},
            {"setCode": "TEST1", "cardIndex": "002"},
            {"setCode": "TEST1", "cardIndex": "003"},
            {"setCode": "TEST1", "cardIndex": "004"},
            {"setCode": "TEST1", "cardIndex": "005"},
        ],
    },
    "msg": "OK",
}


def test_incremental_cardsnum_mismatch_triggers_refetch(tmp_path):
    """cardsNum 与缓存不一致时自动重新拉取 product-detail。"""
    call_count = [0]

    def handler(request):
        if request.url.path == "/api/v3/card/product-list":
            return httpx.Response(200, json=PRODUCTS_WITH_CARDS_NUM)
        if request.url.path == "/api/v3/card/product-detail":
            call_count[0] += 1
            if call_count[0] == 1:
                # 首次返回只有 3 张卡（与 cardsNum=5 不符）
                return httpx.Response(200, json=DETAIL_WITH_3_CARDS)
            else:
                return httpx.Response(200, json=DETAIL_WITH_5_CARDS)
        if request.url.path.startswith("/api/v3/card/card-detail"):
            return httpx.Response(200, json={
                "code": 200,
                "data": {"setCode": "TEST1", "cardIndex": "001", "name": "Test"},
                "msg": "OK",
            })
        raise AssertionError(f"unexpected {request.url.path}")

    runner = make_runner(tmp_path, handler)

    # 首次抓取：cardsNum=5 ≠ 缓存 3 张 → 自动触发重拉（product-detail 被调用两次）
    runner.scrape_cards(set_ids=["TEST1"])
    assert call_count[0] == 2  # 首次拉取 + cardsNum 对账触发的重拉

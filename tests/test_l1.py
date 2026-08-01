"""task 014 测试：L1 赛制监控 + 提案生成。

零网络：fetcher 注入。契约测试用真实页面 fixture（tests/fixtures/l1/，
2026-08-01 recon 保存）。提案 = SnapshotSeed 超集，apply_snapshot 直接消费。
"""

from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.legal.seed import SnapshotSeed, seed_snapshots
from ptcgdb.legal.versions import apply_snapshot
from ptcgdb.migrations import apply_migrations
from ptcgdb.monitor.l1 import (
    PAGE_TARGETS,
    content_hash,
    extract_blocks,
    extract_news_entries,
    parse_regulation,
    run_l1,
    serialize_blocks,
)
from ptcgdb.orm import LegalitySnapshot

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "l1"
REGULATION_HTML = (FIXTURE_DIR / "regulation.html").read_text(encoding="utf-8")
NEWS_HTML = (FIXTURE_DIR / "news.html").read_text(encoding="utf-8")
EXTRA_HTML = (FIXTURE_DIR / "extra.html").read_text(encoding="utf-8")
CONFIG_LEGALITY = Path("config/legality")


def _seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)
    seed_snapshots(db_path, CONFIG_LEGALITY)
    return db_path


def _article_html(inner: str, *, auth_key: str = "AAA", footer_ts: str = "v1") -> str:
    return f"""<html><head><link href="style.css?ver={footer_ts}"></head><body>
<header>导航 {footer_ts}</header>
<main><section class="article-body t-main bdtn">
<div class="article-body__inner">
{inner}
</div></section></main>
<footer>页脚 更新于 {footer_ts}</footer>
</body></html>"""


# ---- 正文提取：剔除动态区块 ----


def test_extract_strips_dynamic_blocks():
    inner = (
        '<h3 class="line-block__title"><span>标准赛制</span></h3>'
        '<p class="t-container__txt">卡牌左下角的赛制标记为 G、H、I 的卡牌'
        '<img src="https://image.pokemon.com.cn/x.png?auth_key={auth}" alt=""></p>'
        '<li class="list-dote">伤药</li>'
    )
    html_a = _article_html(inner.format(auth="KEY_A_111"), auth_key="A", footer_ts="2026-01")
    html_b = _article_html(inner.format(auth="KEY_B_999"), auth_key="B", footer_ts="2026-12")
    blocks_a = extract_blocks(html_a)
    blocks_b = extract_blocks(html_b)
    # img/auth_key、页眉页脚、?ver= 全部不影响提取结果 → 不假阳性
    assert blocks_a == blocks_b
    assert content_hash(serialize_blocks(blocks_a)) == content_hash(serialize_blocks(blocks_b))
    assert ("h3", "标准赛制") in blocks_a
    assert ("li", "伤药") in blocks_a


def test_extract_detects_real_change():
    a = extract_blocks(_article_html("<p>赛制标记为 G、H、I</p>"))
    b = extract_blocks(_article_html("<p>赛制标记为 H、I、J</p>"))
    assert content_hash(serialize_blocks(a)) != content_hash(serialize_blocks(b))


# ---- 真实 fixture 契约 ----


def test_parse_regulation_real_fixture():
    blocks = extract_blocks(REGULATION_HTML)
    parsed = parse_regulation(blocks)
    assert parsed.parse_errors == []

    std = parsed.formats["standard"]
    assert std.effective_from == date(2026, 7, 16)
    assert std.allowed_marks == ["G", "H", "I"]
    promo = [w for w in std.whitelist if w.get("note") and "PROMO_" in w["note"]]
    past = [w for w in std.whitelist if not (w.get("note") and "PROMO_" in w["note"])]
    assert len(promo) == 18
    assert len(past) == 26  # PRD 2.1 核定口径（不含"各种基本能量卡"）
    assert {w["name_full"] for w in past} >= {"博士的研究", "老大的指令", "伤药"}

    op = parsed.formats["open"]
    assert op.effective_from == date(2026, 7, 16)
    assert op.allowed_marks is None  # 系列句不可机械映射，沿用当前快照
    past_open = [w for w in op.whitelist if not (w.get("note") and "PROMO_" in w["note"])]
    assert len(past_open) == 32
    assert len(op.banned) == 3
    marsh = next(b for b in op.banned if b["name"] == "玛夏多")
    assert marsh["ability_or_attack"] == "破罐破摔"
    assert {b["name"] for b in op.banned} == {"玛夏多", "阿塞萝拉", "全满药"}


def test_parse_failure_records_errors():
    # 抹掉赛制标记句 → 不猜，记 parse_errors
    html = REGULATION_HTML.replace(
        "卡牌左下角的赛制标记为 G、H、I 的卡牌和8种基本能量卡", "可用卡牌如下"
    )
    parsed = parse_regulation(extract_blocks(html))
    assert any("赛制标记" in e for e in parsed.parse_errors)
    assert parsed.formats["standard"].allowed_marks is None


def test_extract_news_entries_real_fixture():
    entries = extract_news_entries(NEWS_HTML)
    assert len(entries) >= 8
    first = entries[0]
    assert first.href == "https://www.pokemon.cn/tcg/campaign/23243.html"
    assert "青岛" in first.title
    assert first.date == "2026-07-30"
    assert first.category == "Campaign"
    # auth_key 不进入序列化
    assert "auth_key" not in repr(entries)


# ---- run_l1：基线 / 不变 / 变更 ----


def _fetcher(mapping: dict[str, str]):
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return mapping[url]

    fetch.calls = calls
    return fetch


def _pages_by_id():
    return {p.page_id: p for p in PAGE_TARGETS}


def test_run_l1_baseline_then_unchanged(tmp_path):
    mapping = {
        "https://www.pokemon.cn/tcg-rules-regulation": REGULATION_HTML,
        "https://www.pokemon.cn/tcg-rules-regulation-extra/": EXTRA_HTML,
        "https://www.pokemon.cn/category/tcg": NEWS_HTML,
    }
    db_path = _seeded_db(tmp_path)
    store_dir = tmp_path / "l1"
    proposals_dir = tmp_path / "proposals"

    fetch = _fetcher(mapping)
    result = run_l1(fetch, db_path, store_dir, proposals_dir, baseline=True)
    assert sorted(result.baselines) == ["extra", "news", "regulation"]
    assert result.proposals == []
    assert (store_dir / "regulation.json").exists()

    # 第二轮：内容不变 → 全部 unchanged，零提案
    result2 = run_l1(fetch, db_path, store_dir, proposals_dir)
    assert sorted(result2.unchanged) == ["extra", "news", "regulation"]
    assert result2.proposals == []


def _rotated_regulation_html() -> str:
    # 只改标准赛制分节（第一处"更新日期"在标准节）——开放节日期不变，不产生开放提案
    return (
        REGULATION_HTML.replace("更新日期：2026年7月16日", "更新日期：2026年9月16日", 1)
        .replace("（自2026年7月16日起）", "（自2026年9月16日起）")
        .replace("赛制标记为 G、H、I", "赛制标记为 H、I、J")
    )


def test_run_l1_change_proposal_applies_end_to_end(tmp_path):
    """变更 → 提案 → apply_snapshot → 新快照生效（goal 判定：提案被 legal-apply 直接消费）。"""
    urls = _pages_by_id()
    mapping_baseline = {
        urls["regulation"].url: REGULATION_HTML,
        urls["extra"].url: EXTRA_HTML,
        urls["news"].url: NEWS_HTML,
    }
    db_path = _seeded_db(tmp_path)
    store_dir = tmp_path / "l1"
    proposals_dir = tmp_path / "proposals"
    run_l1(_fetcher(mapping_baseline), db_path, store_dir, proposals_dir, baseline=True)

    mapping_changed = dict(mapping_baseline)
    mapping_changed[urls["regulation"].url] = _rotated_regulation_html()
    result = run_l1(_fetcher(mapping_changed), db_path, store_dir, proposals_dir)

    assert result.unchanged == ["extra", "news"]
    assert len(result.proposals) == 1
    proposal_path = result.proposals[0]
    doc = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert doc["status"] == "pending_review"
    assert doc["snapshot_id"] == "standard-2026-09-16"
    assert doc["allowed_marks"] == ["H", "I", "J"]
    # 白名单从页面重新解析（18 特典 + 26 旧卡）
    assert len(doc["whitelist_cards"]) == 44
    assert doc["diff"]["allowed_marks"] == {"old": ["G", "H", "I"], "new": ["H", "I", "J"]}

    # SnapshotSeed 超集：直接被 apply_snapshot 消费
    seed = SnapshotSeed.model_validate(doc)
    assert seed.snapshot_id == "standard-2026-09-16"
    snapshot_id = apply_snapshot(
        db_path, proposal_path,
        changelog_path=tmp_path / "CHANGELOG.md", versions_dir=tmp_path / "versions",
    )
    assert snapshot_id == "standard-2026-09-16"
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        new_snap = session.get(LegalitySnapshot, "standard-2026-09-16")
        assert new_snap.effective_to is None
        assert new_snap.allowed_marks == ["H", "I", "J"]
        old_snap = session.get(LegalitySnapshot, "standard-2026-07-16")
        assert old_snap.effective_to == date(2026, 9, 15)  # 旧快照闭合不删除
    engine.dispose()


def test_run_l1_noop_change_no_proposal(tmp_path):
    """hash 变了但解析内容与当前快照一致（如注释文字微调）→ 不生成提案，store 照更新。"""
    urls = _pages_by_id()
    mapping = {
        urls["regulation"].url: REGULATION_HTML,
        urls["extra"].url: EXTRA_HTML,
        urls["news"].url: NEWS_HTML,
    }
    db_path = _seeded_db(tmp_path)
    store_dir = tmp_path / "l1"
    proposals_dir = tmp_path / "proposals"
    run_l1(_fetcher(mapping), db_path, store_dir, proposals_dir, baseline=True)

    mutated = REGULATION_HTML.replace(
        "※部分特殊卡牌的“商品编号”可能位于卡牌的其他位置。",
        "※部分特殊卡牌的“商品编号”可能位于卡牌的其他位置（请留意）。",
    )
    mapping[urls["regulation"].url] = mutated
    result = run_l1(_fetcher(mapping), db_path, store_dir, proposals_dir)
    assert result.proposals == []
    assert result.noop == ["regulation"]


def test_run_l1_parse_failure_needs_manual(tmp_path):
    """关键句缺失 → 提案 status=needs_manual，快照字段沿用当前值，绝不猜测。"""
    urls = _pages_by_id()
    mapping = {
        urls["regulation"].url: REGULATION_HTML,
        urls["extra"].url: EXTRA_HTML,
        urls["news"].url: NEWS_HTML,
    }
    db_path = _seeded_db(tmp_path)
    store_dir = tmp_path / "l1"
    proposals_dir = tmp_path / "proposals"
    run_l1(_fetcher(mapping), db_path, store_dir, proposals_dir, baseline=True)

    broken = _rotated_regulation_html().replace(
        "卡牌左下角的赛制标记为 H、I、J 的卡牌和8种基本能量卡", "可用卡牌范围详见说明"
    )
    mapping[urls["regulation"].url] = broken
    result = run_l1(_fetcher(mapping), db_path, store_dir, proposals_dir)

    assert len(result.proposals) == 1
    doc = yaml.safe_load(result.proposals[0].read_text(encoding="utf-8"))
    assert doc["status"] == "needs_manual"
    assert doc["parse_errors"]
    assert doc["allowed_marks"] == ["G", "H", "I"]  # 沿用当前快照，未猜


def test_run_l1_news_new_entry(tmp_path):
    """公告新增：命中赛制关键词 → needs_manual 提案；未命中 → 仅事件。"""
    urls = _pages_by_id()
    mapping = {
        urls["regulation"].url: REGULATION_HTML,
        urls["extra"].url: EXTRA_HTML,
        urls["news"].url: NEWS_HTML,
    }
    db_path = _seeded_db(tmp_path)
    store_dir = tmp_path / "l1"
    proposals_dir = tmp_path / "proposals"
    run_l1(_fetcher(mapping), db_path, store_dir, proposals_dir, baseline=True)

    new_item = (
        '<li class="card__element  card__category--card card__category--card">'
        '<a href="https://www.pokemon.cn/tcg/card/99999.html"><div class="card__container">'
        '<div class="card__content">'
        '<div class="card__products-title">关于标准赛制调整的通知</div>'
        '<footer class="card__footer">'
        '<time class="card__footer--category">Card</time>'
        '<time class="card__footer--date">2026-08-01</time>'
        "</footer></div></div></a></li>"
    )
    mapping[urls["news"].url] = NEWS_HTML.replace(
        '<ul class="card-list__body">', '<ul class="card-list__body">' + new_item
    )
    events: list[tuple[str, dict]] = []
    result = run_l1(
        _fetcher(mapping), db_path, store_dir, proposals_dir,
        on_event=lambda e, p: events.append((e, p)),
    )
    assert any(e == "news" for e, _ in events)
    assert result.news and result.news[0]["title"] == "关于标准赛制调整的通知"
    assert len(result.proposals) == 1
    doc = yaml.safe_load(result.proposals[0].read_text(encoding="utf-8"))
    assert doc["status"] == "needs_manual"

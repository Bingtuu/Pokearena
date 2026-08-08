"""task 028：stats basis 口径标签（PRD v1.14 FR-9.1a/9.7）+ pairings 导出测试。

黄金数据集 + 一场 limitless regional（division=NULL，与 ingest 真实口径一致）：
- 默认 basis=cn 不含 intl_aligned（EN/JP 样本不与 CN 混同）；
- basis=intl_aligned 只有 EN 赛事参与；basis=all 合并；
- meta 回显 basis；SDK 双后端（SQLite/JSONL）契约一致；
- pairings.jsonl 导出（十三件套）计数断言；
- division=NULL 的 limitless 赛事不被 division 过滤排除（v1.14 续：NULL=未知
  组别不做排他；缺省 division=master 下 T7 仍参与，CN senior 排除行为不变）。

期望值用手工数学（与 golden_stats.expected 同款独立计算，容差 1e-9）。
"""

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from ptcgdb import cli
from ptcgdb.export.exporter import EXPORT_FILES, export_all
from ptcgdb.sdk import open_db, open_jsonl
from tests.golden_stats import AS_OF, DATE_FROM, DATE_TO, G1, build_golden_db

TOL = 1e-9
WIN = {"as_of": AS_OF, "date_from": DATE_FROM, "date_to": DATE_TO, "division": None}
T7 = "limitless:aaaaaaaabbbbbbbbcccc0001"

# 各赛事静态权重 × 时间衰减（as_of=2026-08-01；log10(100)=2 / log10(1000)=3 / log10(10)=1）
W_T1 = 2.0 * 2 * 0.5 ** (9 / 90.0)  # super 2026-07-23
W_T2 = 1.0 * 3 * 0.5 ** (16 / 90.0)  # city 2026-07-16
W_T3 = 1.0 * 2 * 0.5 ** (12 / 90.0)  # senior city 2026-07-20（division=None 时参与）
W_T6 = 1.0 * 1 * 0.5 ** (7 / 90.0)  # topcut NULL 2026-07-25（WUR 计入）
W_T7 = 1.5 * 2 * 0.5 ** (2 / 90.0)  # limitless regional 2026-07-30

_SW1 = 100.0 + 1 / 2 + 1 / 9
CARRY_G1_T1 = (100.0 + 1 / 9) / _SW1  # D101 + D103
CARRY_G1_T2 = 50.0 / (50.0 + 1 / 3)  # D104

CN_NUM = W_T1 * CARRY_G1_T1 + W_T2 * CARRY_G1_T2 + W_T3 * 1.0 + W_T6 * 1.0
CN_DEN = W_T1 + W_T2 + W_T3 + W_T6
WUR_CN_G1 = CN_NUM / CN_DEN
WUR_INTL_G1 = 1.0  # 单赛事单出战条目，份额归一 = 1
WUR_ALL_G1 = (CN_NUM + W_T7 * 1.0) / (CN_DEN + W_T7)


def build_basis_db(db_path):
    """黄金数据集 + 一场 limitless regional（basis=intl_aligned，division=NULL）。"""
    build_golden_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO tournaments (tournament_id, source, series_id, name, tier, "
            "tier_coef, division, date, location, participant_count, topcut_slots, "
            "format, regulation_mark, format_end, is_qual, is_team, official_url, "
            "fetched_at) VALUES (?, 'limitless', NULL, 'Test Regional Championship', "
            "'regional', 1.5, NULL, '2026-07-30', NULL, 100, 3, 'standard', NULL, "
            "NULL, 0, 0, 'https://limitlesstcg.com/tournaments/x', '2026-08-01')",
            (T7,),
        )
        conn.execute(
            "INSERT INTO decks (deck_id, archetype_id, archetype_name, deck_code, "
            "mapping_status, mapped_ratio, source, fetched_at) VALUES "
            "('limitless:d1', 'a1', 'EN 原型', NULL, 'full', 1.0, 'limitless', '2026-08-01')"
        )
        conn.execute(
            "INSERT INTO deck_appearances (deck_id, tournament_id, rank, points, "
            "player_ref, record_wins, record_losses, record_ties, source, fetched_at) "
            "VALUES ('limitless:d1', ?, 1, 10.0, 'enplayer', 5, 0, 0, 'limitless', "
            "'2026-08-01')",
            (T7,),
        )
        conn.execute(
            "INSERT INTO deck_cards (deck_id, card_id, count, raw_name, stat_scope) "
            "VALUES ('limitless:d1', 'GOLD-001', 2, 'EN 卡', 'pokemon')"
        )
        # pairings 两行（导出 pairings.jsonl 计数断言用；含一行平局 winner=NULL）
        conn.execute(
            "INSERT INTO pairings (tournament_id, phase, round, table_no, player1, "
            "player2, winner, fetched_at) VALUES (?, 2, 1, 1, 'enplayer', 'rival', "
            "'enplayer', '2026-08-01')",
            (T7,),
        )
        conn.execute(
            "INSERT INTO pairings (tournament_id, phase, round, table_no, player1, "
            "player2, winner, fetched_at) VALUES (?, 1, 1, 1, 'enplayer', 'rival2', "
            "NULL, '2026-08-01')",
            (T7,),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def env(tmp_path):
    db = build_basis_db(tmp_path / "g.db")
    dist = tmp_path / "dist"
    manifest = export_all(db, dist)
    return db, dist, manifest


# ---- basis 过滤（SDK SQLite 后端）----


def test_basis_default_cn_excludes_intl(env):
    db, _, _ = env
    with open_db(db) as d:
        res = d.stats_usage(**WIN)  # 缺省 basis='cn'
    assert res.meta["basis"] == "cn"
    assert res.meta["n_tournaments"] == 4  # T1/T2/T3(division 放开)/T6；T7 被 basis 排除
    got = {s.group_key: s for s in res.data}
    assert got[G1].value == pytest.approx(WUR_CN_G1, abs=TOL)
    assert got[G1].n == 5  # 101/103/104/107/110，不含 limitless:d1


def test_basis_intl_aligned_only_en(env):
    db, _, _ = env
    with open_db(db) as d:
        res = d.stats_usage(basis="intl_aligned", **WIN)
        wr = d.stats_winrate(basis="intl_aligned", layer="a", **WIN)
    assert res.meta["basis"] == "intl_aligned"
    assert res.meta["n_tournaments"] == 1  # 只有 T7
    got = {s.group_key: s for s in res.data}
    assert got[G1].value == pytest.approx(WUR_INTL_G1, abs=TOL)
    assert got[G1].n == 1
    assert wr.meta["layer"] == "a"
    got_wr = {s.group_key: s for s in wr.data}
    assert got_wr[G1].value == pytest.approx(1.0, abs=TOL)  # record 5-0-0
    assert got_wr[G1].n == 5


def test_basis_all_merges(env):
    db, _, _ = env
    with open_db(db) as d:
        res = d.stats_usage(basis="all", **WIN)
    assert res.meta["basis"] == "all"
    assert res.meta["n_tournaments"] == 5  # CN 四场 + T7
    got = {s.group_key: s for s in res.data}
    assert got[G1].value == pytest.approx(WUR_ALL_G1, abs=TOL)
    assert got[G1].n == 6


def test_basis_intl_with_default_division_master_included(env):
    """division 过滤语义（v1.14 续）：division IS NULL 的赛事不因 :division 被排除。
    limitless 赛事 division=NULL（ingest 口径），缺省 division=master 下 T7 仍参与。"""
    db, _, _ = env
    win = {k: v for k, v in WIN.items() if k != "division"}  # 缺省 master
    with open_db(db) as d:
        res = d.stats_usage(basis="intl_aligned", **win)
    assert res.meta["n_tournaments"] == 1  # T7 不被缺省 master 排除
    got = {s.group_key: s for s in res.data}
    assert got[G1].value == pytest.approx(WUR_INTL_G1, abs=TOL)
    assert got[G1].n == 1


def test_default_division_master_cn_unchanged(env):
    """CN 行为不变：缺省 division=master 下 senior 赛事 T3 仍被排除
    （T3 division='senior' 非 NULL，新语义只放开 NULL）。"""
    db, _, _ = env
    win = {k: v for k, v in WIN.items() if k != "division"}  # 缺省 master + 默认 basis cn
    with open_db(db) as d:
        res = d.stats_usage(**win)
    assert res.meta["basis"] == "cn"
    assert res.meta["n_tournaments"] == 3  # T1/T2/T6；T3 senior 排除、T7 被 basis 排除
    got = {s.group_key: s for s in res.data}
    assert got[G1].n == 4  # 101/103/104/110，与黄金期望一致


def test_explicit_division_senior_keeps_null(env):
    """显式 division=senior 时 NULL 不排除：T7（division=NULL）仍参与，
    与 senior 赛事并列（NULL 语义=未知组别，不做排他）。"""
    db, _, _ = env
    win = {k: v for k, v in WIN.items() if k != "division"}
    with open_db(db) as d:
        res = d.stats_usage(basis="intl_aligned", division="senior", **win)
    assert res.meta["n_tournaments"] == 1  # CN senior 被 basis 排除，只剩 T7
    got = {s.group_key: s for s in res.data}
    assert got[G1].value == pytest.approx(WUR_INTL_G1, abs=TOL)


def test_basis_drilldown_meta(env):
    db, _, _ = env
    with open_db(db) as d:
        res = d.stats_card(G1, basis="intl_aligned", **WIN)
    assert res.meta["basis"] == "intl_aligned"
    assert len(res.data) == 1
    assert res.data[0].tournament_id == T7


# ---- SDK 双后端契约（SQLite vs JSONL）----


def test_basis_dual_backend_contract(env):
    db, dist, _ = env
    with open_db(db) as d_db, open_jsonl(dist) as d_jsonl:
        for basis in ("cn", "intl_aligned", "all"):
            r_db = d_db.stats_usage(basis=basis, **WIN)
            r_jsonl = d_jsonl.stats_usage(basis=basis, **WIN)
            assert r_db.data == r_jsonl.data
            assert r_db.meta == r_jsonl.meta


# ---- 导出：pairings.jsonl（十三件套）----


def test_export_pairings_jsonl(env):
    _, dist, manifest = env
    assert "pairings.jsonl" in EXPORT_FILES
    path = dist / "pairings.jsonl"
    assert path.exists()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert manifest["counts"]["pairings"] == 2
    row = next(r for r in rows if r["phase"] == 2)
    assert row == {
        "tournament_id": T7, "phase": 2, "round": 1, "table_no": 1,
        "player1": "enplayer", "player2": "rival", "winner": "enplayer",
        "fetched_at": "2026-08-01T00:00:00",  # DateTime 列序列化为完整 ISO
    }
    tie = next(r for r in rows if r["phase"] == 1)
    assert tie["winner"] is None  # 平局原样 NULL（不猜）
    checksums = (dist / "checksums.sha256").read_text(encoding="utf-8")
    assert "pairings.jsonl" in checksums


# ---- CLI --basis ----


def test_cli_stats_basis(tmp_path):
    db = build_basis_db(tmp_path / "g.db")
    window = ["--as-of", AS_OF, "--from", DATE_FROM, "--to", DATE_TO, "--division", ""]
    result = CliRunner().invoke(
        cli.app,
        ["stats", "usage", *window, "--basis", "intl_aligned",
         "--format", "json", "--db-path", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["basis"] == "intl_aligned"
    assert payload["meta"]["n_tournaments"] == 1
    got = {r["group_key"]: r for r in payload["data"]}
    assert got[G1]["value"] == pytest.approx(WUR_INTL_G1, abs=TOL)


def test_cli_stats_basis_default_cn(tmp_path):
    db = build_basis_db(tmp_path / "g.db")
    window = ["--as-of", AS_OF, "--from", DATE_FROM, "--to", DATE_TO, "--division", ""]
    result = CliRunner().invoke(
        cli.app,
        ["stats", "usage", *window, "--format", "json", "--db-path", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["basis"] == "cn"  # 缺省 cn，不混 EN/JP 样本
    assert payload["meta"]["n_tournaments"] == 4

"""stats 引擎：黄金数据集上三指标 canonical SQL 结果 = 手工期望值（容差 1e-9）。"""

import pytest

from ptcgdb.stats.engine import StatsParams, usage, winrate, wws
from tests.golden_stats import AS_OF, DATE_FROM, DATE_TO, G1, G2, G3, build_golden_db, expected

TOL = 1e-9


@pytest.fixture()
def env(tmp_path):
    db = build_golden_db(tmp_path / "g.db")
    params = StatsParams(as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO)
    return db, params, expected()


def by_key(stats):
    return {s.group_key: s for s in stats}


def test_usage_decks_basis(env):
    db, params, exp = env
    params = StatsParams(
        as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO, min_n=2
    )
    stats, meta = usage(db, params)
    got = by_key(stats)
    assert set(got) == {G1, G2, G3}  # partial 卡组、other scope 不进统计
    for g in (G1, G2, G3):
        assert got[g].value == pytest.approx(exp["wur"][g], abs=TOL)
        assert got[g].n == exp["n_usage"][g]
        assert got[g].basis == "decks"
    assert got[G3].low_confidence is True   # n=1 < min_n=5
    assert got[G1].low_confidence is False
    # meta 回显
    assert meta["as_of"] == AS_OF
    assert meta["date_from"] == DATE_FROM and meta["date_to"] == DATE_TO
    assert meta["division"] == "master"
    assert meta["usage_basis"] == "decks"
    assert meta["name_group_rules_hash"]
    assert meta["tournament_tiers_hash"]
    assert meta["n_tournaments"] == 3  # T3 senior / T4 qual / T5 缺权重排除；T6 计入 WUR


def test_usage_copies_basis(env):
    db, params, exp = env
    params = StatsParams(
        as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO, usage_basis="copies"
    )
    stats, _ = usage(db, params)
    got = by_key(stats)
    for g in (G1, G2, G3):
        assert got[g].value == pytest.approx(exp["wur_copies"][g], abs=TOL)
        assert got[g].basis == "copies"


def test_usage_filters(env):
    db, _, _ = env
    # senior 组别：只命中 T3（D7 携带 G1）→ G1 WUR=1.0
    params = StatsParams(
        as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO, division="senior"
    )
    stats, meta = usage(db, params)
    got = by_key(stats)
    assert set(got) == {G1}
    assert got[G1].value == pytest.approx(1.0, abs=TOL)
    assert meta["n_tournaments"] == 1
    # include_qual 放开后 T4 计入
    params = StatsParams(
        as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO, include_qual=True
    )
    _, meta = usage(db, params)
    assert meta["n_tournaments"] == 4  # T1/T2/T4/T6（T5 缺权重仍排除）


def test_winrate_b_layer(env):
    db, params, exp = env
    stats, meta = winrate(db, params, layer="b")
    got = by_key(stats)
    for g in (G1, G2, G3):
        assert got[g].value == pytest.approx(exp["wr_b"][g], abs=TOL)
        assert got[g].layer == "b"
    assert meta["q0"] == pytest.approx(exp["q0"], abs=TOL)
    assert meta["n_tournaments"] == 2  # B 层口径：T6 topcut NULL 不参与
    assert meta["mirror"] == "exclude"  # 无 pairings，诚实回显


def test_winrate_a_layer(env):
    db, params, exp = env
    stats, meta = winrate(db, params, layer="a")
    got = by_key(stats)
    # 仅 D1/D4 有 record，G1/G2 被二者携带；G3 无 record → 不出现
    assert set(got) == {G1, G2}
    for g in (G1, G2):
        assert got[g].value == pytest.approx(exp["wr_a"], abs=TOL)
        assert got[g].layer == "a"
        assert got[g].n == 18  # 总对局数
    assert meta["layer"] == "a"


def test_winrate_auto_resolves_a_when_records_exist(env):
    db, params, exp = env
    stats, meta = winrate(db, params, layer="auto")
    assert meta["layer"] == "a"  # 黄金集有 record → auto 走 A
    got = by_key(stats)
    assert got[G1].value == pytest.approx(exp["wr_a"], abs=TOL)


def test_winrate_auto_resolves_b_without_records(tmp_path):
    db = build_golden_db(tmp_path / "g.db")
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE deck_appearances SET record_wins=NULL, record_losses=NULL, record_ties=NULL"
    )
    conn.commit()
    conn.close()
    params = StatsParams(as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO)
    stats, meta = winrate(db, params, layer="auto")
    assert meta["layer"] == "b"
    exp = expected()
    got = by_key(stats)
    assert got[G1].value == pytest.approx(exp["wr_b"][G1], abs=1e-9)


def test_wws_b_layer(env):
    db, params, exp = env
    stats, meta = wws(db, params, layer="b")
    got = by_key(stats)
    for g in (G1, G2, G3):
        assert got[g].value == pytest.approx(exp["wws_b"][g], abs=TOL)
        assert got[g].layer == "b"


def test_wws_a_layer(env):
    db, params, exp = env
    stats, _ = wws(db, params, layer="a")
    got = by_key(stats)
    for g in (G1, G2):
        assert got[g].value == pytest.approx(exp["wws_a"][g], abs=TOL)


def test_b_layer_empty_without_topcut(tmp_path):
    """topcut_slots 全 NULL（mik 真实库现状）→ B 层诚实空结果，不产出 NULL 值。"""
    import sqlite3

    db = build_golden_db(tmp_path / "g.db")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE tournaments SET topcut_slots=NULL")
    conn.commit()
    conn.close()
    params = StatsParams(as_of=AS_OF, date_from=DATE_FROM, date_to=DATE_TO)
    stats, meta = winrate(db, params, layer="b")
    assert stats == [] and meta["n_tournaments"] == 0
    stats, meta = wws(db, params, layer="b")
    assert stats == [] and meta["n_tournaments"] == 0

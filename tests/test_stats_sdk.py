"""task 029 导出追加（赛事四件套）+ SDK stats_* 双后端契约测试（FR-9.6/9.7/FR-8）。"""

import json
import sqlite3

import pytest

from ptcgdb.export.exporter import EXPORT_FILES, export_all
from ptcgdb.sdk import open_db, open_jsonl
from tests.golden_stats import AS_OF, DATE_FROM, DATE_TO, G1, G2, build_golden_db, expected

TOL = 1e-9
WIN = {"as_of": AS_OF, "date_from": DATE_FROM, "date_to": DATE_TO}


@pytest.fixture()
def env(tmp_path):
    db = build_golden_db(tmp_path / "g.db")
    dist = tmp_path / "dist"
    manifest = export_all(db, dist)
    return db, dist, manifest, expected()


# ---- 导出追加（FR-7 只加不删）----


def test_export_tournament_four_files(env):
    _, dist, manifest, _ = env
    for name in ("tournaments", "decks", "deck_appearances", "deck_cards"):
        assert f"{name}.jsonl" in EXPORT_FILES
        assert (dist / f"{name}.jsonl").exists()
    # manifest.counts 加四项
    assert manifest["counts"]["tournaments"] == 6
    assert manifest["counts"]["decks"] == 10
    assert manifest["counts"]["deck_appearances"] == 10
    assert manifest["counts"]["deck_cards"] == 14
    # checksums 覆盖新文件
    checksums = (dist / "checksums.sha256").read_text(encoding="utf-8")
    for name in ("tournaments", "decks", "deck_appearances", "deck_cards"):
        assert f"{name}.jsonl" in checksums


def test_export_deck_cards_redundant_group_key(env):
    _, dist, _, _ = env
    rows = [
        json.loads(line)
        for line in (dist / "deck_cards.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all("group_key" in r and "stat_scope" in r for r in rows)
    row = next(r for r in rows if r["card_id"] == "GOLD-001")
    assert row["group_key"] == G1 and row["stat_scope"] == "pokemon"


def test_export_manifest_caliber_hashes(env):
    _, _, manifest, _ = env
    assert manifest["caliber"]["name_group_rules_hash"]
    assert manifest["caliber"]["tournament_tiers_hash"]


def test_export_db_has_views_and_schema_md_canonical_sql(env):
    _, dist, _, _ = env
    conn = sqlite3.connect(dist / "ptcg-cn.db")
    views = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
    }
    conn.close()
    assert {"v_stat_deck_cards", "v_tournament_weights"} <= views
    schema_md = (dist / "schema.md").read_text(encoding="utf-8")
    assert "wur.sql" in schema_md and "WUR(c)" in schema_md  # canonical SQL 附录
    assert "winrate_b.sql" in schema_md and "wws.sql" in schema_md


# ---- SDK stats_*（FR-8 Phase 2 追加）----


def test_sdk_db_backend(env):
    db, _, _, exp = env
    with open_db(db) as d:
        res = d.stats_usage(**WIN)
        assert res.meta["as_of"] == AS_OF
        assert res.meta["name_group_rules_hash"]
        got = {s.group_key: s for s in res.data}
        assert got[G1].value == pytest.approx(exp["wur"][G1], abs=TOL)
        assert got[G2].n == 4

        wr = d.stats_winrate(layer="b", **WIN)
        assert wr.meta["layer"] == "b"
        got_wr = {s.group_key: s for s in wr.data}
        assert got_wr[G1].value == pytest.approx(exp["wr_b"][G1], abs=TOL)

        wws_res = d.stats_wws(layer="b", **WIN)
        got_wws = {s.group_key: s for s in wws_res.data}
        assert got_wws[G1].value == pytest.approx(exp["wws_b"][G1], abs=TOL)

        drill = d.stats_card(G1, **WIN)
        assert len(drill.data) == 3
        assert drill.data[0].tournament_id.startswith("mik_moe:")


def test_sdk_jsonl_backend_contract(env):
    db, dist, _, _ = env
    with open_db(db) as d_db, open_jsonl(dist) as d_jsonl:
        for call in (
            lambda d: d.stats_usage(**WIN),
            lambda d: d.stats_usage(usage_basis="copies", **WIN),
            lambda d: d.stats_winrate(layer="a", **WIN),
            lambda d: d.stats_winrate(layer="b", **WIN),
            lambda d: d.stats_winrate(**WIN),  # auto
            lambda d: d.stats_wws(layer="a", **WIN),
            lambda d: d.stats_wws(layer="b", **WIN),
        ):
            r_db, r_jsonl = call(d_db), call(d_jsonl)
            assert r_db.data == r_jsonl.data
            assert r_db.meta == r_jsonl.meta
        drill_db = d_db.stats_card(G1, **WIN)
        drill_jsonl = d_jsonl.stats_card(G1, **WIN)
        assert drill_db.data == drill_jsonl.data
        assert drill_db.meta == drill_jsonl.meta


def test_sdk_jsonl_without_tournament_files(tmp_path):
    """旧版导出（无赛事四件套）调 stats_* 给出明确错误，不崩溃。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "manifest.json").write_text(
        json.dumps({"version": "v1", "schema_version": "1.0.0"}), encoding="utf-8"
    )
    for name in ("cards", "sets", "relations"):
        (dist / f"{name}.jsonl").write_text("", encoding="utf-8")
    (dist / "legality.json").write_text(
        json.dumps({"data": {"snapshots": []}}), encoding="utf-8"
    )
    with open_jsonl(dist) as d:
        with pytest.raises(LookupError, match="tournaments.jsonl"):
            d.stats_usage(**WIN)

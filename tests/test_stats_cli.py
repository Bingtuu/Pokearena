"""CLI：stats 子命令组（裸调用兼容 overview）+ query 只读 SQL（FR-9.7）。"""

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from ptcgdb import cli
from tests.golden_stats import AS_OF, DATE_FROM, DATE_TO, G1, G2, build_golden_db, expected

runner = CliRunner()
WINDOW = ["--as-of", AS_OF, "--from", DATE_FROM, "--to", DATE_TO]


@pytest.fixture()
def db(tmp_path):
    return build_golden_db(tmp_path / "g.db")


def test_stats_bare_compat_overview(db):
    result = runner.invoke(cli.app, ["stats", "--db-path", str(db)])
    assert result.exit_code == 0
    assert "cards" in result.output  # overview 对账输出
    # 与显式 overview 一致
    explicit = runner.invoke(cli.app, ["stats", "overview", "--db-path", str(db)])
    assert explicit.exit_code == 0
    assert result.output == explicit.output


def test_stats_usage_table(db):
    result = runner.invoke(cli.app, ["stats", "usage", *WINDOW, "--db-path", str(db)])
    assert result.exit_code == 0
    assert G1 in result.output and G2 in result.output
    assert "as_of" in result.output  # meta 回显


def test_stats_usage_json(db):
    result = runner.invoke(
        cli.app, ["stats", "usage", *WINDOW, "--format", "json", "--db-path", str(db)]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    exp = expected()
    assert payload["meta"]["as_of"] == AS_OF
    assert payload["meta"]["usage_basis"] == "decks"
    assert payload["meta"]["n_tournaments"] == 3
    assert payload["meta"]["name_group_rules_hash"]
    got = {r["group_key"]: r for r in payload["data"]}
    assert got[G1]["value"] == pytest.approx(exp["wur"][G1], abs=1e-9)
    assert got[G1]["n"] == 4


def test_stats_winrate_and_wws(db):
    result = runner.invoke(
        cli.app,
        ["stats", "winrate", *WINDOW, "--layer", "b", "--format", "json",
         "--db-path", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    exp = expected()
    assert payload["meta"]["layer"] == "b"
    assert payload["meta"]["q0"] == pytest.approx(exp["q0"], abs=1e-9)
    got = {r["group_key"]: r for r in payload["data"]}
    assert got[G1]["value"] == pytest.approx(exp["wr_b"][G1], abs=1e-9)

    result = runner.invoke(
        cli.app,
        ["stats", "wws", *WINDOW, "--layer", "b", "--format", "json",
         "--db-path", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    got = {r["group_key"]: r for r in payload["data"]}
    assert got[G1]["value"] == pytest.approx(exp["wws_b"][G1], abs=1e-9)


def test_stats_card_drilldown(db):
    result = runner.invoke(
        cli.app, ["stats", "card", G1, *WINDOW, "--format", "json", "--db-path", str(db)]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"]["group_key"] == G1
    rows = payload["data"]
    assert len(rows) == 3  # T1/T2/T6 三场有 G1 出战
    t1 = next(r for r in rows if r["tournament_id"].endswith("9001"))
    assert t1["n_decks"] == 2 and t1["best_rank"] == 1 and t1["topcut_decks"] == 1


def test_stats_usage_csv(db):
    result = runner.invoke(
        cli.app, ["stats", "usage", *WINDOW, "--format", "csv", "--db-path", str(db)]
    )
    assert result.exit_code == 0
    assert "group_key,display_name,value,n" in result.output.splitlines()[0]


# ---- ptcgdb query ----


def test_query_select(db):
    result = runner.invoke(
        cli.app,
        ["query", "SELECT count(*) AS c FROM decks", "--format", "json",
         "--db-path", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"][0]["c"] == 10


def test_query_with_cte(db):
    result = runner.invoke(
        cli.app,
        ["query", "WITH x AS (SELECT 1 AS one) SELECT * FROM x", "--format", "json",
         "--db-path", str(db)],
    )
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM decks",
        "UPDATE decks SET source='x'",
        "INSERT INTO decks (deck_id) VALUES ('x')",
        "DROP TABLE decks",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "SELECT 1; DELETE FROM decks",
    ],
)
def test_query_rejects_writes(db, sql):
    result = runner.invoke(cli.app, ["query", sql, "--db-path", str(db)])
    assert result.exit_code != 0
    # 数据库未被修改（只读打开）
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM decks").fetchone()[0] == 10
    conn.close()


def test_query_limit(db):
    result = runner.invoke(
        cli.app,
        ["query", "SELECT * FROM decks", "--limit", "3", "--format", "json",
         "--db-path", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["data"]) == 3
    assert payload["meta"]["truncated"] is True


def test_init_db_writes_caliber_hashes(tmp_path):
    db = tmp_path / "fresh.db"
    result = runner.invoke(cli.app, ["init-db", "--db-path", str(db)])
    assert result.exit_code == 0
    conn = sqlite3.connect(db)
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()
    assert meta["name_group_rules_hash"]
    assert meta["tournament_tiers_hash"]
    assert conn

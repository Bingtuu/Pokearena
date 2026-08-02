"""迁移测试：连续执行两次幂等、user_version 正确、全部表与索引存在。"""

import sqlite3

from ptcgdb.migrations import apply_migrations, available_migrations

EXPECTED_TABLES = {
    "sets",
    "cards",
    "card_relations",
    "name_groups",
    "cards_name_group",
    "legality_snapshots",
    "errata",
    "rules_documents",
    "scrape_runs",
    "external_ids",
    "meta",
    "tournaments",
    "decks",
    "deck_appearances",
    "deck_cards",
}

EXPECTED_INDEXES = {
    "ix_cards_name_full",
    "ix_cards_set_id",
    "ix_cards_regulation_mark",
    "ix_cards_species",
    "ix_cards_status",
    "ix_cards_is_basic_energy",
    "ix_cards_is_tera",
    "ix_card_relations_related_card_id",
    "ix_legality_snapshots_format_effective_from",
    "ix_deck_appearances_tournament_id",
    "ix_deck_cards_card_id",
}


def test_migrations_idempotent(tmp_path):
    db_path = tmp_path / "test.db"

    assert available_migrations()[0][0] == 1
    latest = available_migrations()[-1][0]

    first = apply_migrations(db_path)
    assert first == latest

    # 重复执行不报错、user_version 不变
    second = apply_migrations(db_path)
    assert second == latest

    conn = sqlite3.connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == latest

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert EXPECTED_TABLES <= tables

        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert EXPECTED_INDEXES <= indexes
    finally:
        conn.close()

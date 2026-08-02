"""迁移 004+005 测试：tournaments / decks / deck_appearances / deck_cards（PRD §7.5，task 027）。

列名、可空性、主键与外键逐一对照 PRD §7.5（v1.10 续：decks=卡组内容实体，
deck_appearances=出战条目——mik deckId 实测为内容实体，多名选手/多场赛事可共用）。
视图属 task 029 范围，迁移 004/005 不含。
"""

import sqlite3

from ptcgdb.migrations import apply_migrations

# 注：SQLite 对非 INTEGER 的 PRIMARY KEY 列不把 notnull 置 1（历史行为，PRD SQL 原文
# 也未写 NOT NULL），故 PK 列 notnull 期望为 0，主键约束由 pk 标志单独校验。
TOURNAMENTS_COLUMNS = [
    ("tournament_id", 0),  # (列名, notnull)；PRIMARY KEY
    ("source", 1),
    ("series_id", 0),
    ("name", 1),
    ("tier", 0),
    ("tier_coef", 0),
    ("division", 0),
    ("date", 0),
    ("location", 0),
    ("participant_count", 0),
    ("topcut_slots", 0),
    ("format", 0),
    ("regulation_mark", 0),
    ("format_end", 0),
    ("is_qual", 0),
    ("is_team", 0),
    ("official_url", 0),
    ("fetched_at", 0),
]

DECKS_COLUMNS = [  # 卡组内容实体（同一套 60 张清单全源一行）
    ("deck_id", 0),  # PRIMARY KEY（notnull 标志同上说明）
    ("archetype_id", 0),
    ("archetype_name", 0),
    ("deck_code", 0),
    ("mapping_status", 1),
    ("mapped_ratio", 0),
    ("source", 1),
    ("fetched_at", 0),
]

DECK_APPEARANCES_COLUMNS = [  # 出战条目：一套内容在一次赛事取得的一个名次
    ("deck_id", 1),
    ("tournament_id", 1),
    ("rank", 1),
    ("points", 0),
    ("player_ref", 0),
    ("record_wins", 0),
    ("record_losses", 0),
    ("record_ties", 0),
    ("source", 1),
    ("fetched_at", 0),
]

DECK_CARDS_COLUMNS = [
    ("deck_id", 1),
    ("card_id", 0),  # 可空：映射不上不猜（FR-9.2）
    ("count", 1),
    ("raw_name", 1),
    ("stat_scope", 1),
]


def _columns(conn, table):
    """PRAGMA table_info → [(name, notnull)]，按定义顺序。"""
    return [(r[1], r[3]) for r in conn.execute(f"PRAGMA table_info({table})")]


def _apply(tmp_path):
    db_path = tmp_path / "test.db"
    version = apply_migrations(db_path)
    return db_path, version


def test_migration_005_user_version(tmp_path):
    _, version = _apply(tmp_path)
    assert version == 5


def test_migration_005_columns(tmp_path):
    db_path, _ = _apply(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        assert _columns(conn, "tournaments") == TOURNAMENTS_COLUMNS
        assert _columns(conn, "decks") == DECKS_COLUMNS
        assert _columns(conn, "deck_appearances") == DECK_APPEARANCES_COLUMNS
        assert _columns(conn, "deck_cards") == DECK_CARDS_COLUMNS
    finally:
        conn.close()


def test_migration_005_primary_keys_and_foreign_keys(tmp_path):
    db_path, _ = _apply(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        for table, pk_col in (("tournaments", "tournament_id"), ("decks", "deck_id")):
            pk = {
                r[1]
                for r in conn.execute(f"PRAGMA table_info({table})")
                if r[5]  # pk 序号非 0
            }
            assert pk == {pk_col}

        pk = {
            r[1]
            for r in conn.execute("PRAGMA table_info(deck_appearances)")
            if r[5]
        }
        assert pk == {"deck_id", "tournament_id", "rank"}

        pk = {
            r[1]
            for r in conn.execute("PRAGMA table_info(deck_cards)")
            if r[5]
        }
        assert pk == {"deck_id", "card_id", "raw_name"}

        app_fks = {
            (r[2], r[3]) for r in conn.execute("PRAGMA foreign_key_list(deck_appearances)")
        }
        assert ("decks", "deck_id") in app_fks
        assert ("tournaments", "tournament_id") in app_fks

        card_fks = {
            (r[2], r[3]) for r in conn.execute("PRAGMA foreign_key_list(deck_cards)")
        }
        assert ("decks", "deck_id") in card_fks
        assert ("cards", "card_id") in card_fks
    finally:
        conn.close()


def test_migration_005_indexes(tmp_path):
    db_path, _ = _apply(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        indexes = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {"ix_deck_appearances_tournament_id", "ix_deck_cards_card_id"} <= indexes
        assert "ix_decks_tournament_id" not in indexes  # 004 旧表已重建
    finally:
        conn.close()


def test_migration_005_idempotent_and_null_card_id(tmp_path):
    db_path, _ = _apply(tmp_path)
    # 重复执行不报错（DROP/CREATE 均 IF EXISTS/IF NOT EXISTS）
    assert apply_migrations(db_path) == 5

    conn = sqlite3.connect(db_path)
    try:
        # deck_cards 复合主键含可空 card_id（SQLite 允许），映射不上的卡可落库
        conn.execute(
            "INSERT INTO tournaments (tournament_id, source, name) VALUES (?, ?, ?)",
            ("mik_moe:8801", "mik_moe", "测试赛"),
        )
        conn.execute(
            "INSERT INTO decks (deck_id, mapping_status, source) VALUES (?, ?, ?)",
            ("mik_moe:555001", "full", "mik_moe"),
        )
        conn.execute(
            "INSERT INTO deck_appearances (deck_id, tournament_id, rank, source)"
            " VALUES (?, ?, ?, ?)",
            ("mik_moe:555001", "mik_moe:8801", 1, "mik_moe"),
        )
        conn.execute(
            "INSERT INTO deck_cards (deck_id, card_id, count, raw_name, stat_scope)"
            " VALUES (?, NULL, ?, ?, ?)",
            ("mik_moe:555001", 4, "某未映射卡", "other"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT card_id, raw_name FROM deck_cards WHERE deck_id = 'mik_moe:555001'"
        ).fetchone()
        assert row == (None, "某未映射卡")
        # 同一内容在同一赛事的另一名次 = 第二条出战条目（复合主键不冲突）
        conn.execute(
            "INSERT INTO deck_appearances (deck_id, tournament_id, rank, source)"
            " VALUES (?, ?, ?, ?)",
            ("mik_moe:555001", "mik_moe:8801", 53, "mik_moe"),
        )
        conn.commit()
        assert conn.execute(
            "SELECT count(*) FROM deck_appearances WHERE deck_id = 'mik_moe:555001'"
        ).fetchone()[0] == 2
    finally:
        conn.close()

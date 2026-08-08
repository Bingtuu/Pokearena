"""task 028 扩展测试：Limitless 主站 HTML 收录入库管线（ingest_limitless_site）。

全部零网络：ptcd/limitless_site raw 树与 CN 库都在 tmp_path 手工构建（风格照
test_ingest_limitless.py）。覆盖：
- migration 010 视图 basis（limitless_site→intl_aligned，原三映射不变，jsonldb 一致）
  ——见 tests/test_tournament_migration.py 010 段；
- 全流程：一场 regional（standings 35 行 → 截断 32，truncated=3，topcut_slots=
  截断后实际入库名次数）+ 一场 league_cup（10 行 → 截断 8）+ 一场未知 tier
  （不截断 + warning，不猜）+ 一场缺索引条目（最小入库）；
- 字段断言：record 三列 NULL、env=GHI、official_url、tier_coef 物化、division NULL、
  deck 内容去重（两人同表 = 1 内容行 + N 出战行）、60 张门、卡组快照缺失拦截、
  映射分档、幂等两遍一致；
- finish_run source 参数化（传/不传两例，task 028 顺带小修）。
"""

import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from ptcgdb import cli
from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.ingest_limitless_site import (
    SITE_CUT_LIMITS,
    ingest_limitless_site,
    make_deck_id,
)
from ptcgdb.orm import Card, Deck, DeckAppearance, DeckCard, ScrapeRun, Set, Tournament
from ptcgdb.scrapers.raw_store import write_raw
from ptcgdb.scrapers.runner import RunStats, _new_run_id, finish_run

NOW = datetime(2026, 8, 8, 12, 0, 0)

T_REG = "559"  # regional 1974 人，2026-03-30（EN env GHI）→ 截断 32
T_CUP = "600"  # league_cup 48 人，2026-03-15 → 截断 8
T_MISC = "601"  # 未知 tier（非官方名）→ 不截断 + warning
T_NOIDX = "699"  # 缺索引条目 → 最小入库

# ---- ptcd / limitless_site raw 树构建（tmp_path，零网络）----


def write_ptcd_raw(raw_dir: Path) -> None:
    base = raw_dir / "pokemon-tcg-data"
    (base / "cards-en").mkdir(parents=True, exist_ok=True)
    (base / "sets-en.json").write_text(
        json.dumps({"sets": [{"id": "sv1", "ptcgoCode": "SVI", "releaseDate": "2023/03/31"}]}),
        encoding="utf-8",
    )
    (base / "cards-en" / "sv1.json").write_text(
        json.dumps(
            {
                "cards": [
                    {"id": "sv1-185", "name": "Ultra Ball", "number": "185",
                     "supertype": "Trainer", "regulationMark": "G"},
                    {"id": "sv1-1", "name": "Basic Psychic Energy", "number": "1",
                     "supertype": "Energy", "regulationMark": "G"},
                    {"id": "sv1-57", "name": "Slowpoke", "number": "057",
                     "supertype": "Pokémon", "regulationMark": "G"},
                ]
            }
        ),
        encoding="utf-8",
    )


def make_cards(spec):
    """spec = [(count, set, number, name, section)] → 主站卡组快照 cards 形态。"""
    return [
        {"count": count, "set": set_code, "number": number, "name": name, "section": section}
        for count, set_code, number, name, section in spec
    ]


def make_standing(placing, player, decklist_id, archetype_id="326"):
    return {
        "placing": placing,
        "player": player,
        "country": "US",
        "archetype_name": "Some Archetype",
        "deck_url": f"/decks/list/{decklist_id}",
        "decklist_id": decklist_id,
        "archetype_url": f"/decks/{archetype_id}",
        "archetype_id": archetype_id,
    }


def write_site_raw(raw_dir, index_entries=None, standings=None, decklists=None):
    base = raw_dir / "limitless_site"
    if index_entries is not None:
        write_raw(
            base / "tournaments" / "index" / "2526" / "page-1.json",
            {"season": "2526", "page": 1, "entries": index_entries},
            source="limitless_site",
        )
    for tid, payload in (standings or {}).items():
        write_raw(
            base / "tournaments" / "standings" / f"{tid}.json", payload,
            source="limitless_site",
        )
    for did, payload in (decklists or {}).items():
        write_raw(
            base / "decks" / "list" / f"{did}.json", payload,
            source="limitless_site",
        )


def index_entry(tid, name, players, day):
    return {
        "tournament_id": tid, "name": name, "date": day, "players": players,
        "country": "US", "url": f"/tournaments/{tid}",
    }


# ---- CN 库（cards.name_en 桥 + sets.release_date）----


def make_card(card_id, set_id, name_en, mark, *, ctype="pokemon", subtype=None):
    return Card(
        card_id=card_id, set_id=set_id, number=card_id.rsplit("-", 1)[1],
        number_display="001/100", name_full=card_id, card_type=ctype,
        regulation_mark=mark, rarity="R", trainer_subtype=subtype,
        has_rule_box=False, is_tera=False, prize_cards=1, deck_limit=4,
        is_ace_spec=False, is_basic_energy=False, text_raw="", name_en=name_en,
        source="test", fetched_at=NOW, status="active",
    )


def build_db(db_path):
    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for set_id, release in (("CSA", date(2023, 6, 1)), ("CSB", date(2025, 1, 1)),
                                ("CSJ", date(2026, 2, 1))):
            session.add(Set(
                set_id=set_id, name_zh="测试包", era="朱&紫", release_date=release,
                regulation_mark="G", source="test", fetched_at="2026-08-08",
            ))
        session.add_all([
            make_card("CSA-001", "CSA", "Ultra Ball", "G", ctype="trainer", subtype="物品"),
            make_card("CSB-002", "CSB", "Ultra Ball", "H", ctype="trainer", subtype="物品"),
            make_card("CSA-004", "CSA", "Psychic Energy", "G", ctype="energy"),
            make_card("CSA-005", "CSA", "Slowpoke", "G"),
            make_card("CSJ-008", "CSJ", "Milotic ex", "J"),  # J 标：env 交叉校验告警用
        ])
        session.commit()
    engine.dispose()


def query_all(db_path, model):
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        rows = list(session.scalars(select(model)))
    engine.dispose()
    return rows


# ---- 卡组快照（DECK_A partial / DECK_B partial+J 标 / DECK_C 59 张 / DECK_D full）----

DECK_A = make_cards([
    (4, "SVI", "057", "Slowpoke", "Pokémon"),
    (4, "SVI", "185", "Ultra Ball", "Trainer"),
    (7, "XXX", "999", "Boss's Orders", "Trainer"),  # name_fallback：CN 库无 → unmapped
    (45, "SVI", "1", "Basic Psychic Energy", "Energy"),
])  # 合计 60，mapped 53/60 → partial
DECK_B = make_cards([
    (55, "SVI", "1", "Basic Psychic Energy", "Energy"),
    (1, "XXX", "1", "Milotic ex", "Pokémon"),  # J 标 → env 交叉校验告警
    (4, "XXX", "2", "Nonexistent Card", "Trainer"),  # unmapped
])  # 合计 60，mapped 56/60 → partial
DECK_C = make_cards([(59, "SVI", "1", "Basic Psychic Energy", "Energy")])  # 59 → 60 张门
DECK_D = make_cards([
    (4, "SVI", "057", "Slowpoke", "Pokémon"),
    (56, "SVI", "1", "Basic Psychic Energy", "Energy"),
])  # 合计 60 全映射 → full


def decklist_payload(did, archetype, player, cards):
    return {"decklist_id": did, "archetype": archetype, "player": player, "cards": cards}


def build_full_fixture(tmp_path):
    """regional 35 行 + league_cup 10 行 + 未知 tier 3 行 + 缺索引 1 行。"""
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    write_ptcd_raw(raw_dir)
    reg_rows = (
        [make_standing(1, "alice", "28249"),
         make_standing(2, "bob", "28249"),  # 同表 → 内容去重
         make_standing(3, "carol", "28236"),
         make_standing(4, "dave", "28250"),  # DECK_C 59 张 → 60 张门
         make_standing(5, "erin", "28299")]  # 快照缺失 → blocked
        + [make_standing(p, f"p{p:02d}", "28249") for p in range(6, 33)]  # 截断内
        + [make_standing(p, f"cut{p}", "28249") for p in range(33, 36)]  # 截断外 ×3
    )
    cup_rows = [make_standing(p, f"cup{p:02d}", "28300") for p in range(1, 11)]  # 截断 8
    misc_rows = [make_standing(p, f"misc{p}", "28300") for p in range(1, 4)]  # 不截断
    write_site_raw(
        raw_dir,
        index_entries=[
            index_entry(T_REG, "Regional Indianapolis, IN", 1974, "2026-03-30"),
            index_entry(T_CUP, "Toronto League Cup", 48, "2026-03-15"),
            index_entry(T_MISC, "Professor Oak Casual Meetup", 120, "2026-03-20"),
        ],
        standings={
            T_REG: {"tournament_id": T_REG, "name": "Regional Indianapolis, IN",
                    "standings": reg_rows},
            T_CUP: {"tournament_id": T_CUP, "name": "Toronto League Cup",
                    "standings": cup_rows},
            T_MISC: {"tournament_id": T_MISC, "name": "Professor Oak Casual Meetup",
                     "standings": misc_rows},
            T_NOIDX: {"tournament_id": T_NOIDX, "name": None,
                      "standings": [make_standing(1, "noidx", "28300")]},
        },
        decklists={
            "28249": decklist_payload("28249", "Slowpoke Control", "alice", DECK_A),
            "28236": decklist_payload("28236", "Mystery Box", "carol", DECK_B),
            "28250": decklist_payload("28250", "Short Deck", "dave", DECK_C),
            "28300": decklist_payload("28300", "Cup Deck", "cup01", DECK_D),
            # 28299 快照缺失（blocked）
        },
    )
    build_db(db_path)
    return raw_dir, db_path


# ---- 全流程 ----


def test_ingest_full_flow(tmp_path):
    raw_dir, db_path = build_full_fixture(tmp_path)
    result = ingest_limitless_site(raw_dir, db_path)

    assert result.tournaments == 4
    assert result.truncated == 5  # regional 33~35（3）+ league_cup 9~10（2）
    assert result.cut_limits == SITE_CUT_LIMITS  # 截断档位回显
    assert result.decks == 5  # 内容实体处理次数（同 API 口径）：A/B 各 1 + D×3 场
    # （DB 唯一内容行 = 3：DECK_A/B/D；DECK_C 60 张门拦截）
    # appearances：regional 30（32 截断内 − dave 60 张门 − erin 快照缺失）
    # + cup 8 + misc 3 + noidx 1 = 42
    assert result.appearances == 42
    blocked_reasons = [b["reason"] for b in result.blocked]
    assert len(result.blocked) == 2
    assert any("60 张质量门" in r for r in blocked_reasons)
    assert any("卡组快照缺失" in r for r in blocked_reasons)
    snap_blocked = next(b for b in result.blocked if "卡组快照缺失" in b["reason"])
    assert snap_blocked["decklist_id"] == "28299"

    tours = {t.tournament_id: t for t in query_all(db_path, Tournament)}
    reg = tours[f"limitless_site:{T_REG}"]
    assert reg.tier == "regional"
    assert reg.tier_coef == 1.5  # 词表物化（FR-9.4 Regional=1.5）
    assert reg.topcut_slots == 30  # 截断后实际入库名次数（32 − 2 拦截）
    assert reg.participant_count == 1974
    assert reg.env == "GHI"  # 2026-03-30 命中 EN G/H/I 段
    assert reg.division is None
    assert reg.format == "standard"
    assert reg.official_url == f"https://limitlesstcg.com/tournaments/{T_REG}"
    cup = tours[f"limitless_site:{T_CUP}"]
    assert cup.tier == "league_cup"
    assert cup.tier_coef == 1.0
    assert cup.topcut_slots == 8  # league_cup 截断 8
    misc = tours[f"limitless_site:{T_MISC}"]
    assert misc.tier is None and misc.tier_coef is None  # 未知 tier 不猜
    assert misc.topcut_slots == 3  # 不截断（截断代理不适用，如实计数）
    assert any("tier 归类未命中" in w for w in result.warnings)
    noidx = tours[f"limitless_site:{T_NOIDX}"]
    assert noidx.tier is None and noidx.date is None and noidx.participant_count is None
    assert noidx.topcut_slots == 1  # 最小入库照常物化
    assert any("缺索引条目" in w for w in result.warnings)

    # 内容去重：DECK_A 一行内容，alice/bob + p06~p32 共 29 行出战
    deck_a_id = make_deck_id(DECK_A)
    decks = {d.deck_id: d for d in query_all(db_path, Deck)}
    assert decks[deck_a_id].archetype_name == "Slowpoke Control"  # 卡组页标题解析
    assert decks[deck_a_id].archetype_id == "326"  # standings 行源侧归类 id
    assert decks[deck_a_id].deck_code is None
    assert decks[deck_a_id].source == "limitless_site"
    # DECK_A：Boss's Orders unmapped（7/60）→ partial
    assert decks[deck_a_id].mapping_status == "partial"
    deck_d_id = make_deck_id(DECK_D)
    assert decks[deck_d_id].mapping_status == "full"
    assert decks[deck_d_id].mapped_ratio == 1.0

    apps = [
        a for a in query_all(db_path, DeckAppearance)
        if a.tournament_id == f"limitless_site:{T_REG}"
    ]
    assert len(apps) == 30
    by_player = {a.player_ref: a for a in apps}
    assert by_player["alice"].rank == 1 and by_player["bob"].rank == 2
    assert by_player["alice"].deck_id == by_player["bob"].deck_id == deck_a_id
    # record 三列 NULL + points NULL（主站收录无比分，不猜）
    assert (by_player["alice"].record_wins, by_player["alice"].record_losses,
            by_player["alice"].record_ties) == (None, None, None)
    assert by_player["alice"].points is None
    assert by_player["alice"].source == "limitless_site"
    assert "dave" not in by_player and "erin" not in by_player  # 拦截不落
    assert not any(a.rank > 32 for a in apps)  # 截断外不入库
    cup_apps = [
        a for a in query_all(db_path, DeckAppearance)
        if a.tournament_id == f"limitless_site:{T_CUP}"
    ]
    assert len(cup_apps) == 8
    assert max(a.rank for a in cup_apps) == 8  # league_cup 截断 8

    # env 交叉校验告警（DECK_B J 标不在 GHI，不拒收）
    assert any("交叉校验告警" in w and "J" in w for w in result.warnings)
    # 映射决策分布（60 张门在映射前拦截，DECK_C 不计）
    assert result.mapping_rules.get("unmapped", 0) == 2  # Boss's Orders + Nonexistent Card
    assert result.unknown_cards


def test_ingest_idempotent(tmp_path):
    raw_dir, db_path = build_full_fixture(tmp_path)
    result1 = ingest_limitless_site(raw_dir, db_path)
    counts1 = {m.__tablename__: len(query_all(db_path, m))
               for m in (Tournament, Deck, DeckAppearance, DeckCard)}
    result2 = ingest_limitless_site(raw_dir, db_path)
    counts2 = {m.__tablename__: len(query_all(db_path, m))
               for m in (Tournament, Deck, DeckAppearance, DeckCard)}
    assert counts1 == counts2
    assert result2.tournaments == result1.tournaments
    assert result2.decks == result1.decks
    assert result2.appearances == result1.appearances == 42
    assert result2.deck_cards == result1.deck_cards
    assert result2.truncated == result1.truncated == 5
    assert result2.mapping_rules == result1.mapping_rules
    # topcut_slots 物化幂等：重跑后 regional 仍 = 30
    tours = {t.tournament_id: t for t in query_all(db_path, Tournament)}
    assert tours[f"limitless_site:{T_REG}"].topcut_slots == 30


def test_cli_ingest_limitless_site(tmp_path):
    raw_dir, db_path = build_full_fixture(tmp_path)
    result = CliRunner().invoke(
        cli.app,
        ["ingest-limitless-site", "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    assert result.exit_code == 1  # 有质量门拦截 → 非零退出
    assert "tournaments=4" in result.output
    assert "appearances=42" in result.output
    assert "truncated=5" in result.output
    assert "blocked=2" in result.output


# ---- finish_run source 参数化（task 028 顺带小修）----


def test_finish_run_source_default_and_explicit(tmp_path):
    run_id, started_at = _new_run_id()
    # 不传 source：保持历史默认 mik_moe（向后兼容）
    finish_run(tmp_path / "raw", tmp_path / "t.db", run_id, started_at, RunStats())
    # 显式传：limitless_site 落各自 source
    run_id2, started_at2 = _new_run_id()
    finish_run(
        tmp_path / "raw", tmp_path / "t.db", run_id2, started_at2, RunStats(),
        source="limitless_site",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    with Session(engine) as session:
        assert session.get(ScrapeRun, run_id).source == "mik_moe"
        assert session.get(ScrapeRun, run_id2).source == "limitless_site"
    engine.dispose()

"""task 028 步骤 3+4 测试：Limitless decklist→简中映射链 + 入库管线。

全部零网络：ptcd/limitless raw 树与 CN 库都在 tmp_path 手工构建（风格照
test_tournament_ingest.py / test_envs.py）。覆盖：
- 映射链单测：ptcd 定位（含前导零变体）/ name_fallback / basic_energy_alias /
  多候选 env 优先 / 无 env 最新印刷 / release_date 并列字典序兜底 / unmapped；
- 全流程：一场 regional 赛事三卡组（一 full 两人同卡组、一 partial 带 J 标、
  一 59 张被 60 张门拦截）；record 三列/玩家名落库；env=GHI；交叉校验告警；
  tier_coef 物化 regional=1.5；mapping_rules 分布；幂等两遍一致；
- 缺 list 条目 → 最小入库 + warning（照 mik 口径）。
"""

import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from ptcgdb import cli
from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize.ingest_limitless import ingest_limitless, make_deck_id
from ptcgdb.normalize.limitless import (
    CnCandidate,
    load_ptcd_index,
    map_decklist_card,
    parse_standings_entry,
)
from ptcgdb.orm import Card, Deck, DeckAppearance, DeckCard, Set, Tournament
from ptcgdb.scrapers.raw_store import write_raw

NOW = datetime(2026, 8, 7, 12, 0, 0)
ENV_GHI = ("G", "H", "I")

T_A = "aaaaaaaaaaaaaaaaaaaaaaa1"  # regional 850 人，2026-03-15（EN env GHI）
T_B = "bbbbbbbbbbbbbbbbbbbbbbb2"  # 缺 list 条目的赛事

# ---- ptcd / limitless raw 树构建（tmp_path，零网络）----


def write_ptcd_raw(raw_dir: Path) -> None:
    base = raw_dir / "pokemon-tcg-data"
    (base / "cards-en").mkdir(parents=True, exist_ok=True)
    (base / "sets-en.json").write_text(
        json.dumps(
            {
                "sets": [
                    {"id": "sv1", "ptcgoCode": "SVI", "releaseDate": "2023/03/31"},
                    {"id": "sv6", "ptcgoCode": "TWM", "releaseDate": "2024/05/24"},
                ]
            }
        ),
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
    (base / "cards-en" / "sv6.json").write_text(
        json.dumps(
            {
                "cards": [
                    {"id": "sv6-18", "name": "Dipplin", "number": "18",
                     "supertype": "Pokémon", "regulationMark": "H"},
                ]
            }
        ),
        encoding="utf-8",
    )


def make_decklist(cards):
    """cards = [(section, count, set, number, name)] → Limitless decklist 形态。"""
    decklist: dict[str, list] = {"pokemon": [], "trainer": [], "energy": []}
    for section, count, set_code, number, name in cards:
        decklist[section].append(
            {"count": count, "set": set_code, "number": number, "name": name}
        )
    return decklist


def make_standing(placing, player, record, deck, decklist):
    return {
        "name": f"{player} display",
        "country": "US",
        "player": player,
        "placing": placing,
        "record": record,
        "drop": None,
        "deck": deck,
        "decklist": decklist,
    }


def write_limitless_raw(raw_dir, list_entries=None, standings=None):
    base = raw_dir / "limitless" / "tournaments"
    if list_entries is not None:
        write_raw(base / "list" / "page-0001.json", {"data": list_entries},
                  source="limitless")
    for tid, entries in (standings or {}).items():
        write_raw(base / "standings" / f"{tid}.json", {"data": entries},
                  source="limitless")


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
        for set_id, release in (
            ("CSA", date(2023, 6, 1)),
            ("CSB", date(2025, 1, 1)),
            ("CSC", date(2026, 1, 1)),
            ("CSD", date(2023, 6, 1)),
            ("CSE", date(2024, 1, 1)),
            ("CSF", date(2024, 6, 1)),
            ("CSJ", date(2026, 2, 1)),
        ):
            session.add(Set(
                set_id=set_id, name_zh="测试包", era="朱&紫", release_date=release,
                regulation_mark="G", source="test", fetched_at="2026-08-07",
            ))
        session.add_all([
            # Ultra Ball 三印刷：G@2023 / H@2025 / F@2026（env 优先裁决用）
            make_card("CSA-001", "CSA", "Ultra Ball", "G", ctype="trainer", subtype="物品"),
            make_card("CSB-002", "CSB", "Ultra Ball", "H", ctype="trainer", subtype="物品"),
            make_card("CSC-003", "CSC", "Ultra Ball", "F", ctype="trainer", subtype="物品"),
            make_card("CSD-004", "CSD", "Psychic Energy", "G", ctype="energy"),
            make_card("CSE-005", "CSE", "Slowpoke", "G"),
            make_card("CSF-006", "CSF", "Boss's Orders", "G", ctype="trainer", subtype="支援者"),
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


# ---- 映射链单测（cn_name_index 手工构建）----

CN_INDEX = {
    "Ultra Ball": [
        CnCandidate("CSA-001", "G", date(2023, 6, 1)),
        CnCandidate("CSB-002", "H", date(2025, 1, 1)),
        CnCandidate("CSC-003", "F", date(2026, 1, 1)),
    ],
    "Psychic Energy": [CnCandidate("CSD-004", "G", date(2023, 6, 1))],
    "Slowpoke": [CnCandidate("CSE-005", "G", date(2024, 1, 1))],
    "Boss's Orders": [CnCandidate("CSF-006", "G", date(2024, 6, 1))],
    "Tiepuff": [  # release_date 并列 → card_id 字典序最小者
        CnCandidate("CSTB-010", "G", date(2024, 1, 1)),
        CnCandidate("CSTA-009", "G", date(2024, 1, 1)),
    ],
}


def load_test_ptcd_index(tmp_path):
    write_ptcd_raw(tmp_path)
    return load_ptcd_index(tmp_path)


def test_ptcd_index_loads_with_number_variants(tmp_path):
    set_map, card_index = load_test_ptcd_index(tmp_path)
    assert set_map == {"SVI": "sv1", "TWM": "sv6"}
    assert card_index[("SVI", "185")]["name"] == "Ultra Ball"
    # 前导零变体：ptcd number="057"，三种写法都能命中同一条目
    assert card_index[("SVI", "057")]["name"] == "Slowpoke"
    assert card_index[("SVI", "57")]["name"] == "Slowpoke"


def test_map_ptcd_exact_env_preferred(tmp_path):
    _, ptcd_index = load_test_ptcd_index(tmp_path)
    # ptcd 定位纠正 decklist 自带名；env GHI 排除 F 印刷 → H 印刷（子集内最新）
    card_id, rule = map_decklist_card("SVI", "185", "Ultra Balll", ptcd_index, CN_INDEX, ENV_GHI)
    assert card_id == "CSB-002"
    assert rule == "ptcd+env+latest"


def test_map_latest_print_without_env(tmp_path):
    _, ptcd_index = load_test_ptcd_index(tmp_path)
    # env 为空 → 全体候选最新印刷（F@2026 最新）
    card_id, rule = map_decklist_card("SVI", "185", "Ultra Ball", ptcd_index, CN_INDEX, None)
    assert card_id == "CSC-003"
    assert rule == "ptcd+latest"


def test_map_name_fallback(tmp_path):
    _, ptcd_index = load_test_ptcd_index(tmp_path)
    # set code 不在 ptcd → 回退 decklist 自带 name
    card_id, rule = map_decklist_card("XXX", "999", "Boss's Orders", ptcd_index, CN_INDEX, ENV_GHI)
    assert card_id == "CSF-006"
    assert rule == "name_fallback+unique"


def test_map_basic_energy_alias(tmp_path):
    _, ptcd_index = load_test_ptcd_index(tmp_path)
    # ptcd "Basic Psychic Energy" → CN "Psychic Energy"（去 Basic 前缀重试）
    card_id, rule = map_decklist_card(
        "SVI", "1", "Basic Psychic Energy", ptcd_index, CN_INDEX, ENV_GHI
    )
    assert card_id == "CSD-004"
    assert rule == "ptcd+basic_energy_alias+unique"


def test_map_release_date_tie_breaks_by_card_id(tmp_path):
    _, ptcd_index = load_test_ptcd_index(tmp_path)
    card_id, rule = map_decklist_card("XXX", "1", "Tiepuff", ptcd_index, CN_INDEX, None)
    assert card_id == "CSTA-009"  # 同日并列 → 字典序最小
    assert rule == "name_fallback+latest"


def test_map_unmapped(tmp_path):
    _, ptcd_index = load_test_ptcd_index(tmp_path)
    card_id, rule = map_decklist_card("XXX", "1", "Nonexistent Card", ptcd_index, CN_INDEX, ENV_GHI)
    assert card_id is None
    assert rule == "unmapped"


def test_parse_standings_entry_defaults():
    entry = {
        "placing": 5,
        "player": "eve",
        "deck": {"id": "d1", "name": "X Control"},
        "decklist": {
            "pokemon": [{"count": 4, "set": "SVI", "number": "057", "name": "Slowpoke"}],
            "energy": [{"count": 7, "set": "SVI", "number": "1", "name": "Basic Psychic Energy"}],
        },
    }
    s = parse_standings_entry(entry)
    assert s.placing == 5
    assert s.player == "eve"
    assert s.record_wins is None and s.record_losses is None and s.record_ties is None
    assert s.archetype_id == "d1" and s.archetype_name == "X Control"
    assert [c.name for c in s.decklist] == ["Slowpoke", "Basic Psychic Energy"]
    assert s.decklist[0].number == "057"  # number 原样字符串保真


# ---- 全流程：一场 regional 三卡组（full / partial+J 标 / 60 张门拦截）----

DECK_A = make_decklist([
    ("pokemon", 4, "SVI", "057", "Slowpoke"),
    ("trainer", 2, "SVI", "185", "Ultra Ball"),
    ("trainer", 2, "SVI", "185", "Ultra Ball"),  # 重复行 → 合并 count + warning
    ("trainer", 7, "XXX", "999", "Boss's Orders"),  # name_fallback
    ("energy", 45, "SVI", "1", "Basic Psychic Energy"),
])  # 合计 60，全映射 → full
DECK_B = make_decklist([
    ("energy", 55, "SVI", "1", "Basic Psychic Energy"),
    ("pokemon", 1, "XXX", "1", "Milotic ex"),  # J 标 → env 交叉校验告警
    ("trainer", 4, "XXX", "2", "Nonexistent Card"),  # unmapped
])  # 合计 60，mapped 56/60 → partial
DECK_C = make_decklist([
    ("energy", 59, "SVI", "1", "Basic Psychic Energy"),
])  # 合计 59 → 60 张门拦截

LIST_A = [{
    "game": "PTCG", "name": "Charlotte Regional Championship",
    "date": "2026-03-15T02:10:00.000Z", "format": "STANDARD",
    "id": T_A, "players": 850, "organizerId": "org-1",
}]
STANDINGS_A = [
    make_standing(1, "alice", {"wins": 9, "losses": 1, "ties": 0},
                  {"id": "arch-1", "name": "Slowpoke Control", "icons": []}, DECK_A),
    make_standing(2, "bob", {"wins": 8, "losses": 1, "ties": 1},
                  {"id": "arch-1", "name": "Slowpoke Control", "icons": []}, DECK_A),
    make_standing(3, "carol", {"wins": 7, "losses": 3, "ties": 0},
                  {"id": "arch-2", "name": "Mystery Box", "icons": []}, DECK_B),
    make_standing(4, "dave", {"wins": 6, "losses": 4, "ties": 0},
                  {"id": "arch-3", "name": "Short Deck", "icons": []}, DECK_C),
]


def build_full_fixture(tmp_path):
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    write_ptcd_raw(raw_dir)
    write_limitless_raw(raw_dir, list_entries=LIST_A, standings={T_A: STANDINGS_A})
    build_db(db_path)
    return raw_dir, db_path


def test_ingest_full_flow(tmp_path):
    raw_dir, db_path = build_full_fixture(tmp_path)
    result = ingest_limitless(raw_dir, db_path)

    assert result.tournaments == 1
    assert result.decks == 2  # DECK_C 被 60 张门拦截（内容与出战条目都不落）
    assert result.appearances == 3  # alice/bob 同卡组两行 + carol；dave 随拦截不落
    assert result.deck_cards == 7  # deckA 4 行（Ultra Ball 合并）+ deckB 3 行
    assert len(result.blocked) == 1 and result.blocked[0]["total"] == 59
    assert len(result.unknown_cards) == 1
    assert result.unknown_cards[0]["raw_name"] == "Nonexistent Card"

    # tournaments 行：tier 重判 + 词表物化 + env 推导
    tour = query_all(db_path, Tournament)[0]
    assert tour.tournament_id == f"limitless:{T_A}"
    assert tour.tier == "regional"
    assert tour.tier_coef == 1.5  # FR-9.4 Regional=1.5
    assert tour.env == "GHI"  # 2026-03-15 命中 EN G/H/I 段
    assert tour.participant_count == 850
    assert tour.format == "standard"
    assert tour.division is None and tour.topcut_slots is None
    assert tour.official_url == f"https://limitlesstcg.com/tournaments/{T_A}"

    deck_a_id = make_deck_id(DECK_A)
    decks = {d.deck_id: d for d in query_all(db_path, Deck)}
    assert decks[deck_a_id].mapping_status == "full"
    assert decks[deck_a_id].mapped_ratio == 1.0
    assert decks[deck_a_id].archetype_name == "Slowpoke Control"
    assert decks[deck_a_id].deck_code is None
    deck_b_id = make_deck_id(DECK_B)
    assert decks[deck_b_id].mapping_status == "partial"
    assert abs(decks[deck_b_id].mapped_ratio - 56 / 60) < 1e-9

    # deck_cards：重复行合并 count；映射裁决 env 优先（Ultra Ball → H 印刷）
    rows = {
        (r.card_id or r.raw_name): r
        for r in query_all(db_path, DeckCard)
        if r.deck_id == deck_a_id
    }
    assert rows["CSB-002"].count == 4  # 2+2 合并
    assert rows["CSB-002"].stat_scope == "other"  # 物品
    assert rows["CSE-005"].count == 4 and rows["CSE-005"].stat_scope == "pokemon"
    assert rows["CSD-004"].count == 45
    assert rows["CSF-006"].count == 7 and rows["CSF-006"].stat_scope == "supporter"

    # 出战条目：record 三列 + player 用户名；同卡组两人两行
    apps = {
        a.player_ref: a
        for a in query_all(db_path, DeckAppearance)
        if a.tournament_id == f"limitless:{T_A}"
    }
    assert apps["alice"].rank == 1
    assert (apps["alice"].record_wins, apps["alice"].record_losses,
            apps["alice"].record_ties) == (9, 1, 0)
    assert apps["alice"].points is None
    assert apps["bob"].deck_id == apps["alice"].deck_id  # 同内容实体
    assert (apps["bob"].record_wins, apps["bob"].record_losses,
            apps["bob"].record_ties) == (8, 1, 1)
    assert apps["carol"].rank == 3
    assert "dave" not in apps  # 60 张门拦截，出战条目不落

    # 警告：合并 count + env 交叉校验（J 标不在 GHI 内，不拒收）
    assert any("合并 count" in w for w in result.warnings)
    assert any("交叉校验告警" in w and "J" in w for w in result.warnings)

    # 映射决策分布（60 张门在映射前拦截，DECK_C 不计）
    assert result.mapping_rules == {
        "ptcd+unique": 1,
        "ptcd+env+latest": 2,
        "ptcd+basic_energy_alias+unique": 2,
        "name_fallback+unique": 2,
        "unmapped": 1,
    }


def test_ingest_idempotent(tmp_path):
    raw_dir, db_path = build_full_fixture(tmp_path)
    result1 = ingest_limitless(raw_dir, db_path)
    counts1 = {m.__tablename__: len(query_all(db_path, m))
               for m in (Tournament, Deck, DeckAppearance, DeckCard)}
    result2 = ingest_limitless(raw_dir, db_path)
    counts2 = {m.__tablename__: len(query_all(db_path, m))
               for m in (Tournament, Deck, DeckAppearance, DeckCard)}
    assert counts1 == counts2
    assert result2.tournaments == result1.tournaments
    assert result2.decks == result1.decks
    assert result2.appearances == result1.appearances
    assert result2.deck_cards == result1.deck_cards
    assert result2.mapping_rules == result1.mapping_rules


def test_ingest_missing_list_entry_minimal(tmp_path):
    raw_dir, db_path = tmp_path / "raw", tmp_path / "t.db"
    write_ptcd_raw(raw_dir)
    write_limitless_raw(
        raw_dir, standings={T_B: [STANDINGS_A[0]]}  # 无 list 页
    )
    build_db(db_path)
    result = ingest_limitless(raw_dir, db_path)
    assert result.tournaments == 1
    tour = query_all(db_path, Tournament)[0]
    assert tour.tournament_id == f"limitless:{T_B}"
    assert tour.tier is None and tour.tier_coef is None
    assert tour.date is None and tour.env is None and tour.participant_count is None
    assert any("缺 list 条目" in w for w in result.warnings)
    assert any("tier 归类未命中" in w for w in result.warnings)
    assert any("环境推导未命中" in w for w in result.warnings)
    # 卡组内容照常入库（同内容 → 同 deck_id）
    assert make_deck_id(DECK_A) in {d.deck_id for d in query_all(db_path, Deck)}


def test_cli_ingest_limitless(tmp_path):
    raw_dir, db_path = build_full_fixture(tmp_path)
    result = CliRunner().invoke(
        cli.app,
        ["ingest-limitless", "--raw-dir", str(raw_dir), "--db-path", str(db_path)],
    )
    assert result.exit_code == 1  # 有 60 张门拦截 → 非零退出
    assert "tournaments=1" in result.output
    assert "decks=2" in result.output
    assert "appearances=3" in result.output
    assert "blocked=1" in result.output
    assert "映射决策分布" in result.output

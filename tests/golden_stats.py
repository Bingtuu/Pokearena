"""task 029 黄金数据集：迷你赛事库 + 手工算好的三指标期望值。

数据集设计（全部日期相对 as_of=2026-08-01）：
- T1 超级赛 tier_coef=2.0 / 100 人 / topcut=8 / 2026-07-23（9 天前）
- T2 城市赛 tier_coef=1.0 / 1000 人 / topcut=2 / 2026-07-16（16 天前）
- T3 senior 组别（division 过滤用）、T4 预赛（is_qual 排除用）、
  T5 tier_coef=NULL（权重输入缺失排除用）
- T6 topcut_slots=NULL（B 层赛事范围排除、WUR 仍计入——meta n_tournaments 口径验证用）
- D1~D5 为 full 卡组；D6 为 partial（隔离验证：不进统计、不进归一化分母）

期望值由 expected() 用与 PRD FR-9.4 公式等价的 Python 计算给出（容差 1e-9），
与被测 SQL 互相独立——公式错两边同时错的风险靠人工核对本文件注释承担。
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from ptcgdb.migrations import apply_migrations
from ptcgdb.stats.caliber import write_caliber_hashes

AS_OF = "2026-08-01"
DATE_FROM = "2026-07-01"
DATE_TO = "2026-08-01"

T1, T2 = "mik_moe:9001", "mik_moe:9002"
T6 = "mik_moe:9006"  # topcut_slots=NULL：WUR 计入、B 层排除
G1, G2, G3 = "沙奈朵ex", "博士的研究", "庆典场地"


def build_golden_db(db_path: Path) -> Path:
    """应用全部迁移并插入黄金数据集（master 默认口径外的 T3/T4/T5 也入库）。"""
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    try:
        # name_groups + cards + cards_name_group
        for gk, dn in [(G1, G1), (G2, G2), (G3, G3), ("基本超能量", "基本超能量")]:
            conn.execute(
                "INSERT INTO name_groups (group_key, display_name) VALUES (?, ?)", (gk, dn)
            )
        cards = [
            ("GOLD-001", G1, "pokemon", None),
            ("GOLD-002", G2, "trainer", "支援者"),
            ("GOLD-003", G3, "trainer", "竞技场"),
            ("GOLD-004", "基本超能量", "energy", None),
        ]
        for cid, gk, ctype, subtype in cards:
            conn.execute(
                "INSERT INTO cards (card_id, set_id, number, number_display, name_full, "
                "card_type, regulation_mark, rarity, has_rule_box, is_tera, prize_cards, "
                "deck_limit, is_ace_spec, is_basic_energy, text_raw, trainer_subtype, "
                "source, fetched_at, status) "
                "VALUES (?, 'GOLD', '001', '001/001', ?, ?, 'G', 'U', 0, 0, 1, 4, 0, 0, "
                "'黄金卡原文', ?, 'golden', '2026-08-01', 'active')",
                (cid, gk, ctype, subtype),
            )
            conn.execute(
                "INSERT INTO cards_name_group (card_id, group_key) VALUES (?, ?)", (cid, gk)
            )

        tournaments = [
            # (id, tier, coef, division, date, participants, topcut, is_qual, is_team)
            (T1, "super", 2.0, "master", "2026-07-23", 100, 8, 0, 0),
            (T2, "city", 1.0, "master", "2026-07-16", 1000, 2, 0, 0),
            ("mik_moe:9003", "city", 1.0, "senior", "2026-07-20", 100, 8, 0, 0),
            ("mik_moe:9004", "city", 1.0, "master", "2026-07-21", 100, 8, 1, 0),
            ("mik_moe:9005", None, None, "master", "2026-07-22", 50, 4, 0, 0),
            ("mik_moe:9006", "city", 1.0, "master", "2026-07-25", 10, None, 0, 0),  # topcut NULL
        ]
        for tid, tier, coef, div, dt, pc, tc, qual, team in tournaments:
            conn.execute(
                "INSERT INTO tournaments (tournament_id, source, series_id, name, tier, "
                "tier_coef, division, date, location, participant_count, topcut_slots, "
                "format, regulation_mark, format_end, is_qual, is_team, official_url, "
                "fetched_at) VALUES (?, 'mik_moe', '99', ?, ?, ?, ?, ?, NULL, ?, ?, "
                "'standard', 'GHI', 'CSV9C', ?, ?, NULL, '2026-08-01')",
                (tid, f"黄金赛{tid[-4:]}", tier, coef, div, dt, pc, tc, qual, team),
            )

        decks = [
            # (deck_id, mapping_status)
            ("mik_moe:101", "full"), ("mik_moe:102", "full"), ("mik_moe:103", "full"),
            ("mik_moe:104", "full"), ("mik_moe:105", "full"), ("mik_moe:106", "partial"),
            ("mik_moe:107", "full"), ("mik_moe:108", "full"), ("mik_moe:109", "full"),
            ("mik_moe:110", "full"),
        ]
        for did, ms in decks:
            conn.execute(
                "INSERT INTO decks (deck_id, archetype_id, archetype_name, deck_code, "
                "mapping_status, mapped_ratio, source, fetched_at) VALUES (?, '1', "
                "'黄金原型', NULL, ?, 1.0, 'mik_moe', '2026-08-01')",
                (did, ms),
            )

        appearances = [
            # (deck, tournament, rank, points, wins, losses, ties)
            ("mik_moe:101", T1, 1, 100.0, 8, 1, 1),
            ("mik_moe:102", T1, 2, 0.0, None, None, None),   # points=0 回退 1/rank
            ("mik_moe:103", T1, 9, None, None, None, None),  # 非 topcut（slots=8）
            ("mik_moe:104", T2, 1, 50.0, 6, 2, 0),
            ("mik_moe:105", T2, 3, None, None, None, None),  # 非 topcut（slots=2）
            ("mik_moe:106", T2, 2, 30.0, None, None, None),  # partial → 隔离
            ("mik_moe:107", "mik_moe:9003", 1, 10.0, None, None, None),
            ("mik_moe:108", "mik_moe:9004", 1, 10.0, None, None, None),
            ("mik_moe:109", "mik_moe:9005", 1, 10.0, None, None, None),
            ("mik_moe:110", "mik_moe:9006", 1, 10.0, None, None, None),
        ]
        for did, tid, rank, pts, wins, losses, ties in appearances:
            conn.execute(
                "INSERT INTO deck_appearances (deck_id, tournament_id, rank, points, "
                "player_ref, record_wins, record_losses, record_ties, source, fetched_at) "
                "VALUES (?, ?, ?, ?, 'P001', ?, ?, ?, 'mik_moe', '2026-08-01')",
                (did, tid, rank, pts, wins, losses, ties),
            )

        deck_cards = [
            # (deck, card, count, scope)
            ("mik_moe:101", "GOLD-001", 2, "pokemon"),
            ("mik_moe:101", "GOLD-002", 4, "supporter"),
            ("mik_moe:101", "GOLD-004", 10, "other"),
            ("mik_moe:102", "GOLD-002", 4, "supporter"),
            ("mik_moe:102", "GOLD-003", 1, "stadium"),
            ("mik_moe:103", "GOLD-001", 2, "pokemon"),
            ("mik_moe:104", "GOLD-001", 2, "pokemon"),
            ("mik_moe:104", "GOLD-002", 4, "supporter"),
            ("mik_moe:105", "GOLD-002", 4, "supporter"),
            ("mik_moe:106", "GOLD-001", 2, "pokemon"),  # partial → 隔离
            ("mik_moe:107", "GOLD-001", 1, "pokemon"),
            ("mik_moe:108", "GOLD-001", 1, "pokemon"),
            ("mik_moe:109", "GOLD-001", 1, "pokemon"),
            ("mik_moe:110", "GOLD-001", 1, "pokemon"),
        ]
        for did, cid, cnt, scope in deck_cards:
            conn.execute(
                "INSERT INTO deck_cards (deck_id, card_id, count, raw_name, stat_scope) "
                "VALUES (?, ?, ?, '黄金卡', ?)",
                (did, cid, cnt, scope),
            )
        conn.commit()
    finally:
        conn.close()
    write_caliber_hashes(db_path)  # 与 init-db 流程一致：口径 hash 入 meta
    return db_path


def _days(date_str: str) -> float:
    """as_of 与赛事日期的天数差（与 julianday 差值一致）。"""
    from datetime import date

    y, m, d = map(int, date_str.split("-"))
    ay, am, ad = map(int, AS_OF.split("-"))
    return float((date(ay, am, ad) - date(y, m, d)).days)


def expected() -> dict:
    """FR-9.4 公式的独立 Python 实现（master 默认口径：排除 qual/team/缺权重赛事）。

    T6（topcut NULL）计入 WUR 分母与 G1 携带，但不进 B 层（winrate/wws B）。
    """
    w_t1 = 2.0 * math.log10(100) * 0.5 ** (_days("2026-07-23") / 90.0)
    w_t2 = 1.0 * math.log10(1000) * 0.5 ** (_days("2026-07-16") / 90.0)
    w_t6 = 1.0 * math.log10(10) * 0.5 ** (_days("2026-07-25") / 90.0)
    w_sum = w_t1 + w_t2 + w_t6

    # 出战条目权重（full 范围内归一化）
    sw1 = 100.0 + 1 / 2 + 1 / 9
    wt1 = {"101": 100.0 / sw1, "102": (1 / 2) / sw1, "103": (1 / 9) / sw1}
    sw2 = 50.0 + 1 / 3
    wt2 = {"104": 50.0 / sw2, "105": (1 / 3) / sw2}

    carry = {  # (group, tournament) → Σ w̃（decks 口径）
        (G1, T1): wt1["101"] + wt1["103"], (G1, T2): wt2["104"], (G1, T6): 1.0,
        (G2, T1): wt1["101"] + wt1["102"], (G2, T2): 1.0, (G2, T6): 0.0,  # T1 中 103 只带 G1
        (G3, T1): wt1["102"], (G3, T2): 0.0, (G3, T6): 0.0,
    }

    def wur(g: str) -> float:
        return (w_t1 * carry[(g, T1)] + w_t2 * carry[(g, T2)] + w_t6 * carry[(g, T6)]) / w_sum

    # B 层：topcut T1 slots=8（101✓ 102✓ 103✗）；T2 slots=2（104✓ 105✗）；T6 不参与
    top = {
        (G1, T1): wt1["101"], (G1, T2): wt2["104"],
        (G2, T1): wt1["101"] + wt1["102"], (G2, T2): wt2["104"],
        (G3, T1): wt1["102"], (G3, T2): 0.0,
    }

    def t_u(g: str) -> tuple[float, float]:
        return (
            w_t1 * top[(g, T1)] + w_t2 * top[(g, T2)],
            w_t1 * carry[(g, T1)] + w_t2 * carry[(g, T2)],
        )

    q0 = (w_t1 * (8 / 100) + w_t2 * (2 / 1000)) / (w_t1 + w_t2)

    def wr_b(g: str) -> float:
        t, u = t_u(g)
        return t / u

    def wws_b(g: str, k: float = 10.0) -> float:
        t, u = t_u(g)
        return wur(g) * (t + k * q0) / (u + k)

    # A 层：仅 D1(8/1/1) 与 D4(6/2/0) 有 record（G1/G2 均被二者携带）
    wa, la, ta = 14.0, 3.0, 1.0
    wr_a = (wa + 0.5 * ta) / (wa + la + ta)

    def wws_a(g: str, k: float = 20.0) -> float:
        return wur(g) * (wa + 0.5 * ta + k * 0.5) / (wa + la + ta + k)

    return {
        "w_t1": w_t1, "w_t2": w_t2, "q0": q0,
        "wur": {G1: wur(G1), G2: wur(G2), G3: wur(G3)},
        # copies 口径：G1 每出战 2 张（T6 的 D110 只带 1 张）、G2 每出战 4 张、G3 每出战 1 张
        "wur_copies": {
            G1: (w_t1 * 2 * carry[(G1, T1)] + w_t2 * 2 * carry[(G1, T2)] + w_t6 * 1.0)
            / w_sum,
            G2: (w_t1 * 4 * carry[(G2, T1)] + w_t2 * 4 * carry[(G2, T2)]) / w_sum,
            G3: (w_t1 * carry[(G3, T1)]) / w_sum,
        },
        "wr_b": {G1: wr_b(G1), G2: wr_b(G2), G3: wr_b(G3)},
        "wr_a": wr_a,
        "wws_b": {G1: wws_b(G1), G2: wws_b(G2), G3: wws_b(G3)},
        "wws_a": {G1: wws_a(G1), G2: wws_a(G2), G3: wws_a(G3)},
        "n_usage": {G1: 4, G2: 4, G3: 1},
    }

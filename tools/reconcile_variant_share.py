"""task 027 验收：variant 对账（mik deck-static vs 我方 deck_appearances 聚合）。

口径发现（2026-08-02 实测）：
- mik deck-static 覆盖**全量参赛卡组**；我方 ingest 口径 = rank-individual 第 1 页（top64，FR-9.5）。
- mik deck-static 的 archetype 粒度 = variant 归并：取 variantIcon 的**最长前缀**匹配 static entry icon
  （完整匹配 → 自身；否则前缀递减，如 [charizard,pidgeot] → 299 喷火龙）。
- 团队赛（is_team）mik deck-static 的 count 为人均值（小数），口径不可比 → 跳过。

判定：
- full-coverage 场（mik Σcount == 我方条目数）：rollup 后每个 archetype 计数必须完全一致（强验收）；
- 部分覆盖场：每个 static archetype mik count ≥ 我方 top64 count（单调性弱验收）；
- mik 无 deck-static 数据（空 list）或团队赛：跳过，单独列出。
"""

import json
import os
import sqlite3
import sys

RAW_DIR = "data/raw/mikmoe/decks/deck-static-by-tour"
DETAIL_DIR = "data/raw/mikmoe/decks/detail"
DB = "data/ptcg-cn.db"


def load_variant_icons() -> dict[str, tuple[str, ...]]:
    """archetype_id(str) → variantIcon tuple（从全部 deck detail raw）。"""
    icons: dict[str, tuple[str, ...]] = {}
    for fname in os.listdir(DETAIL_DIR):
        if not fname.endswith(".json"):
            continue
        data = json.load(open(os.path.join(DETAIL_DIR, fname), encoding="utf-8"))["data"]
        v = data.get("variant") or {}
        vid, vicon = v.get("variantId"), v.get("variantIcon")
        if vid is not None and vicon:
            icons.setdefault(str(vid), tuple(vicon))
    return icons


def rollup(icon_map, aid: str, static_by_icon: dict[tuple[str, ...], str]) -> str | None:
    """variant archetype_id → deck-static 粒度 id（icon 最长前缀匹配）。"""
    icons = icon_map.get(aid)
    if not icons:
        return None
    for n in range(len(icons), 0, -1):
        if icons[:n] in static_by_icon:
            return static_by_icon[icons[:n]]
    return None


def main() -> int:
    conn = sqlite3.connect(DB)
    icon_map = load_variant_icons()
    files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".json"))
    full_ok = full_fail = partial_ok = partial_fail = skipped = 0
    lines = []
    for fname in files:
        tid = f"mik_moe:{fname[:-5]}"
        data = json.load(open(os.path.join(RAW_DIR, fname), encoding="utf-8"))["data"]["list"]
        rows = conn.execute(
            "SELECT d.archetype_id, count(*) FROM deck_appearances a "
            "JOIN decks d USING(deck_id) WHERE a.tournament_id=? GROUP BY 1",
            (tid,),
        ).fetchall()
        our_total = sum(c for _, c in rows)
        is_team = conn.execute(
            "SELECT is_team FROM tournaments WHERE tournament_id=?", (tid,)
        ).fetchone()[0]
        if is_team:
            skipped += 1
            lines.append(f"{tid} 团队赛（mik count 为人均口径，不可比；我方条目={our_total}），跳过")
            continue
        if not data:
            skipped += 1
            lines.append(f"{tid} mik 无 deck-static 数据（我方条目={our_total}），跳过")
            continue

        mik_count = {str(e["id"]): e["count"] for e in data}
        names = {str(e["id"]): e["name"] for e in data}
        static_by_icon = {tuple(e["icon"]): str(e["id"]) for e in data}
        mik_total = sum(mik_count.values())

        ours: dict[str, int] = {}
        unmapped = set()
        for aid, c in rows:
            sid = rollup(icon_map, aid, static_by_icon)
            if sid is None:
                unmapped.add(aid)
                continue
            ours[sid] = ours.get(sid, 0) + c

        diffs = []
        for sid, mc in mik_count.items():
            oc = ours.get(sid, 0)
            if mik_total == our_total:
                if mc != oc:
                    diffs.append(f"{names[sid]} mik={mc} 我方={oc}")
            elif mc < oc:
                diffs.append(f"{names[sid]} mik={mc} < 我方={oc}")
        for sid in set(ours) - set(mik_count):
            diffs.append(f"我方多出 static_id={sid} count={ours[sid]}")
        if unmapped:
            diffs.append(f"variant 无 icon 映射: {sorted(unmapped)}")

        coverage = "full" if mik_total == our_total else f"partial(mik={mik_total}/我方top64={our_total})"
        if diffs:
            if mik_total == our_total:
                full_fail += 1
            else:
                partial_fail += 1
            lines.append(f"{tid} [{coverage}] FAIL: " + "; ".join(diffs))
        else:
            if mik_total == our_total:
                full_ok += 1
            else:
                partial_ok += 1
            lines.append(f"{tid} [{coverage}] OK")
    conn.close()

    print("\n".join(lines))
    print(
        f"\nfull-coverage: OK {full_ok} / FAIL {full_fail}；"
        f"partial: OK {partial_ok} / FAIL {partial_fail}；mik 无数据跳过 {skipped}"
    )
    return 1 if (full_fail or partial_fail) else 0


if __name__ == "__main__":
    sys.exit(main())

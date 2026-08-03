"""卡面分母种子（PRD §7.1 `card_face_total`，v1.11 task 030，F-01）。

A2 卡面人工比对实测翻案：卡面编号分母 = 商品主列表收录数，**无法从 mik 推出**
（mik cardsNum 为含追加收录的全量口径）。种子文件 `config/set_card_face_totals.yml`
为唯一事实源，来源三层（优先级从高到低）：

1. `measured`：A2 人工实测数据点（207/414/151/045/222 五例）
2. `tcgdex`：TCGdex zh-cn 系列壳 `cardCount.official`，须过 sanity 门才播种
   （official ≤ 库内数字编号最大值且 1..official 编号全覆盖），不过门入冲突清单
3. `derived_cbb`：CBB* 宝石包按包播种（PPNN 复合编号，分母=包内卡数，
   库内前缀分组统计，与 5 例实测自洽）

未覆盖系列 `card_face_total=NULL`：number_display 只显示分子（不伪装卡面口径）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ptcgdb.normalize.fields import CONFIG_DIR

SEED_PATH = CONFIG_DIR / "set_card_face_totals.yml"

# A2 人工实测数据点（.scratch/task020-findings.md F-01；CSM1cC 与 tcgdex official 一致）
MEASURED: dict[str, int] = {
    "CS1DC": 207,
    "CS4DaC": 414,
    "CSM1cC": 151,
    "CSM2.1C": 45,
    "CSV10C": 222,
}

# CBB* 宝石包实测（卡面 PPNN/包内卡数）：{set: {包号: 包内卡数}}
MEASURED_CBB: dict[str, dict[str, int]] = {
    "CBB1C": {"13": 7, "08": 7, "18": 7},
    "CBB2C": {"09": 15, "11": 7},
    "CBB3C": {"11": 7},
}


@dataclass
class SeedResult:
    """种子生成结果：落 yml 的条目 + 被 sanity 门拦下的冲突。"""

    totals: dict[str, dict] = field(default_factory=dict)  # set_id → {total, source}
    packs: dict[str, dict] = field(default_factory=dict)  # set_id → {packs, source}
    conflicts: list[str] = field(default_factory=list)  # 冲突说明（未播种）


def load_seed(seed_path: Path = SEED_PATH) -> dict[str, dict]:
    """读种子文件 → {set_id: entry}。文件不存在返回空（未覆盖=只显分子）。"""
    if not seed_path.exists():
        return {}
    doc = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
    return doc.get("sets") or {}


def display_denominator(seed_entry: dict | None, number: str) -> int | None:
    """(种子条目, 分子) → number_display 分母。无种子/包号未覆盖 → None（只显分子）。"""
    if not seed_entry:
        return None
    if "total" in seed_entry:
        return seed_entry["total"]
    packs = seed_entry.get("packs") or {}
    if packs and number[:2].isdigit():
        return packs.get(number[:2])
    return None


def _numeric_numbers(con: sqlite3.Connection, set_id: str) -> list[int]:
    rows = con.execute(
        "SELECT DISTINCT number FROM cards WHERE set_id=?"
        " AND number GLOB '[0-9]*' AND number NOT GLOB '*[^0-9]*'",
        (set_id,),
    ).fetchall()
    return sorted(int(r[0]) for r in rows)


def _gate_tcgdex(con: sqlite3.Connection, set_id: str, official: int) -> str | None:
    """sanity 门：返回 None=通过，否则返回冲突原因。"""
    nums = _numeric_numbers(con, set_id)
    if not nums:
        return f"{set_id}: 库内无数字编号卡"
    if official > max(nums):
        return f"{set_id}: tcgdex official={official} > 库内最大编号 {max(nums)}"
    missing = [n for n in range(1, official + 1) if n not in set(nums)]
    if missing:
        return f"{set_id}: tcgdex official={official} 但 1..official 有缺口 {missing[:5]}"
    return None


def _derive_cbb_packs(con: sqlite3.Connection, set_id: str) -> dict[str, int]:
    """CBB 按包分组统计（PPNN 复合编号前两位=包号）。"""
    packs: dict[str, int] = {}
    for (num,) in con.execute(
        "SELECT DISTINCT number FROM cards WHERE set_id=?"
        " AND number GLOB '[0-9]*' AND number NOT GLOB '*[^0-9]*'",
        (set_id,),
    ):
        packs[num[:2]] = packs.get(num[:2], 0) + 1
    return dict(sorted(packs.items()))


def generate_seed(db_path: Path, raw_dir: Path) -> SeedResult:
    """生成种子：实测 > tcgdex（过门）> CBB 按包（实测校验）。幂等可重跑。"""
    import json

    result = SeedResult()
    con = sqlite3.connect(db_path)
    try:
        # ① 人工实测直接播种（最高优先级）
        for set_id, total in sorted(MEASURED.items()):
            result.totals[set_id] = {"total": total, "source": "measured"}

        # ② TCGdex zh-cn 壳 official（实测已覆盖的系列跳过；过 sanity 门才播种）
        shells_path = Path(raw_dir) / "tcgdex" / "zh-cn-sets.json"
        shells = json.loads(shells_path.read_text(encoding="utf-8"))["sets"]
        for shell in shells:
            set_id = shell["id"]
            if set_id in result.totals:
                continue
            official = (shell.get("cardCount") or {}).get("official")
            if not official:
                result.conflicts.append(f"{set_id}: tcgdex 壳无 official 值")
                continue
            exists = con.execute(
                "SELECT 1 FROM sets WHERE set_id=?", (set_id,)
            ).fetchone()
            if not exists:
                continue  # 非本库系列（tcgdex 壳与本库 set_id 不一致的参照项）
            reason = _gate_tcgdex(con, set_id, official)
            if reason:
                result.conflicts.append(reason)
            else:
                result.totals[set_id] = {"total": official, "source": "tcgdex"}

        # ③ CBB* 按包播种（库内分组统计；实测包计数必须全中，否则整包入冲突）
        for set_id, measured_packs in sorted(MEASURED_CBB.items()):
            derived = _derive_cbb_packs(con, set_id)
            bad = [
                f"包{p}: 实测{v} vs 统计{derived.get(p)}"
                for p, v in measured_packs.items()
                if derived.get(p) != v
            ]
            if bad:
                result.conflicts.append(f"{set_id}: CBB 包计数与实测不符 {bad}")
            else:
                result.packs[set_id] = {"packs": derived, "source": "derived_cbb"}
    finally:
        con.close()
    return result


def write_seed(result: SeedResult, seed_path: Path = SEED_PATH) -> Path:
    """种子结果落 yml（确定性输出，幂等）。"""
    sets_doc: dict[str, dict] = {}
    for set_id in sorted(result.totals):
        sets_doc[set_id] = result.totals[set_id]
    for set_id in sorted(result.packs):
        sets_doc[set_id] = {
            "packs": {p: int(v) for p, v in result.packs[set_id]["packs"].items()},
            "source": result.packs[set_id]["source"],
        }
    doc = {
        "#": "卡面分母种子（PRD §7.1 card_face_total，task 030）"
        "——ptcgdb seed-face-totals 生成，勿手改",
        "sets": sets_doc,
    }
    seed_path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return seed_path


def apply_seed_to_sets(db_path: Path, seed_path: Path = SEED_PATH) -> int:
    """种子 → sets.card_face_total（total 型播种，packs 型置 NULL；未覆盖清空）。返回播种数。"""
    seed = load_seed(seed_path)
    con = sqlite3.connect(db_path)
    try:
        applied = 0
        for (set_id,) in con.execute("SELECT set_id FROM sets"):
            entry = seed.get(set_id)
            total = entry.get("total") if entry and "total" in entry else None
            con.execute(
                "UPDATE sets SET card_face_total=? WHERE set_id=?", (total, set_id)
            )
            if total is not None:
                applied += 1
        con.commit()
    finally:
        con.close()
    return applied

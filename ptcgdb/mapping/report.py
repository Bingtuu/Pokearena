"""映射覆盖率报告（task 022/023/024 共用）。"""

from datetime import UTC, datetime
from pathlib import Path

from ptcgdb.mapping.en import EnFillResult
from ptcgdb.mapping.tcgdex import ResolveResult, SetReconcileReport


def write_en_report(result: EnFillResult, out_dir: Path) -> Path:
    """EN 映射覆盖率报告：总量 + 分系列覆盖 + 无桥清单（如实记录，不猜测）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    path = out_dir / f"mapping-en-{stamp}.md"
    mapped = result.filled + result.already
    lines = [
        f"# EN 映射覆盖率报告（{stamp}）",
        "",
        f"- 全库卡数：{result.total}",
        f"- 已映射（name_en + external_ids mik_en）：{mapped}（{mapped / result.total:.1%}）",
        f"  - 本次补齐 name_en：{result.filled}；入库时已填充核实：{result.already}",
        f"- 无英文桥（简中独占等，不猜测）：{len(result.no_bridge)}",
        "",
        "## 分系列覆盖",
        "",
        "| 系列 | 已映射 | 总数 | 覆盖率 |",
        "|---|---|---|---|",
    ]
    for set_id in sorted(result.by_set):
        mapped_n, total_n = result.by_set[set_id]
        lines.append(f"| {set_id} | {mapped_n} | {total_n} | {mapped_n / total_n:.0%} |")
    lines += [
        "",
        "## 无英文桥清单",
        "",
    ]
    for card_id in result.no_bridge:
        lines.append(f"- `{card_id}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_tcgdex_report(
    result: ResolveResult, reconcile: SetReconcileReport, out_dir: Path
) -> Path:
    """TCGdex 解析 + 系列级对账报告（task 023）：四类结果与差异全记录，不猜测。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    path = out_dir / f"mapping-tcgdex-{stamp}.md"
    resolved = len(result.resolved)
    lines = [
        f"# TCGdex EN 解析 + 系列级对账报告（{stamp}）",
        "",
        "## EN 桥 → TCGdex card ID 解析",
        "",
        f"- external_ids(mik_en) 总数：{result.total}",
        f"- 解析成功（ID 命中 + 卡名归一一致）：{resolved}（{resolved / result.total:.1%}）",
        f"- setCodeEn 无映射（pokemon-tcg-data 无 ptcgoCode）："
        f"{sum(len(v) for v in result.unmapped_set.values())} 张 / {len(result.unmapped_set)} 个码",
        f"- 候选 ID 不在 TCGdex：{len(result.missing_card)}",
        f"- ID 命中但卡名不一致：{len(result.name_mismatch)}",
        "",
    ]
    if result.unmapped_set:
        lines += ["### setCodeEn 无映射清单", ""]
        for code in sorted(result.unmapped_set):
            ids = result.unmapped_set[code]
            lines.append(f"- `{code}`：{len(ids)} 张（如 {', '.join(ids[:3])}）")
        lines.append("")
    if result.missing_card:
        lines += ["### 候选 ID 不在 TCGdex（前 50）", ""]
        for card_id in sorted(result.missing_card)[:50]:
            lines.append(f"- `{card_id}` → {result.tcgdex_ids.get(card_id, '?')}")
        lines.append("")
    if result.name_mismatch:
        lines += ["### 卡名不一致（前 50，需人工裁决）", ""]
        for card_id in sorted(result.name_mismatch)[:50]:
            lines.append(f"- `{card_id}` → {result.tcgdex_ids.get(card_id, '?')}")
        lines.append("")
    lines += ["## 系列级对账（TCGdex zh-cn 壳 vs 本库 sets）", ""]
    by_status: dict[str, list] = {}
    for row in reconcile.rows:
        by_status.setdefault(row.status, []).append(row)
    lines.append(
        f"- 一致：{len(by_status.get('ok', []))}；"
        f"卡数差异：{len(by_status.get('count_diff', []))}；"
        f"名称差异：{len(by_status.get('name_diff', []))}；"
        f"TCGdex 有壳本库无：{len(by_status.get('missing_in_db', []))}；"
        f"本库有 TCGdex 无壳：{len(by_status.get('missing_in_tcgdex', []))}"
    )
    lines.append("")
    for status in ("count_diff", "name_diff", "missing_in_db", "missing_in_tcgdex"):
        rows = by_status.get(status)
        if not rows:
            continue
        lines += [f"### {status}", ""]
        for row in rows:
            lines.append(f"- `{row.set_id}` {row.note}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path

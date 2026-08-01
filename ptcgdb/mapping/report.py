"""映射覆盖率报告（task 022/024 共用）。"""

from datetime import UTC, datetime
from pathlib import Path

from ptcgdb.mapping.en import EnFillResult


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

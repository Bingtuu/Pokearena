"""映射覆盖率报告（task 022/023/024 共用）。"""

from datetime import UTC, datetime
from pathlib import Path

from ptcgdb.mapping.en import EnFillResult
from ptcgdb.mapping.ja import JaFillResult
from ptcgdb.mapping.tcgdex import ResolveResult, SetReconcileReport


def write_en_report(result: EnFillResult, out_dir: Path) -> Path:
    """EN 映射覆盖率报告：总量 + 分系列覆盖 + 无桥清单（如实记录，不猜测）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    path = out_dir / f"mapping-en-{stamp}.md"
    mapped = result.filled + result.already
    pct = f"{mapped / result.total:.1%}" if result.total > 0 else "N/A"
    lines = [
        f"# EN 映射覆盖率报告（{stamp}）",
        "",
        f"- 全库卡数：{result.total}",
        f"- 已映射（name_en + external_ids mik_en）：{mapped}（{pct}）",
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
    pct = f"{resolved / result.total:.1%}" if result.total > 0 else "N/A"
    lines = [
        f"# TCGdex EN 解析 + 系列级对账报告（{stamp}）",
        "",
        "## EN 桥 → TCGdex card ID 解析",
        "",
        f"- external_ids(mik_en) 总数：{result.total}",
        f"- 解析成功（ID 命中 + 卡名归一一致）：{resolved}（{pct}）",
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


def write_ja_report(result: JaFillResult, total_bridge: int, out_dir: Path) -> Path:
    """JP 映射覆盖率报告（task 024）：置信度分布 + 分类 question 清单。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    path = out_dir / f"mapping-ja-{stamp}.md"
    q_total = sum(len(v) for v in result.questions.values())
    ja_pct = f"{result.name_ja_filled / total_bridge:.1%}" if total_bridge > 0 else "N/A"
    lines = [
        f"# JP 映射覆盖率报告（{stamp}）",
        "",
        "- 链路：CN → mik 英文桥 → TCGdex EN id → ptcd dexId → PokéAPI 日文物种名"
        " + 形态/机制词表（PRD v1.6 名字级映射）",
        f"- mik_en 桥总数：{total_bridge}",
        f"- external_ids(system='tcgdex') 落库：{result.external_ids_written}"
        "（置信度 tcgdex-linked）",
        f"- name_ja 填充：{result.name_ja_filled}（{ja_pct}，"
        "置信度 species-linked = dexId 链 + 词表）",
        f"- 已有值冲突（保留原值，需人工裁决）：{len(result.conflicts)}",
        f"- 未填充（question 清单，不猜测）：{q_total}",
        "",
        "## 未填充分类",
        "",
        "| 类别 | 数量 | 说明 |",
        "|---|---|---|",
    ]
    category_notes = {
        "trainer": "训练家卡：无可靠批量 JA 名源，本里程碑不填充",
        "energy_special": "特殊能量：同上",
        "no_set_map": "mik 桥无法解析出 TCGdex id（含 task 023 missing 6 张）",
        "no_dex": "TCGdex id 命中但 ptcd 卡数据无 dexId（非宝可梦或数据缺口）",
        "name_unmatched": "EN 卡名核心与物种名校验不符 / 词表外前后缀（含 TAG TEAM 成分不齐）",
    }
    for category in sorted(result.questions):
        ids = result.questions[category]
        lines.append(f"| {category} | {len(ids)} | {category_notes.get(category, '')} |")
    lines.append("")
    for category in sorted(result.questions):
        ids = result.questions[category]
        lines += [f"### {category}（前 100）", ""]
        for card_id in ids[:100]:
            lines.append(f"- `{card_id}`")
        if len(ids) > 100:
            lines.append(f"- ……共 {len(ids)} 张")
        lines.append("")
    if result.conflicts:
        lines += ["## 冲突清单", ""]
        for card_id in result.conflicts:
            lines.append(f"- `{card_id}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_tera_report(result, out_dir: Path) -> Path:
    """太晶识别报告（task 030 F-03）：命中率 + 未解析清单（如实记录，不猜测）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    path = out_dir / f"mapping-tera-{stamp}.md"
    lines = [
        f"# 太晶识别报告（{stamp}）",
        "",
        "链路：external_ids(mik_en) 印刷级桥 → ptcd sets-en ptcgoCode"
        " → ptcd 卡 subtypes 含 'Tera'。",
        "",
        f"- 全库卡数：{result.total}",
        f"- 有 mik_en 桥：{result.bridged}",
        f"- **判定太晶（is_tera=1）：{result.tera}**",
        f"- 解析为非太晶：{result.resolved_non_tera}",
        f"- 无桥（不猜测）：{len(result.no_bridge)}",
        f"- ptcgoCode 无 ptcd 系列（不猜测）：{len(result.unmapped_set)}",
        f"- ptcd 系列内查无编号（不猜测）：{len(result.missing_card)}",
        "",
        "## 无桥清单",
        "",
    ]
    for card_id in result.no_bridge:
        lines.append(f"- `{card_id}`")
    lines += ["", "## ptcgoCode 无 ptcd 系列清单", ""]
    for card_id in result.unmapped_set:
        lines.append(f"- `{card_id}`")
    lines += ["", "## ptcd 系列内查无编号清单", ""]
    for card_id in result.missing_card:
        lines.append(f"- `{card_id}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path

"""FR-2.3 校验报告渲染（Markdown，默认落 reports/ 目录，git 跟踪）。

含每规则通过率、失败明细、系列对账表、抽样清单；
规则 6 的"同源自验替代降级源比对"偏差在报告头部如实注明（task 006）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ptcgdb.validate.rules import RuleResult


def _pass_rate(r: RuleResult) -> str:
    """通过率 = 1 - 失败条目占比（按 card_id/set_id 去重），未检查显示 '-'。"""
    if r.checked == 0:
        return "-"
    failed = {
        f.get("card_id") or f.get("set_id") or tuple(f.get("card_ids") or ())
        for f in r.failures
    }
    return f"{(r.checked - len(failed)) / r.checked:.0%}"


def _fmt_value(value: Any) -> str:
    return f"`{value}`" if value is not None else "NULL"


def render_report(
    results: list[RuleResult],
    *,
    db_path: Path,
    raw_dir: Path | None,
    generated_at: datetime | None = None,
) -> str:
    ts = generated_at or datetime.now(UTC)
    all_passed = all(r.passed for r in results)
    lines = [
        "# 校验报告（FR-2.3）",
        "",
        f"- 生成时间：{ts.isoformat()}",
        f"- 数据库：`{db_path}`",
        f"- raw 目录：`{raw_dir}`",
        f"- 总结论：{'六条规则全部通过' if all_passed else '存在失败规则，阻断 activate'}",
        "",
        "> 偏差说明：PRD FR-2.3 规则 6 原文为「与降级源抽样比对」；D1 后 M1 仅有",
        "> mik.moe 单源，本报告规则 6 为 DB vs raw 同源自验，降级源比对待 Phase 2 补齐。",
        "",
        "## 规则总览",
        "",
        "| 规则 | 结果 | 检查数 | 失败数 | 通过率 |",
        "|---|---|---:|---:|---:|",
    ]
    for r in results:
        verdict = "通过" if r.passed else "**失败**"
        row = f"| {r.rule} | {verdict} | {r.checked} | {len(r.failures)} | {_pass_rate(r)} |"
        lines.append(row)

    for r in results:
        lines += ["", f"## {r.rule}", ""]
        if r.note:
            lines += [f"> {r.note}", ""]
        if r.rule == "系列对账" and r.details:
            lines += [
                "| 系列 | 应入库（expected+secret） | 实际入库 | 对账 |",
                "|---|---:|---:|---|",
            ]
            for d in r.details:
                expected = d["expected"] if d["expected"] is not None else "未知"
                ok_text = "OK" if d["ok"] else "缺口"
                lines.append(f"| {d['set_id']} | {expected} | {d['actual']} | {ok_text} |")
            lines.append("")
        if r.rule == "抽样比对" and r.details:
            lines.append("抽样清单：")
            lines.append("")
            for d in r.details:
                samples = "、".join(f"`{s}`" for s in d["samples"])
                head = f"- {d['set_id']}（共 {d['total']} 张，抽 {len(d['samples'])} 张）："
                lines.append(head + samples)
            lines.append("")
        if r.failures:
            lines.append("失败明细：")
            lines.append("")
            for f in r.failures:
                target = f.get("card_id") or f.get("set_id") or "、".join(f.get("card_ids") or [])
                parts = [f"- `{target}`"]
                if f.get("field"):
                    parts.append(f"字段 `{f['field']}`")
                if "value" in f:
                    parts.append(f"取值 {_fmt_value(f['value'])}")
                if "db" in f or "raw" in f:
                    parts.append(f"DB={_fmt_value(f.get('db'))} raw={_fmt_value(f.get('raw'))}")
                if "expected" in f:
                    parts.append(f"应 {_fmt_value(f['expected'])} 实 {_fmt_value(f.get('actual'))}")
                parts.append(f"— {f['note']}")
                lines.append(" ".join(parts))
            lines.append("")
        elif not r.details:
            lines += ["无失败项。", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(
    results: list[RuleResult],
    report_path: Path,
    *,
    db_path: Path,
    raw_dir: Path | None,
) -> Path:
    """渲染并落盘（自动建父目录），返回报告路径。"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(results, db_path=db_path, raw_dir=raw_dir), encoding="utf-8"
    )
    return report_path

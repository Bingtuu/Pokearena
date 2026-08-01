"""验收 runner（task 016，PRD §10 A1~A8，A2/A3 见 task 017 抽样工具）。

一键重跑可自动化验收项并产出 markdown 证据报告：
- A1 白名单逐卡核对（ptcgdb.legal.audit，真实库只读）
- A4 合法性引擎：两赛制 legal_at 构建 + 妖能量二分 spot check
  （构造用例 ≥12 组以 pytest 套件全绿为证据，报告注明）
- A5 更新机制：副本库 提案 → apply → 新快照生效 / 旧快照闭合可查询 / 冻结守卫
- A6 回滚：副本库 脏合入 → rollback → 行数复原
- A7 导出契约：export_all → 七件套 + checksums 逐一校验 + manifest 双轨版本
- A8 SDK 契约：open_db vs open_jsonl 同一查询集结果一致

边界：真实库只读；A5/A6 全在 work_dir 副本。单项失败不中断，报告如实记录。
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.export.exporter import EXPORT_FILES, export_all
from ptcgdb.legal.audit import audit_format
from ptcgdb.legal.engine import legal_at
from ptcgdb.legal.versions import (
    FrozenSnapshotError,
    apply_snapshot,
    rollback,
    update_text_overrides,
)
from ptcgdb.orm import Card, LegalitySnapshot
from ptcgdb.sdk import open_db, open_jsonl

FORMATS = ("standard", "open")
FAR_FUTURE = date(2099, 1, 1)  # A5/A6 提案生效日：保证晚于任何当前快照


@dataclass
class SectionResult:
    aid: str
    title: str
    passed: bool
    lines: list[str] = field(default_factory=list)


@dataclass
class AcceptanceReport:
    sections: list[SectionResult]
    path: Path

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.sections)


def _card_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    finally:
        conn.close()


def _current_snapshot(session: Session, fmt: str) -> LegalitySnapshot | None:
    return session.scalars(
        select(LegalitySnapshot)
        .where(LegalitySnapshot.format == fmt, LegalitySnapshot.effective_to.is_(None))
        .order_by(LegalitySnapshot.effective_from.desc())
        .limit(1)
    ).first()


# ---- A1 白名单逐卡核对 ----


def _run_a1(db_path: Path, today: date) -> SectionResult:
    sec = SectionResult("A1", "覆盖完整：白名单/能量分赛制逐卡核对", True)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for fmt in FORMATS:
            if _current_snapshot(session, fmt) is None:
                sec.lines.append(f"- {fmt}：无当前快照，跳过")
                continue
            result = audit_format(session, fmt, today)
            bad = [e for e in result.entries if not e.ok]
            ok_n = len(result.entries) - len(bad)
            sec.lines.append(
                f"- {fmt}：{ok_n}/{len(result.entries)} 项通过"
                + ("" if result.passed else "，**存在不符项（需人工裁决）**")
            )
            for e in bad:
                sec.lines.append(f"  - ✗ {e.name}（{e.kind}）：{e.detail}")
            if not result.passed:
                sec.passed = False
    engine.dispose()
    return sec


# ---- A4 合法性引擎 ----


def _run_a4(db_path: Path, today: date) -> SectionResult:
    sec = SectionResult("A4", "合法性引擎：卡池构建 + 妖能量二分", True)
    sec.lines.append("- 构造用例 ≥12 组：以 pytest 套件全绿为证据（tests/test_legal_engine.py）")
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        pools = {}
        for fmt in FORMATS:
            if _current_snapshot(session, fmt) is None:
                sec.lines.append(f"- {fmt}：无当前快照，跳过")
                continue
            pools[fmt] = legal_at(session, today, fmt)
            sec.lines.append(
                f"- {fmt}：legal_at({today}) 构建成功，合法卡 {len(pools[fmt].card_ids)} 张"
            )
        yao = [
            c.card_id
            for c in session.scalars(
                select(Card).where(Card.status == "active", Card.is_basic_energy.is_(True))
            )
            if c.provides == ["妖"]
        ]
        if yao and "standard" in pools and "open" in pools:
            std_hit = [c for c in yao if c in pools["standard"].card_ids]
            open_hit = [c for c in yao if c in pools["open"].card_ids]
            if std_hit:
                sec.passed = False
                sec.lines.append(f"- ✗ 妖能量出现在标准池: {std_hit[:3]}")
            elif not open_hit:
                sec.passed = False
                sec.lines.append("- ✗ 妖能量未出现在开放池")
            else:
                sec.lines.append(
                    f"- 妖能量二分正确：标准池 0 张 / 开放池 {len(open_hit)} 张"
                )
        else:
            sec.lines.append("- 库内无妖基本能量或缺赛制快照，二分 spot check 跳过")
    engine.dispose()
    return sec


# ---- A5 更新机制（副本库）----


def _write_future_proposal(work_dir: Path, db_path: Path, tag: str) -> Path:
    """以当前 standard 快照字段造一份 FAR_FUTURE 生效的提案。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        current = _current_snapshot(session, "standard")
        if current is None:
            raise LookupError("无 standard 当前快照，无法构造 A5/A6 提案")
        doc = {
            "snapshot_id": f"accept-{tag}-2099-01-01",
            "format": "standard",
            "effective_from": FAR_FUTURE.isoformat(),
            "allowed_marks": list(current.allowed_marks or []),
            "allowed_basic_energy_types": list(current.allowed_basic_energy_types or []),
            "whitelist_cards": [dict(w) for w in (current.whitelist_cards or [])],
            "banned_cards": [dict(b) for b in (current.banned_cards or [])],
            "mark_overrides": [dict(m) for m in (current.mark_overrides or [])],
            "status": "pending_review",
        }
    engine.dispose()
    path = work_dir / f"proposal-{tag}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _run_a5(db_path: Path, work_dir: Path) -> SectionResult:
    sec = SectionResult("A5", "更新机制：提案 → apply → 新快照生效 + 冻结守卫", True)
    a5_dir = work_dir / "a5"
    a5_dir.mkdir(parents=True, exist_ok=True)
    copy = a5_dir / "a5.db"
    shutil.copy2(db_path, copy)
    try:
        proposal = _write_future_proposal(a5_dir, copy, "a5")
        new_id = apply_snapshot(
            copy, proposal,
            changelog_path=a5_dir / "CHANGELOG.md", versions_dir=a5_dir / "versions",
        )
        engine = create_engine(f"sqlite:///{copy}")
        with Session(engine) as session:
            new_snap = session.get(LegalitySnapshot, new_id)
            old = session.scalars(
                select(LegalitySnapshot).where(
                    LegalitySnapshot.format == "standard",
                    LegalitySnapshot.snapshot_id != new_id,
                )
            ).first()
            checks = [
                ("新快照生效（effective_to=None）", new_snap and new_snap.effective_to is None),
                ("旧快照闭合且可查询", old and old.effective_to == FAR_FUTURE - timedelta(days=1)),
            ]
            old_id = old.snapshot_id if old else None
            for label, ok in checks:
                sec.lines.append(f"- {'✓' if ok else '✗'} {label}")
                sec.passed = sec.passed and bool(ok)
        engine.dispose()
        try:
            update_text_overrides(copy, old_id, {"X": "Y"})
            sec.passed = False
            sec.lines.append("- ✗ 冻结守卫未拦截历史快照写入")
        except FrozenSnapshotError:
            sec.lines.append("- ✓ 冻结守卫拒绝历史快照 override 写入")
    except (ValueError, LookupError) as exc:
        sec.passed = False
        sec.lines.append(f"- ✗ 异常：{exc}")
    return sec


# ---- A6 回滚（副本库）----


def _run_a6(db_path: Path, work_dir: Path) -> SectionResult:
    sec = SectionResult("A6", "回滚：脏合入 → 一键回滚 → 数据无损", True)
    a6_dir = work_dir / "a6"
    a6_dir.mkdir(parents=True, exist_ok=True)
    copy = a6_dir / "a6.db"
    shutil.copy2(db_path, copy)
    try:
        original = _card_count(copy)
        proposal = _write_future_proposal(a6_dir, copy, "a6")
        apply_snapshot(  # 制造备份（变动前的一致状态）
            copy, proposal,
            changelog_path=a6_dir / "CHANGELOG.md", versions_dir=a6_dir / "versions",
        )
        # 脏合入：删 5 行卡
        engine = create_engine(f"sqlite:///{copy}")
        with Session(engine) as session:
            for card in session.scalars(select(Card).limit(5)).all():
                session.delete(card)
            session.commit()
        engine.dispose()
        dirty = _card_count(copy)
        backup = rollback(copy, versions_dir=a6_dir / "versions")
        restored = _card_count(copy)
        ok = dirty < original and restored == original
        sec.lines.append(
            f"- 原 {original} 行 → 脏合入后 {dirty} 行 → 回滚（{backup}）后 {restored} 行"
        )
        sec.lines.append(f"- {'✓ 数据无损复原' if ok else '✗ 行数未复原'}")
        sec.passed = ok
    except (ValueError, LookupError) as exc:
        sec.passed = False
        sec.lines.append(f"- ✗ 异常：{exc}")
    return sec


# ---- A7 导出契约 ----


def _run_a7(db_path: Path, work_dir: Path) -> SectionResult:
    sec = SectionResult("A7", "导出契约：七件套 + checksums + manifest 双轨版本", True)
    dist = work_dir / "dist"
    manifest = export_all(db_path, dist)
    missing = [f for f in sorted(EXPORT_FILES) if not (dist / f).exists()]
    if missing:
        sec.passed = False
        sec.lines.append(f"- ✗ 缺文件: {missing}")
    else:
        sec.lines.append(f"- ✓ {len(EXPORT_FILES)} 件产物齐全: {', '.join(sorted(EXPORT_FILES))}")
    bad = []
    for line in (dist / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if hashlib.sha256((dist / name).read_bytes()).hexdigest() != digest:
            bad.append(name)
    if bad:
        sec.passed = False
        sec.lines.append(f"- ✗ checksum 不符: {bad}")
    else:
        sec.lines.append("- ✓ checksums.sha256 逐一校验通过")
    if manifest.get("version") and manifest.get("schema_version"):
        sec.lines.append(
            f"- ✓ manifest 双轨版本: data={manifest['version']} schema={manifest['schema_version']}"
        )
    else:
        sec.passed = False
        sec.lines.append("- ✗ manifest 缺双轨版本号")
    return sec


# ---- A8 SDK 契约 ----


def _run_a8(db_path: Path, work_dir: Path, today: date) -> SectionResult:
    sec = SectionResult("A8", "SDK 契约：open_db 与 open_jsonl 双后端一致", True)
    dist = work_dir / "dist"
    if not (dist / "manifest.json").exists():
        dist = work_dir / "dist-a8"
        export_all(db_path, dist)
    try:
        with open_db(db_path) as db, open_jsonl(dist) as js:
            if db.schema_version != js.schema_version:
                sec.passed = False
                sec.lines.append(
                    f"- ✗ schema_version 不一致: {db.schema_version} vs {js.schema_version}"
                )
            else:
                sec.lines.append(f"- ✓ schema_version 一致可读: {db.schema_version}")
            samples = db.search_cards(limit=5)
            mismatches = []
            for card in samples:
                other = js.get_card(card.card_id)
                if other is None or other.model_dump() != card.model_dump():
                    mismatches.append(card.card_id)
            if mismatches:
                sec.passed = False
                sec.lines.append(f"- ✗ get_card 不一致: {mismatches}")
            else:
                sec.lines.append(f"- ✓ get_card {len(samples)} 张逐一一致")
            for fmt in FORMATS:
                try:
                    pool_db = db.legal_at(today, fmt)
                    pool_js = js.legal_at(today, fmt)
                except LookupError:
                    continue
                if pool_db.card_ids != pool_js.card_ids:
                    sec.passed = False
                    sec.lines.append(f"- ✗ legal_at({fmt}) 卡池不一致")
                else:
                    sec.lines.append(f"- ✓ legal_at({fmt}) 卡池一致（{len(pool_db.card_ids)} 张）")
            if samples:
                et_db = db.effective_text(samples[0].card_id, today)
                et_js = js.effective_text(samples[0].card_id, today)
                if et_db.model_dump() != et_js.model_dump():
                    sec.passed = False
                    sec.lines.append("- ✗ effective_text 不一致")
                else:
                    sec.lines.append("- ✓ effective_text 一致")
    except Exception as exc:  # SDK 异常即契约失败，如实记录
        sec.passed = False
        sec.lines.append(f"- ✗ 异常：{type(exc).__name__}: {exc}")
    return sec


# ---- 汇总 ----


def run_acceptance(
    db_path: Path, out_dir: Path, work_dir: Path, *, today: date | None = None
) -> AcceptanceReport:
    """一键验收。真实库只读；A5/A6 在 work_dir 副本；报告写 out_dir/acceptance-*.md。"""
    today = today or date.today()
    db_path, out_dir, work_dir = Path(db_path), Path(out_dir), Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    sections = [
        _run_a1(db_path, today),
        _run_a4(db_path, today),
        _run_a5(db_path, work_dir),
        _run_a6(db_path, work_dir),
        _run_a7(db_path, work_dir),
        _run_a8(db_path, work_dir, today),
    ]
    report = AcceptanceReport(sections=sections, path=out_dir / f"acceptance-{today:%Y%m%d}.md")

    lines = [
        f"# 验收报告（{today.isoformat()}）",
        "",
        f"- 数据库：`{db_path}`（卡片 {_card_count(db_path)} 行，验收动作只读；A5/A6 用副本）",
        f"- 结果：**{'全部 PASS' if report.passed else '存在 FAIL（详见下）'}**",
        f"- 生成时间：{datetime.now(UTC).isoformat()}",
        "",
    ]
    for s in sections:
        lines.append(f"## {s.aid} {s.title} — {'PASS' if s.passed else 'FAIL'}")
        lines.append("")
        lines.extend(s.lines)
        lines.append("")
    report.path.write_text("\n".join(lines), encoding="utf-8")
    return report

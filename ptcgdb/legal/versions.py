"""版本化与回滚（task 009，PRD FR-6）。

- 双轨版本化：数据版本 vYYYYMMDD.N（meta.data_version + CHANGELOG）；
  结构版本 SemVer（meta.schema_version）。
- 快照 apply：备份 DB → 闭合当前快照 → 写入新快照 → 刷新 latest_text_overrides
  （FR-5.1 后处理）→ 版本递增 → CHANGELOG 四段式追加。
- 冻结守卫：历史快照（effective_to 非空）的 latest_text_overrides 拒绝写入。
- 回滚 = 切换到上一版本 DB 文件（FR-6.3）。
"""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.legal.seed import SnapshotSeed
from ptcgdb.migrations import SCHEMA_VERSION
from ptcgdb.orm import Card, CardNameGroup, LegalitySnapshot, Meta, Set


class FrozenSnapshotError(RuntimeError):
    """历史快照 override 冻结：拒绝写入。"""


def _set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(Meta, key)
    if row is None:
        session.add(Meta(key=key, value=value))
    else:
        row.value = value


def _bump_data_version(session: Session, today: date | None = None) -> str:
    today = today or date.today()
    stamp = today.strftime("%Y%m%d")
    current = session.get(Meta, "data_version")
    n = 1
    if current is not None and current.value.startswith(f"v{stamp}."):
        n = int(current.value.rsplit(".", 1)[1]) + 1
    version = f"v{stamp}.{n}"
    _set_meta(session, "data_version", version)
    return version


def _latest_text_overrides(session: Session, whitelist: list) -> dict[str, str]:
    """白名单每个 name_group：最新印刷（系列发售日降序，空值最后，card_id 次序）为基准，
    其余印刷行映射过去。单印刷组不产生条目。"""
    overrides: dict[str, str] = {}
    for entry in whitelist:
        name = entry.name_full
        rows = session.execute(
            select(Card.card_id, Set.release_date)
            .join(CardNameGroup, CardNameGroup.card_id == Card.card_id)
            .join(Set, Set.set_id == Card.set_id)
            .where(CardNameGroup.group_key == name, Card.status == "active")
        ).all()
        if len(rows) < 2:
            continue
        ordered = sorted(rows, key=lambda r: (r[1] or date.min, r[0]), reverse=True)
        latest = ordered[0][0]
        for cid, _ in ordered[1:]:
            overrides[cid] = latest
    return overrides


def _append_changelog_block(
    changelog_path: Path, version: str, section: str, items: list[str]
) -> None:
    """四段式追加一个版本块（插在 "# Changelog" 标题之后）。"""
    if changelog_path.exists():
        text = changelog_path.read_text(encoding="utf-8")
    else:
        text = "# Changelog\n\n"
    body = "\n".join(f"- {item}" for item in items)
    block = f"## [{version}] - {date.today().isoformat()}\n\n### {section}\n\n{body}\n\n"
    lines = text.split("\n")
    # 插到 "# Changelog" 标题之后
    insert_at = 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    lines.insert(insert_at, block.rstrip("\n"))
    changelog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_changelog(
    changelog_path: Path, version: str, seed: SnapshotSeed, proposal: Path
) -> None:
    _append_changelog_block(
        changelog_path,
        version,
        "Added",
        [
            f"环境快照 `{seed.snapshot_id}`（{seed.format}，{seed.effective_from} 起生效；"
            f"提案 `{proposal}`）"
        ],
    )


def apply_snapshot(
    db_path: Path,
    proposal_path: Path,
    *,
    changelog_path: Path = Path("CHANGELOG.md"),
    versions_dir: Path | None = None,
) -> str:
    """应用赛制变更提案（FR-5.2 的人工确认之后）：生成新快照，返回 snapshot_id。"""
    seed = SnapshotSeed.model_validate(
        yaml.safe_load(Path(proposal_path).read_text(encoding="utf-8"))
    )
    versions_dir = versions_dir or Path(db_path).parent / "versions"

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        current_version = session.get(Meta, "data_version")
        backup_tag = current_version.value if current_version else "base"

        current = session.scalars(
            select(LegalitySnapshot)
            .where(
                LegalitySnapshot.format == seed.format,
                LegalitySnapshot.effective_to.is_(None),
            )
            .order_by(LegalitySnapshot.effective_from.desc())
            .limit(1)
        ).first()
        if current is not None and seed.effective_from <= current.effective_from:
            raise ValueError(
                f"新快照生效日 {seed.effective_from} 必须晚于当前快照 {current.effective_from}"
            )
        if session.get(LegalitySnapshot, seed.snapshot_id) is not None:
            raise ValueError(f"snapshot_id 已存在: {seed.snapshot_id}")

        # 1. 备份（变动前）
        versions_dir.mkdir(parents=True, exist_ok=True)
        backup = versions_dir / f"ptcg-cn-{backup_tag}.db"
        session.commit()  # 落盘未提交内容，保证备份一致
        shutil.copy2(db_path, backup)

        # 2. 闭合当前快照 + 写入新快照（旧快照永不删除）
        if current is not None:
            current.effective_to = seed.effective_from - timedelta(days=1)
        session.add(LegalitySnapshot(
            snapshot_id=seed.snapshot_id,
            format=seed.format,
            effective_from=seed.effective_from,
            effective_to=None,
            allowed_marks=seed.allowed_marks,
            allowed_basic_energy_types=seed.allowed_basic_energy_types,
            whitelist_cards=[w.model_dump() for w in seed.whitelist_cards],
            banned_cards=[b.model_dump() for b in seed.banned_cards],
            mark_overrides=[m.model_dump() for m in seed.mark_overrides],
            latest_text_overrides=_latest_text_overrides(session, seed.whitelist_cards),
            source_url=seed.source_url,
            created_at=datetime.now(UTC),
        ))

        # 3. 双轨版本号
        _set_meta(session, "schema_version", SCHEMA_VERSION)
        version = _bump_data_version(session)
        session.commit()
    engine.dispose()

    # 4. CHANGELOG 四段式（Added）
    _append_changelog(changelog_path, version, seed, Path(proposal_path))
    return seed.snapshot_id


def update_text_overrides(db_path: Path, snapshot_id: str, overrides: dict[str, str]) -> None:
    """更新 latest_text_overrides；仅当前快照可写，历史快照冻结（FR-3.3/S5）。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        row = session.get(LegalitySnapshot, snapshot_id)
        if row is None:
            raise LookupError(f"快照不存在: {snapshot_id}")
        if row.effective_to is not None:
            raise FrozenSnapshotError(
                f"历史快照 {snapshot_id} 已冻结"
                f"（effective_to={row.effective_to}），拒绝写入 override"
            )
        row.latest_text_overrides = {**(row.latest_text_overrides or {}), **overrides}
        session.commit()
    engine.dispose()


def rollback(db_path: Path, *, versions_dir: Path | None = None) -> str:
    """回滚：用最新备份覆盖当前 DB 文件（FR-6.3），返回所用备份文件名。"""
    versions_dir = versions_dir or Path(db_path).parent / "versions"
    backups = sorted(versions_dir.glob("ptcg-cn-*.db")) if versions_dir.is_dir() else []
    if not backups:
        raise LookupError(f"无可用备份: {versions_dir}")
    shutil.copy2(backups[-1], db_path)
    return backups[-1].name

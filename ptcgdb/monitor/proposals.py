"""提案生命周期（task 015，PRD FR-5.2 闭环）。

proposals/ 目录提案的列举与状态回写：
pending_review / needs_manual →（人工确认 → legal-apply）→ applied。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def list_proposals(proposals_dir: Path) -> list[dict[str, Any]]:
    """列出目录下全部 *.yaml 提案的摘要（按文件名排序）。"""
    proposals_dir = Path(proposals_dir)
    if not proposals_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(proposals_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("YAML 解析失败 %s: %s", path, exc)
            doc = {}
        rows.append({
            "path": str(path),
            "snapshot_id": doc.get("snapshot_id"),
            "format": doc.get("format"),
            "status": doc.get("status", "unknown"),
            "detected_at": doc.get("detected_at"),
            "parse_errors": doc.get("parse_errors") or [],
        })
    return rows


def mark_proposal_applied(proposal_path: Path, snapshot_id: str) -> None:
    """legal-apply 成功后回写：status=applied + applied_snapshot_id + applied_at。"""
    proposal_path = Path(proposal_path)
    doc = yaml.safe_load(proposal_path.read_text(encoding="utf-8")) or {}
    doc["status"] = "applied"
    doc["applied_snapshot_id"] = snapshot_id
    doc["applied_at"] = datetime.now(UTC).isoformat()
    proposal_path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

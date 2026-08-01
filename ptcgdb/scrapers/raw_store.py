"""raw 层落盘（append-only）。

每个 raw 文件内嵌 `_meta` 侧车信息：fetched_at / source / content_hash
（content_hash = payload 部分规范化 JSON 的 sha256）。

append-only 语义（两选一，本实现选"存在即跳过"）：
- 同一路径已存在且 hash 校验有效 → 不覆盖、不重抓（断点续传的粒度基础）；
- 需要重抓时显式传 force=True（CLI `--force`），旧文件被覆盖——
  raw 层的"append-only"指**不原地修改语义化内容**，重抓覆盖的是同一来源同一键的
  原始响应快照，历史版本由 git/备份兜底；不删除任何已落盘文件。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

META_KEY = "_meta"


def canonical_json(payload: Any) -> str:
    """规范化 JSON（排序键、紧凑分隔符），用于 content_hash 与 manifest_hash。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def raw_path(base_dir: Path, *parts: str) -> Path:
    return base_dir.joinpath(*parts)


def write_raw(
    path: Path,
    payload: dict[str, Any],
    *,
    source: str,
    fetched_at: str | None = None,
    force: bool = False,
) -> bool:
    """写入 raw 文件（内嵌 _meta）。已存在且 hash 有效且非 force → 跳过，返回 False。"""
    if not force and is_valid_raw(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        META_KEY: {
            "fetched_at": fetched_at or datetime.now(UTC).isoformat(),
            "source": source,
            "content_hash": content_hash(payload),
        },
        **payload,
    }
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return True


def is_valid_raw(path: Path) -> bool:
    """文件存在、可解析、且 _meta.content_hash 与 payload 重算值一致。"""
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    stored = (doc.get(META_KEY) or {}).get("content_hash")
    if not stored:
        return False
    payload = {k: v for k, v in doc.items() if k != META_KEY}
    return content_hash(payload) == stored


def read_raw(path: Path) -> dict[str, Any] | None:
    """读出完整 raw 文档（含 _meta）；无效返回 None。"""
    if not is_valid_raw(path):
        return None
    return json.loads(path.read_text(encoding="utf-8"))

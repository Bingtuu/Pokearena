"""L1 赛制监控 + 提案生成（task 014，PRD FR-5.2）。

三页正文提取（剔除 img/auth_key、页眉页脚、?ver= 等动态区块）→ hash 快照比对 →
变更检测 → 结构化提案 proposals/YYYYMMDD_*.yaml。

提案 = SnapshotSeed 超集：顶层即 SnapshotSeed 字段，另加 proposal_id/detected_at/
status/diff/parse_errors/raw_excerpt（Pydantic extra=ignore，apply_snapshot 直接消费）。
解析不确定的变更 status=needs_manual、快照字段沿用当前值——绝不猜测性自动 apply。

实测页面结构（2026-08-01 recon，fixture 见 tests/fixtures/l1/）：
- 赛制页/特别的卡牌页正文容器：<div class="article-body__inner">（WordPress）
- 公告列表页：<ul class="card-list__body"> 内 li.card__element
- "特别的卡牌"外链 /tcg-rules-regulation-extra/ 是特殊机制说明页（GX/棱镜之星/
  TAG TEAM/V-UNION 等），无结构化字段，只 hash 监控 + needs_manual 提案
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.orm import LegalitySnapshot

OFFICIAL_BASE = "https://www.pokemon.cn"

# 公告标题命中这些关键词时生成 needs_manual 提案（否则仅事件通知）
NEWS_KEYWORDS = re.compile(r"赛制|禁卡|禁用|勘误|规则|调整")

BLOCK_TAGS = {"h3", "h4", "p", "li", "dt", "dd"}
SKIP_TAGS = {"script", "style", "noscript"}
VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}


@dataclass(frozen=True)
class PageTarget:
    page_id: str
    url: str
    kind: str  # "article" / "news"


PAGE_TARGETS: tuple[PageTarget, ...] = (
    PageTarget("regulation", f"{OFFICIAL_BASE}/tcg-rules-regulation", "article"),
    PageTarget("extra", f"{OFFICIAL_BASE}/tcg-rules-regulation-extra/", "article"),
    PageTarget("news", f"{OFFICIAL_BASE}/category/tcg", "news"),
)


@dataclass(frozen=True)
class NewsEntry:
    href: str
    title: str
    category: str
    date: str


@dataclass
class ParsedFormat:
    effective_from: date | None = None
    allowed_marks: list[str] | None = None  # None = 未能解析，沿用当前快照
    whitelist: list[dict[str, Any]] = field(default_factory=list)
    banned: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParsedRegulation:
    formats: dict[str, ParsedFormat]
    parse_errors: list[str]


@dataclass
class L1Result:
    baselines: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    noop: list[str] = field(default_factory=list)  # hash 变了但解析内容与快照一致
    proposals: list[Path] = field(default_factory=list)
    news: list[dict[str, Any]] = field(default_factory=list)  # 新公告条目


# ---- 正文提取 ----


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _ArticleParser(HTMLParser):
    """提取 article-body__inner 容器内的 (tag, text) 块序列，剥一切属性与 img/script。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._depth = 0  # 容器内相对深度（0=未进容器）
        self._tag_stack: list[str] = []
        self._block_tag: str | None = None
        self._block_parts: list[str] = []
        self._skip_depth = 0

    def _class_of(self, attrs: list[tuple[str, str | None]]) -> str:
        return dict(attrs).get("class") or ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth == 0:
            if tag == "div" and "article-body__inner" in self._class_of(attrs):
                self._depth = 1
            return
        if tag in VOID_TAGS:  # void 元素无结束标签：不影响深度，img 直接忽略
            if tag == "br" and self._block_tag is not None and self._skip_depth == 0:
                self._block_parts.append("\n")
            return
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        self._depth += 1
        self._tag_stack.append(tag)
        if tag in BLOCK_TAGS and tag != self._block_tag:
            # 新块开始：若有未闭合的块（块标签嵌套，如 p 里套 ul>li）先闭合它
            if self._block_tag is not None:
                text = _norm_text("".join(self._block_parts))
                if text:
                    self.blocks.append((self._block_tag, text))
            self._block_tag = tag
            self._block_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth > 0 and tag == "br" and self._block_tag is not None:
            self._block_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        if self._skip_depth > 0:
            if tag in SKIP_TAGS:
                self._skip_depth -= 1
            return
        self._depth -= 1
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        if tag == self._block_tag:
            text = _norm_text("".join(self._block_parts))
            if text:
                self.blocks.append((self._block_tag, text))
            self._block_tag = None
            self._block_parts = []

    def handle_data(self, data: str) -> None:
        if self._depth > 0 and self._skip_depth == 0 and self._block_tag is not None:
            self._block_parts.append(data)


def extract_blocks(html: str) -> list[tuple[str, str]]:
    """从赛制页/特别卡牌页 HTML 提取正文块序列 [(tag, text), ...]。"""
    parser = _ArticleParser()
    parser.feed(html)
    return parser.blocks


class _NewsParser(HTMLParser):
    """提取公告列表 ul.card-list__body 内的条目（href/title/category/date）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[NewsEntry] = []
        self._depth = 0
        self._in_li = False
        self._href = ""
        self._title_parts: list[str] = []
        self._capture: str | None = None  # "title" / "category" / "date"
        self._parts: list[str] = []
        self._category = ""
        self._date = ""

    def _class_of(self, attrs: list[tuple[str, str | None]]) -> str:
        return dict(attrs).get("class") or ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = self._class_of(attrs)
        if self._depth == 0:
            if tag == "ul" and "card-list__body" in cls:
                self._depth = 1
            return
        self._depth += 1
        if tag == "li" and "card__element" in cls:
            self._in_li = True
            self._href = self._category = self._date = ""
            self._title_parts = []
        elif self._in_li and tag == "a" and not self._href:
            self._href = dict(attrs).get("href") or ""
        elif self._in_li and tag == "div" and "card__products-title" in cls:
            self._capture = "title"
            self._parts = []
        elif self._in_li and tag == "time" and "card__footer--category" in cls:
            self._capture = "category"
            self._parts = []
        elif self._in_li and tag == "time" and "card__footer--date" in cls:
            self._capture = "date"
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        if self._capture == "title" and tag == "div":
            self._title_parts.append(_norm_text("".join(self._parts)))
            self._capture = None
        elif self._capture == "category" and tag == "time":
            self._category = _norm_text("".join(self._parts))
            self._capture = None
        elif self._capture == "date" and tag == "time":
            self._date = _norm_text("".join(self._parts))
            self._capture = None
        elif tag == "li" and self._in_li:
            if self._href:
                self.entries.append(NewsEntry(
                    href=self._href,
                    title=" ".join(p for p in self._title_parts if p),
                    category=self._category,
                    date=self._date,
                ))
            self._in_li = False
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._parts.append(data)


def extract_news_entries(html: str) -> list[NewsEntry]:
    parser = _NewsParser()
    parser.feed(html)
    return parser.entries


def serialize_blocks(blocks: list[tuple[str, str]]) -> str:
    return "\n".join(f"{tag}|{text}" for tag, text in blocks)


def serialize_news(entries: list[NewsEntry]) -> str:
    return "\n".join(f"{e.href}|{e.title}|{e.category}|{e.date}" for e in entries)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 赛制页解析 ----

_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_MARKS_RE = re.compile(r"赛制标记为\s*([A-Z](?:\s*、\s*[A-Z])*)")
_PROMO_RE = re.compile(r"^特典卡“(.+?)”（(.+?)）$")
_BANNED_RE = re.compile(r"^(.+?)（(?:特性|招式)：(.+?)）$")


def _section(blocks: list[tuple[str, str]], start: str, end: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    inside = False
    for tag, text in blocks:
        if tag == "h3" and text == start:
            inside = True
            continue
        if inside and tag == "h3" and end is not None and text == end:
            break
        if inside:
            out.append((tag, text))
    return out


def _parse_date(section: list[tuple[str, str]], fmt_label: str, errors: list[str]) -> date | None:
    for _tag, text in section:
        m = re.search(r"（自\s*(\d{4})年(\d{1,2})月(\d{1,2})日起）", text)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
    for _tag, text in section:
        if "更新日期" in text:
            m = _DATE_RE.search(text)
            if m:
                return date(int(m[1]), int(m[2]), int(m[3]))
    errors.append(f"{fmt_label}：未找到生效日期（（自…起）/ 更新日期）")
    return None


def _parse_lists(
    section: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """单趟解析 li 列表：返回 (白名单, 禁卡)。"以下卡牌无法加入卡组中"之后的 li 归禁卡。"""
    whitelist: list[dict[str, Any]] = []
    banned: list[dict[str, Any]] = []
    in_banned = False
    for tag, text in section:
        if tag != "li":
            if tag in ("h3", "h4"):
                in_banned = False  # 新分节（如"关于过去系列的卡牌"）→ 禁卡区结束
            if "以下卡牌无法加入卡组中" in text:
                in_banned = True
            continue
        if in_banned:
            m = _BANNED_RE.match(text)
            if m:
                banned.append({"name": m[1], "ability_or_attack": m[2], "note": None})
            else:
                banned.append({"name": text, "ability_or_attack": None, "note": None})
            continue
        if text == "各种基本能量卡":
            continue
        m = _PROMO_RE.match(text)
        if m:
            whitelist.append({"name_full": m[1], "note": f"特典卡 {m[2]}"})
        else:
            whitelist.append({"name_full": text, "note": None})
    return whitelist, banned


def parse_regulation(blocks: list[tuple[str, str]]) -> ParsedRegulation:
    """解析赛制页正文块 → 两赛制结构化内容。关键句缺失记 parse_errors，不猜。"""
    errors: list[str] = []
    formats: dict[str, ParsedFormat] = {}

    std_section = _section(blocks, "标准赛制", "开放赛制")
    open_section = _section(blocks, "开放赛制", None)
    if not std_section:
        errors.append("未找到标准赛制分节（h3）")
    if not open_section:
        errors.append("未找到开放赛制分节（h3）")

    std = ParsedFormat()
    std.effective_from = _parse_date(std_section, "标准赛制", errors)
    marks_text = next((t for _g, t in std_section if "赛制标记为" in t), None)
    if marks_text and (m := _MARKS_RE.search(marks_text)):
        std.allowed_marks = [x.strip() for x in m[1].split("、")]
    else:
        errors.append("标准赛制：未找到赛制标记句")
    std.whitelist, _ = _parse_lists(std_section)
    if not std.whitelist:
        errors.append("标准赛制：白名单解析为空")
    formats["standard"] = std

    op = ParsedFormat()
    op.effective_from = _parse_date(open_section, "开放赛制", errors)
    # 开放赛制口径为"三个系列的卡牌"，无法机械映射标记字母 → 沿用当前快照（非错误）
    op.allowed_marks = None
    op.whitelist, op.banned = _parse_lists(open_section)
    if not op.whitelist:
        errors.append("开放赛制：白名单解析为空")
    formats["open"] = op

    return ParsedRegulation(formats=formats, parse_errors=errors)


# ---- 快照存储 ----


def _store_path(store_dir: Path, page_id: str) -> Path:
    return Path(store_dir) / f"{page_id}.json"


def _load_store(store_dir: Path, page_id: str) -> dict[str, Any] | None:
    path = _store_path(store_dir, page_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_store(
    store_dir: Path, page_id: str, url: str, digest: str, excerpt: str,
    entries: list[NewsEntry] | None = None,
) -> None:
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "page_id": page_id,
        "url": url,
        "hash": digest,
        "fetched_at": datetime.now(UTC).isoformat(),
        "excerpt": excerpt[:500],
    }
    if entries is not None:
        payload["entries"] = [e.__dict__ for e in entries]
    _store_path(store_dir, page_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ---- 提案生成 ----


def _current_snapshot(session: Session, fmt: str) -> LegalitySnapshot | None:
    return session.scalars(
        select(LegalitySnapshot)
        .where(LegalitySnapshot.format == fmt, LegalitySnapshot.effective_to.is_(None))
        .order_by(LegalitySnapshot.effective_from.desc())
        .limit(1)
    ).first()


def _diff_fields(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for key in ("effective_from", "allowed_marks", "allowed_basic_energy_types"):
        old_v = old[key].isoformat() if isinstance(old[key], date) else old[key]
        new_v = new[key].isoformat() if isinstance(new[key], date) else new[key]
        if old_v != new_v:
            diff[key] = {"old": old_v, "new": new_v}
    for key, name_key in (("whitelist_cards", "name_full"), ("banned_cards", "name")):
        old_names = sorted(str(x[name_key]) for x in old[key])
        new_names = sorted(str(x[name_key]) for x in new[key])
        if old_names != new_names:
            diff[key] = {
                "added": sorted(set(new_names) - set(old_names)),
                "removed": sorted(set(old_names) - set(new_names)),
            }
    return diff


def _write_proposal(
    proposals_dir: Path, seed_fields: dict[str, Any], *, source_url: str,
    status: str, diff: dict[str, Any], parse_errors: list[str], raw_excerpt: str,
) -> Path:
    today = date.today()
    doc = {
        **seed_fields,
        "proposal_id": f"{today.isoformat()}-{seed_fields['snapshot_id']}",
        "detected_at": datetime.now(UTC).isoformat(),
        "source_url": source_url,
        "status": status,  # pending_review / needs_manual
        "diff": diff,
        "parse_errors": parse_errors,
        "raw_excerpt": raw_excerpt[:1000],
    }
    proposals_dir = Path(proposals_dir)
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / f"{today:%Y%m%d}_{seed_fields['snapshot_id']}.yaml"
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def _seed_fields_from_current(snap: LegalitySnapshot, snapshot_id: str) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "format": snap.format,
        "effective_from": snap.effective_from,
        "allowed_marks": list(snap.allowed_marks or []),
        "allowed_basic_energy_types": list(snap.allowed_basic_energy_types or []),
        "whitelist_cards": [dict(w) for w in (snap.whitelist_cards or [])],
        "banned_cards": [dict(b) for b in (snap.banned_cards or [])],
        "mark_overrides": [dict(m) for m in (snap.mark_overrides or [])],
    }


def _handle_regulation_change(
    db_path: Path, proposals_dir: Path, target: PageTarget,
    blocks: list[tuple[str, str]], serialized: str,
    emit: Callable[[str, dict[str, Any]], None], result: L1Result,
) -> None:
    parsed = parse_regulation(blocks)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for fmt in ("standard", "open"):
            current = _current_snapshot(session, fmt)
            if current is None:
                result.noop.append(f"regulation:{fmt}")
                continue
            pf = parsed.formats[fmt]
            effective_from = pf.effective_from or current.effective_from
            fields = _seed_fields_from_current(current, f"{fmt}-{effective_from.isoformat()}")
            fields["effective_from"] = effective_from
            if pf.allowed_marks is not None:
                fields["allowed_marks"] = pf.allowed_marks
            if pf.whitelist:
                fields["whitelist_cards"] = [dict(w) for w in pf.whitelist]
            if fmt == "open" and pf.banned:
                fields["banned_cards"] = [dict(b) for b in pf.banned]
            diff = _diff_fields(
                {
                    "effective_from": current.effective_from,
                    "allowed_marks": list(current.allowed_marks or []),
                    "allowed_basic_energy_types": list(
                        current.allowed_basic_energy_types or []
                    ),
                    "whitelist_cards": [dict(w) for w in (current.whitelist_cards or [])],
                    "banned_cards": [dict(b) for b in (current.banned_cards or [])],
                },
                fields,
            )
            if not diff:
                continue
            # 与当前快照同 id（内容变但生效日未变）→ 加 -rev 后缀避免撞号
            if fields["snapshot_id"] == current.snapshot_id:
                fields["snapshot_id"] += "-rev"
            status = "needs_manual" if parsed.parse_errors else "pending_review"
            path = _write_proposal(
                proposals_dir, fields, source_url=target.url, status=status,
                diff=diff, parse_errors=parsed.parse_errors, raw_excerpt=serialized,
            )
            result.proposals.append(path)
            emit("proposal", {"page_id": "regulation", "format": fmt,
                              "status": status, "path": str(path)})
    engine.dispose()
    if not result.proposals:
        result.noop.append("regulation")
        emit("noop", {"page_id": "regulation"})


def _handle_stub_change(
    db_path: Path, proposals_dir: Path, target: PageTarget, note: str,
    serialized: str, emit: Callable[[str, dict[str, Any]], None], result: L1Result,
) -> None:
    """extra/news 变更：无法自动结构化 → needs_manual 提案（字段沿用当前快照）。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        current = _current_snapshot(session, "standard") or _current_snapshot(session, "open")
    engine.dispose()
    if current is None:
        return
    today = date.today()
    fields = _seed_fields_from_current(current, f"manual-{today.isoformat()}")
    path = _write_proposal(
        proposals_dir, fields, source_url=target.url, status="needs_manual",
        diff={}, parse_errors=[note], raw_excerpt=serialized,
    )
    result.proposals.append(path)
    emit("proposal", {"page_id": target.page_id, "status": "needs_manual", "path": str(path)})


# ---- 主流程 ----


def run_l1(
    fetcher: Callable[[str], str],
    db_path: Path,
    store_dir: Path,
    proposals_dir: Path,
    *,
    baseline: bool = False,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> L1Result:
    """L1 主流程：逐页抓取 → 提取 → hash 比对 → 变更生成提案并更新快照存储。

    baseline=True 只建基线（不比对、不出提案）。
    """

    def emit(event: str, payload: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event, payload)

    result = L1Result()
    for target in PAGE_TARGETS:
        html = fetcher(target.url)
        if target.kind == "news":
            entries = extract_news_entries(html)
            blocks: list[tuple[str, str]] = []
            serialized = serialize_news(entries)
        else:
            entries = None
            blocks = extract_blocks(html)
            serialized = serialize_blocks(blocks)
        digest = content_hash(serialized)
        store = _load_store(store_dir, target.page_id)

        if baseline or store is None:
            _write_store(store_dir, target.page_id, target.url, digest, serialized, entries)
            result.baselines.append(target.page_id)
            emit("baseline", {"page_id": target.page_id})
            continue
        if store["hash"] == digest:
            result.unchanged.append(target.page_id)
            emit("unchanged", {"page_id": target.page_id})
            continue

        emit("changed", {"page_id": target.page_id, "old_hash": store["hash"],
                         "new_hash": digest})
        if target.page_id == "regulation":
            _handle_regulation_change(
                db_path, proposals_dir, target, blocks, serialized, emit, result
            )
        elif target.page_id == "extra":
            _handle_stub_change(
                db_path, proposals_dir, target,
                "“特别的卡牌”页内容变更：可能涉及赛制标记视作覆盖/机制说明，需人工核对",
                serialized, emit, result,
            )
        elif target.page_id == "news":
            old_hrefs = {e["href"] for e in store.get("entries", [])}
            new_entries = [e for e in (entries or []) if e.href not in old_hrefs]
            for e in new_entries:
                payload = {"href": e.href, "title": e.title, "date": e.date}
                result.news.append(payload)
                emit("news", payload)
            flagged = [e for e in new_entries if NEWS_KEYWORDS.search(e.title)]
            if flagged:
                titles = "；".join(f"{e.title}（{e.href}）" for e in flagged)
                _handle_stub_change(
                    db_path, proposals_dir, target,
                    f"公告命中赛制关键词，需人工核对：{titles}",
                    serialized, emit, result,
                )
        _write_store(store_dir, target.page_id, target.url, digest, serialized, entries)
    return result

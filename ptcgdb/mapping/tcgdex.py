"""task 023：TCGdex 接入与 EN→TCGdex ID 解析 + 系列级跨源对账。

数据获取（低频只读）：TCGdex `/v2/en/cards` `/v2/ja/cards` `/v2/zh-cn/sets`
+ pokemon-tcg-data `sets/en.json`（ptcgoCode → set id 桥，与 TCGdex set id 同体系）。

实测事实（task 023）：**TCGdex EN/JA 卡 id 不共构**（EN `sm3-20` / JA 自体系
`SV8-001`，交集仅个位数）——PRD v1.5 "同 ID 多语言共构"前提证伪，JP 侧设计
在 task 024 前需修订；本任务只做 EN 侧解析与 zh-cn 系列壳对账。
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ptcgdb.orm import Card, ExternalId, Set
from ptcgdb.scrapers.raw_store import read_raw

logger = logging.getLogger(__name__)

TCGDEX_BASE = "https://api.tcgdex.net/v2"
PTCD_SETS_URL = (
    "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/sets/en.json"
)

FETCH_TARGETS = [
    (f"{TCGDEX_BASE}/en/cards", "tcgdex/en-cards.json", "cards", "tcgdex"),
    (f"{TCGDEX_BASE}/en/sets", "tcgdex/en-sets.json", "sets", "tcgdex"),
    (f"{TCGDEX_BASE}/ja/cards", "tcgdex/ja-cards.json", "cards", "tcgdex"),
    (f"{TCGDEX_BASE}/zh-cn/sets", "tcgdex/zh-cn-sets.json", "sets", "tcgdex"),
    (PTCD_SETS_URL, "pokemon-tcg-data/sets-en.json", "sets", "pokemon_tcg_data"),
]

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_OVERRIDES_PATH = CONFIG_DIR / "tcgdex_set_map_overrides.yml"


def fetch_raw(raw_dir: Path, force: bool = False) -> list[str]:
    """下载 TCGdex / pokemon-tcg-data 静态数据入 raw 层（append-only，低频只读）。"""
    import httpx

    from ptcgdb.scrapers.raw_store import write_raw

    written: list[str] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for url, rel, key, source in FETCH_TARGETS:
            path = raw_dir / rel
            resp = client.get(url)
            resp.raise_for_status()
            payload = {key: resp.json()}
            if write_raw(path, payload, source=source, force=force):
                written.append(rel)
    return written


def _load(raw_dir: Path, rel: str, key: str) -> list[dict]:
    doc = read_raw(raw_dir / rel)
    if doc is None:
        raise FileNotFoundError(f"raw 缺失或 hash 无效: {raw_dir / rel}")
    return doc[key]


def _join_set_candidates(raw_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """setCodeEn(=ptcgoCode) → [(ptcd 系列名, TCGdex set id), ...]（名字连接）。

    名字连接（task 023 实测：SV 代起 ptcd id 与 TCGdex id 分叉，如 sv2 vs sv02，
    直连不可靠）：ptcd(ptcgoCode→name) × TCGdex en-sets(name→id)。
    ptcd 同一 ptcgoCode 常有主套 + 子集两条目（如 ASR = Astral Radiance /
    Astral Radiance Trainer Gallery），全部保留，由调用方按名长取舍。
    """
    tcgdex_by_name: dict[str, str] = {}
    for s in _load(raw_dir, "tcgdex/en-sets.json", "sets"):
        tcgdex_by_name[normalize_name(s["name"])] = s["id"]
    result: dict[str, list[tuple[str, str]]] = {}
    for s in _load(raw_dir, "pokemon-tcg-data/sets-en.json", "sets"):
        ptcgo = s.get("ptcgoCode")
        if not ptcgo:
            continue
        tcgdex_id = tcgdex_by_name.get(normalize_name(s["name"]))
        if tcgdex_id:
            result.setdefault(ptcgo, []).append((s["name"], tcgdex_id))
    return result


def load_set_map(
    raw_dir: Path, overrides_path: Path | None = DEFAULT_OVERRIDES_PATH
) -> dict[str, str]:
    """setCodeEn(=ptcgoCode) → TCGdex 主套 set id。

    同码多条目取最短名（主套，子集名是主套名的扩展）；
    促销/能量等 mik 自造码由词表覆盖文件兜底。
    """
    result = {
        ptcgo: min(cands, key=lambda c: len(c[0]))[1]
        for ptcgo, cands in _join_set_candidates(raw_dir).items()
    }
    if overrides_path is not None and overrides_path.exists():
        overrides = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}
        result.update(overrides)
    return result


def load_subset_map(raw_dir: Path) -> dict[str, str]:
    """setCodeEn → TCGdex 子套 set id（Trainer/Galarian Gallery、Shiny Vault 等）。

    同码多条目里除最短名（主套）外的那条；无子套则无键。
    """
    result: dict[str, str] = {}
    for ptcgo, cands in _join_set_candidates(raw_dir).items():
        ordered = sorted(cands, key=lambda c: len(c[0]))
        if len(ordered) > 1:
            result[ptcgo] = ordered[1][1]
    return result


def load_en_cards(raw_dir: Path) -> dict[str, str]:
    """TCGdex EN 卡索引：id → name。"""
    return {c["id"]: c["name"] for c in _load(raw_dir, "tcgdex/en-cards.json", "cards")}


def _suffix_index(en_cards: dict[str, str]) -> dict[tuple[str, str], str]:
    """(set id, localId 数字尾) → 卡 id：字母前缀编号（SM25 / SWSH017）的兜底查找。

    仅收录无歧义项（实测全库无冲突）；冲突则放弃该键（不猜）。
    """
    hits: dict[tuple[str, str], str] = {}
    ambiguous: set[tuple[str, str]] = set()
    for card_id in en_cards:
        set_id, _, local_id = card_id.rpartition("-")
        m = re.fullmatch(r"[A-Za-z]+(\d+)", local_id)
        if not m:
            continue
        key = (set_id, str(int(m.group(1))))
        if key in hits:
            ambiguous.add(key)
        hits.setdefault(key, card_id)
    for key in ambiguous:
        logger.warning("_suffix_index: 歧义键 %s 已丢弃，涉及 card_id %s", key, hits.get(key, "?"))
        hits.pop(key, None)
    return hits


def normalize_name(name: str) -> str:
    """卡名归一（跨源比较用）：去非字母数字、小写、去变音符。

    mik "Charizard-GX" ≡ TCGdex "Charizard GX"；"Poké" ≡ "Poke"。
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", name.casefold())
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_only)


def names_equivalent(mik_name: str, tcgdex_name: str) -> bool:
    """mik / TCGdex 卡名等价判定（命名惯例差异豁免，仅用于解析校验，不写库）。

    豁免规则（task 023 实测三类系统性差异）：
    1. TCGdex 尾缀人物括注："Professor's Research (Professor Magnolia)" ≡
       mik "Professor's Research"——比较前剥掉 TCGdex 尾缀 "(...)"。
    2. SM 代棱镜星：mik "X Prism Star" ≡ TCGdex "X ◇"——归一后剥 mik 尾缀
       "prismstar"（"◇" 在归一中已消失）。
    3. 其余交给 normalize_name（连字符/大小写/变音符不敏感）。
    """
    tcg_base = re.sub(r"\s*\([^)]*\)\s*$", "", tcgdex_name)
    mik_norm = normalize_name(mik_name)
    if mik_norm.endswith("prismstar"):
        mik_norm = mik_norm[: -len("prismstar")]
    return mik_norm == normalize_name(tcg_base)


@dataclass
class ResolveResult:
    total: int = 0
    resolved: list[str] = field(default_factory=list)  # card_id（解析成功且名字一致）
    tcgdex_ids: dict[str, str] = field(default_factory=dict)  # card_id → tcgdex id
    unmapped_set: dict[str, list[str]] = field(default_factory=dict)  # setCodeEn → card_ids
    missing_card: list[str] = field(default_factory=list)  # 候选 id 不在 TCGdex
    name_mismatch: list[str] = field(default_factory=list)  # id 命中但名字不一致


def resolve_en(
    db_path: Path, raw_dir: Path, overrides_path: Path | None = DEFAULT_OVERRIDES_PATH
) -> ResolveResult:
    """external_ids(mik_en) → TCGdex card id 解析（不猜：四类结果全记录）。"""
    set_map = load_set_map(raw_dir, overrides_path)
    subset_map = load_subset_map(raw_dir)
    en_cards = load_en_cards(raw_dir)
    suffix_index = _suffix_index(en_cards)
    engine = create_engine(f"sqlite:///{db_path}")
    result = ResolveResult()
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(ExternalId.card_id, ExternalId.external_id, Card.name_en)
                .join(Card, Card.card_id == ExternalId.card_id)
                .where(ExternalId.system == "mik_en")
            ).all()
    finally:
        engine.dispose()
    result.total = len(rows)
    for card_id, external_id, name_en in rows:
        set_code_en, _, card_index_en = external_id.partition("-")
        tcgdex_set = set_map.get(set_code_en)
        if tcgdex_set is None:
            result.unmapped_set.setdefault(set_code_en, []).append(card_id)
            continue
        candidate = f"{tcgdex_set}-{card_index_en}"
        tcgdex_name = en_cards.get(candidate)
        if tcgdex_name is None and card_index_en.isdigit():
            # TCGdex 部分套 localId 零填充（如 sv01-1 vs sv01-001）
            candidate = f"{tcgdex_set}-{card_index_en.zfill(3)}"
            tcgdex_name = en_cards.get(candidate)
        if tcgdex_name is None and card_index_en.isdigit():
            # 字母前缀编号兜底（SMP-25 → smp-SM25、SP-17 → swshp-SWSH017）
            suffix_hit = suffix_index.get((tcgdex_set, str(int(card_index_en))))
            if suffix_hit is not None:
                candidate = suffix_hit
                tcgdex_name = en_cards[candidate]
        if tcgdex_name is None:
            prefixed = re.fullmatch(r"([A-Za-z]+)(\d+)", card_index_en)
            if prefixed:
                # 子集套编号（GG/TG/SV 前缀）：主套 + 子集套、原样/两位/三位填充全试
                prefix, digits = prefixed.groups()
                variants = dict.fromkeys(
                    [card_index_en, f"{prefix}{digits.zfill(2)}", f"{prefix}{digits.zfill(3)}"]
                )
                subset_set = subset_map.get(set_code_en)
                for ts in [tcgdex_set, subset_set]:
                    if ts is None:
                        continue
                    for variant in variants:
                        trial = f"{ts}-{variant}"
                        if trial in en_cards:
                            candidate, tcgdex_name = trial, en_cards[trial]
                            break
                    if tcgdex_name is not None:
                        break
        if tcgdex_name is None:
            result.missing_card.append(card_id)
            continue
        result.tcgdex_ids[card_id] = candidate
        if name_en and names_equivalent(name_en, tcgdex_name):
            result.resolved.append(card_id)
        else:
            result.name_mismatch.append(card_id)
    return result


@dataclass
class SetReconcileRow:
    set_id: str
    status: str  # ok / count_diff / name_diff / missing_in_db / missing_in_tcgdex
    tcgdex_total: int | None = None
    db_count: int | None = None
    note: str = ""


@dataclass
class SetReconcileReport:
    rows: list[SetReconcileRow] = field(default_factory=list)


def reconcile_sets(db_path: Path, raw_dir: Path) -> SetReconcileReport:
    """系列级跨源对账：TCGdex zh-cn 系列壳（名称+卡数）vs 本库 sets。"""
    zhcn = _load(raw_dir, "tcgdex/zh-cn-sets.json", "sets")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            db_sets = {s.set_id: s for s in session.scalars(select(Set))}
            db_counts = dict(
                session.execute(
                    select(Card.set_id, func.count()).group_by(Card.set_id)
                ).all()
            )
    finally:
        engine.dispose()
    report = SetReconcileReport()
    seen: set[str] = set()
    for entry in zhcn:
        sid = entry["id"]
        total = (entry.get("cardCount") or {}).get("total")
        name = entry.get("name") or ""
        db_set = db_sets.get(sid)
        if db_set is None:
            report.rows.append(
                SetReconcileRow(sid, "missing_in_db", tcgdex_total=total,
                                note=f"TCGdex 有壳本库无：{name}")
            )
            continue
        seen.add(sid)
        count = db_counts.get(sid, 0)
        note = ""
        status = "ok"
        if total is not None and total != count:
            status = "count_diff"
            note = f"TCGdex total={total} vs 本库 {count}"
        if name and db_set.name_zh and name != db_set.name_zh:
            note = f"{note}；名称差异：TCGdex「{name}」vs 本库「{db_set.name_zh}」".strip("；")
            if status == "ok":
                status = "name_diff"
        report.rows.append(
            SetReconcileRow(sid, status, tcgdex_total=total, db_count=count, note=note)
        )
    for sid in sorted(set(db_sets) - seen):
        report.rows.append(
            SetReconcileRow(sid, "missing_in_tcgdex", db_count=db_counts.get(sid, 0),
                            note=f"本库有 TCGdex 无壳：{db_sets[sid].name_zh}")
        )
    return report

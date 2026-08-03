"""task 030（F-03）：太晶识别——ptcd EN 卡 `subtypes` 印刷级富化 `cards.is_tera`。

背景：mik 源不提供太晶信号（A2 比对实测翻案 v1.4 ⑤"暂无太晶样本"旧注），
ingest 期 `derive_is_tera` 判据永假。pokemon-tcg-data EN 卡 `subtypes` 数组
带结构化 'Tera' 标记（印刷级，实测 sv3/sv5/sv7/sv8pt5 全中）。

链路：cards ⋈ external_ids(mik_en)（'{setCodeEn}-{cardIndexEn}'，印刷级）
→ ptcd sets-en（ptcgoCode → set id）→ ptcd cards-en 该卡 subtypes 含 'Tera'。
幂等：可解析卡按结论重写 is_tera；无桥/未解析不动并入清单，不猜测。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.orm import Card, ExternalId


@dataclass
class TeraMapResult:
    total: int = 0
    bridged: int = 0  # 有 mik_en 桥
    tera: int = 0  # 判定为太晶
    resolved_non_tera: int = 0
    no_bridge: list[str] = field(default_factory=list)
    unmapped_set: list[str] = field(default_factory=list)  # ptcgoCode 无 ptcd 系列
    missing_card: list[str] = field(default_factory=list)  # ptcd 系列内查无此号


def _load_ptcd_set_map(raw_dir: Path) -> dict[str, str]:
    """ptcgoCode → ptcd set id（sets-en.json）。"""
    doc = json.loads(
        (Path(raw_dir) / "pokemon-tcg-data" / "sets-en.json").read_text(encoding="utf-8")
    )
    sets = doc["sets"] if isinstance(doc, dict) else doc
    return {s["ptcgoCode"]: s["id"] for s in sets if s.get("ptcgoCode")}


def _load_ptcd_tera_index(raw_dir: Path) -> dict[str, dict[str, bool]]:
    """ptcd set id → {编号(含前导零变体): 是否太晶}。raw 层只读。"""
    index: dict[str, dict[str, bool]] = {}
    for path in sorted((Path(raw_dir) / "pokemon-tcg-data" / "cards-en").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        cards = doc["cards"] if isinstance(doc, dict) else doc
        set_id = path.stem
        bucket = index.setdefault(set_id, {})
        for card in cards:
            is_tera = "Tera" in (card.get("subtypes") or [])
            num = str(card.get("number") or "")
            for variant in {num, num.lstrip("0") or "0", num.zfill(3)}:
                # 同号多变体冲突时 Tera 优先（同号异印刷理论上一致，防御性处理）
                bucket[variant] = bucket.get(variant, False) or is_tera
    return index


def fill_tera(db_path: Path, raw_dir: Path) -> TeraMapResult:
    """全库扫描填充 is_tera。返回统计与未解析清单（按 card_id 排序）。"""
    set_map = _load_ptcd_set_map(raw_dir)
    tera_index = _load_ptcd_tera_index(raw_dir)
    engine = create_engine(f"sqlite:///{db_path}")
    result = TeraMapResult()
    with Session(engine) as session:
        bridges = dict(
            session.execute(
                select(ExternalId.card_id, ExternalId.external_id).filter_by(system="mik_en")
            ).all()
        )
        cards = list(session.scalars(select(Card)))
        result.total = len(cards)
        for card in cards:
            ext = bridges.get(card.card_id)
            if not ext or "-" not in ext:
                result.no_bridge.append(card.card_id)
                continue
            result.bridged += 1
            code, _, num = ext.partition("-")
            ptcd_set = set_map.get(code)
            if ptcd_set is None:
                result.unmapped_set.append(card.card_id)
                continue
            bucket = tera_index.get(ptcd_set) or {}
            hit = None
            for variant in {num, num.lstrip("0") or "0", num.zfill(3)}:
                if variant in bucket:
                    hit = bucket[variant]
                    break
            if hit is None:
                result.missing_card.append(card.card_id)
                continue
            card.is_tera = hit
            if hit:
                result.tera += 1
            else:
                result.resolved_non_tera += 1
        session.commit()
    engine.dispose()
    result.no_bridge.sort()
    result.unmapped_set.sort()
    result.missing_card.sort()
    return result

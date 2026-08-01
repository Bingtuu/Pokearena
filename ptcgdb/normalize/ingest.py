"""入库管线：raw 层 JSON → sets/cards/name_groups/card_relations（status=draft）。

raw 层只读；入库幂等（重跑覆盖 draft 行）。校验（draft→active）在 task 005。
未知枚举零猜测：映射失败记 question 并跳过该卡（不入库），由报告呈现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.normalize import derive, fields
from ptcgdb.normalize.fields import Questions, UnknownEnumError
from ptcgdb.orm import Card, CardNameGroup, CardRelation, NameGroup, Set
from ptcgdb.scrapers.raw_store import read_raw

SOURCE = "mik_moe"


@dataclass
class IngestResult:
    set_id: str
    card_count: int = 0
    skipped: list[str] = field(default_factory=list)
    questions: Questions = field(default_factory=Questions)


@dataclass
class _Context:
    code_map: dict[str, str]
    card_type_map: dict[str, tuple[str, str | None]]
    stage_map: dict[str, str]
    rarities: set[str]
    owners: list[str]
    name_group_rules: list[dict[str, str]]
    cards_num: int | None
    questions: Questions


def normalize_card(
    data: dict[str, Any], fetched_at: datetime, ctx: _Context
) -> dict[str, Any]:
    """单卡 card-detail data → Card 表字段 dict。未知枚举抛 UnknownEnumError。"""
    card_id = f"{data['setCode']}-{data['cardIndex']}"
    card_type, trainer_subtype = fields.map_card_type(data["cardType"], ctx.card_type_map)
    number, number_display = fields.split_number(data["cardIndex"], ctx.cards_num)
    name_full = data["name"]
    owner, species = derive.split_owner_species(name_full, ctx.owners)
    mechanic = data.get("mechanic")
    label = data.get("label") or None
    pa = data.get("pokemonAttr") or {}
    stage = fields.map_stage(pa.get("stage"), ctx.stage_map)
    rule_box_type, effect_tags = derive.derive_rule_box(
        mechanic, label, ctx.questions, card_id, stage=pa.get("stage")
    )
    is_ace_spec = derive.derive_is_ace_spec(mechanic, label, name_full)
    is_basic_energy, provides = derive.derive_basic_energy(
        data["cardType"], name_full, ctx.questions, card_id
    )
    rarity = data["rarity"]
    if rarity not in ctx.rarities:
        ctx.questions.add(card_id, "rarity", rarity, "罕贵度不在词表（开放词表，原值入库）")

    abilities = [
        {"name": a.get("name") or "", "text": a.get("text") or ""}
        for a in pa.get("ability") or []
    ]
    attacks = [fields.parse_attack(a, ctx.code_map) for a in pa.get("attack") or []]
    types = None
    if pa.get("energyType"):
        types = [fields.map_energy(pa["energyType"], ctx.code_map)]

    return {
        "card_id": card_id,
        "set_id": data["setCode"],
        "number": number,
        "number_display": number_display,
        "name_full": name_full,
        "species": species if card_type == "pokemon" else None,
        "owner": owner,
        "card_type": card_type,
        # 空串/缺省统一存 NULL（task 005 实测：基本能量 regulationMark=""，无赛制标记）
        "regulation_mark": data.get("regulationMark") or None,
        "rarity": rarity,
        "stage": stage,
        "hp": pa.get("hp"),
        "types": types,
        "evolves_from_text": pa.get("evolvesFrom") or None,
        "evolves_from_id": None,
        "evolution_chain_id": None,
        "rule_box_type": rule_box_type,
        "has_rule_box": rule_box_type is not None,
        "is_tera": derive.derive_is_tera(mechanic, label, name_full),
        "union_position": None,
        "prize_cards": derive.derive_prize_cards(rule_box_type),
        "deck_limit": derive.derive_deck_limit(rule_box_type, is_ace_spec),
        "is_ace_spec": is_ace_spec,
        "abilities": abilities or None,
        "attacks": attacks or None,
        "weakness": fields.parse_weak_res(pa.get("weakness"), ctx.code_map),
        "resistance": fields.parse_weak_res(pa.get("resistance"), ctx.code_map),
        "retreat_cost": pa.get("retreatCost"),
        "trainer_subtype": trainer_subtype,
        "provides": provides,
        "is_basic_energy": is_basic_energy,
        # text_raw 逐字保留，绝不规范化（PRD §6.4）
        "text_raw": data.get("description") or "",
        "effect_tags": effect_tags,
        "name_en": data.get("nameEn") or None,
        "name_ja": None,
        "name_zh_tw": None,
        "source": SOURCE,
        "fetched_at": fetched_at,
        "status": "draft",
    }


def _build_set_row(
    cards_doc: dict[str, Any],
    records: list[dict[str, Any]],
    era_map: dict[str, str],
    questions: Questions,
    set_id: str,
) -> Set:
    data = cards_doc["data"]
    series = data.get("series") or ""
    era = era_map.get(series)
    if not era:
        questions.add(None, "series", series, "未知 series，era 置为'未划分'")
        era = "未划分"
    release_raw = data.get("releaseDate") or ""
    release_date = datetime.fromisoformat(release_raw).date() if release_raw else None
    # mik 占位垃圾日期（特典系列实测 0001-01-01，task 005）按 NULL 处理
    if release_date is not None and release_date.year <= 1:
        release_date = None
    # 无赛制标记的卡（regulation_mark=None，如基本能量）不参与系列级标记汇总
    marks = sorted({r["regulation_mark"] for r in records if r["regulation_mark"] is not None})
    if len(marks) > 1:
        questions.add(
            None, "regulation_mark", marks, "系列内赛制标记不唯一，sets 行存逗号连接值"
        )
    # set_id 用目录名（= product setId）：特典系列 product setCode 为内部分组值
    # "PROMO"，与卡级 setCode（SMP/SSP/SVP/30thP）不一致（task 005 实测）
    return Set(
        set_id=set_id,
        name_zh=data["name"],
        era=era,
        release_date=release_date,
        regulation_mark=",".join(marks),
        expected_count=data.get("cardsNum"),
        expected_secret_count=None,
        source=SOURCE,
        fetched_at=(cards_doc.get("_meta") or {}).get("fetched_at") or "",
    )


def ingest_set(
    raw_dir: Path,
    set_id: str,
    db_path: Path,
    config_dir: Path | None = None,
) -> IngestResult:
    """把 raw_dir/mikmoe/{set_id} 下的 raw 入库为 draft。raw 层只读。"""
    questions = Questions()
    vocab_dir = (Path(config_dir) / "vocabularies") if config_dir else fields.VOCAB_DIR
    ctx = _Context(
        code_map=fields.load_energy_code_map(vocab_dir),
        card_type_map=fields.load_card_type_map(vocab_dir),
        stage_map=fields.load_stage_map(vocab_dir),
        rarities=fields.load_rarities(vocab_dir),
        owners=fields.load_owners(vocab_dir),
        name_group_rules=derive.load_name_group_rules(config_dir),
        cards_num=None,
        questions=questions,
    )
    result = IngestResult(set_id=set_id, questions=questions)

    set_dir = Path(raw_dir) / "mikmoe" / set_id
    cards_doc = read_raw(set_dir / "cards.json")
    if cards_doc is None:
        raise FileNotFoundError(f"raw 缺失或 hash 无效: {set_dir / 'cards.json'}")
    ctx.cards_num = (cards_doc.get("data") or {}).get("cardsNum")

    records: list[dict[str, Any]] = []
    card_files = sorted(
        p for p in set_dir.glob("*.json") if p.name != "cards.json"
    )
    for path in card_files:
        doc = read_raw(path)
        if doc is None:
            questions.add(None, "raw", path.name, "raw 文件缺失或 hash 无效，跳过")
            result.skipped.append(path.name)
            continue
        fetched_at = datetime.fromisoformat(doc["_meta"]["fetched_at"])
        card_id = f"{set_id}-{path.stem}"
        try:
            records.append(normalize_card(doc["data"], fetched_at, ctx))
        except UnknownEnumError as exc:
            questions.add(card_id, "enum", None, f"未知枚举，卡片未入库: {exc}")
            result.skipped.append(path.name)

    # 派生：进化链解析 + 同名归组（全量记录就绪后）
    derive.resolve_evolution(records, questions)
    group_keys = {
        rec["card_id"]: derive.name_group_key(rec["name_full"], ctx.name_group_rules)
        for rec in records
    }
    rule_notes = {r["base"]: r.get("note") for r in ctx.name_group_rules}

    apply_migrations(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.merge(
            _build_set_row(cards_doc, records, fields.load_era_map(vocab_dir), questions, set_id)
        )
        # 幂等：清掉本系列旧的归组/关系/卡牌 draft 行再写入
        card_ids = [r["card_id"] for r in records]
        if card_ids:
            session.execute(
                delete(CardRelation).where(CardRelation.card_id.in_(card_ids))
            )
            session.execute(
                delete(CardNameGroup).where(CardNameGroup.card_id.in_(card_ids))
            )
            session.execute(delete(Card).where(Card.card_id.in_(card_ids)))
        for rec in records:
            session.add(Card(**rec))
        for key in sorted(set(group_keys.values())):
            session.merge(
                NameGroup(
                    group_key=key,
                    display_name=key,
                    rule_note=rule_notes.get(key),
                )
            )
        for card_id, key in sorted(group_keys.items()):
            session.add(CardNameGroup(card_id=card_id, group_key=key))
        for card_id, related_id, rel_type in derive.evolve_relations(records):
            session.add(
                CardRelation(
                    card_id=card_id,
                    related_card_id=related_id,
                    relation_type=rel_type,
                    confidence="high",
                    source=SOURCE,
                )
            )
        session.commit()
    engine.dispose()

    result.card_count = len(records)
    return result

"""A2/A3 抽样比对工具（task 017，PRD §10 A2/A3）。

卡面人工比对需要官方小程序（无 API，D1 已否决）——本模块交付工具与清单：
- A2：固定种子随机抽样（可复现）→ 逐字段人工比对清单（含小程序查卡指引）
- A3：特殊卡机制字段自动一致性校验（全量，五项规则）+ 抽样卡面核对清单
不符项如实记录、标记需人工裁决，不猜测性修数据。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.orm import Card, CardRelation

DEFAULT_SEED = 20260801

# PRD A3 已核实的奖赏卡规则（v/vmax/vstar/prism_star/radiant 不在官方已核口径内，不检查）
PRIZE_RULES = {"ex": 2, "gx": 2, "tag_team_gx": 3, "v_union": 3, "mega_ex": 3}
UNION_POSITIONS = {"左上", "右上", "左下", "右下"}

A2_FIELDS = (
    "卡名", "商品编号/卡号", "赛制标记", "罕贵度", "HP/属性", "特性",
    "招式（名/费用/伤害/效果）", "弱点", "抵抗力", "撤退费用", "text_raw 逐字",
)


@dataclass
class A3Result:
    checked: int = 0
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # 豁免/已知缺口（如实记录，非失败）

    @property
    def passed(self) -> bool:
        return not self.failures


def sample_cards(db_path: Path, n: int, seed: int = DEFAULT_SEED) -> list[str]:
    """固定种子随机抽 n 张 active 卡（可复现），返回 card_id 列表。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        ids = session.scalars(
            select(Card.card_id).where(Card.status == "active").order_by(Card.card_id)
        ).all()
    engine.dispose()
    rng = random.Random(seed)
    return sorted(rng.sample(ids, min(n, len(ids))))


def write_a2_checklist(
    db_path: Path, out_dir: Path, n: int = 100, seed: int = DEFAULT_SEED,
    *, today: date | None = None,
) -> Path:
    """A2：抽样 → 逐字段人工比对清单 markdown。"""
    today = today or date.today()
    ids = sample_cards(db_path, n, seed)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        cards = {c.card_id: c for c in session.scalars(
            select(Card).where(Card.card_id.in_(ids))
        )}
    engine.dispose()

    lines = [
        f"# A2 字段抽样人工比对清单（{today.isoformat()}，{len(ids)} 张，seed={seed}）",
        "",
        "## 比对方法",
        "",
        "1. 打开微信小程序「宝可梦卡牌会员」→ 卡牌图鉴；",
        "2. 按每张卡的**系列 + 卡号**检索（或扫卡名），打开卡面详情；",
        "3. 逐项核对下列字段，一致打勾；任一项不符，在卡号后标注差异并告知维护者；",
        "4. text_raw 为卡面全部文字逐字比对（含标点）。",
        "",
        f"抽样口径：status=active 全库固定种子随机（seed={seed}，同 seed 可复现同一批）。",
        "",
    ]
    for cid in ids:
        c = cards[cid]
        lines += [
            f"### {cid} {c.name_full}",
            "",
            (
                f"- 系列/卡号：`{c.set_id}` `{c.number_display}`"
                f"（库内赛制标记 {c.regulation_mark or '无'}，罕贵 {c.rarity}）"
            ),
        ]
        for field_label in A2_FIELDS:
            lines.append(f"- [ ] {field_label}")
        lines.append("")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"sampling-a2-{today:%Y%m%d}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _check_prize(cards: list[Card], res: A3Result) -> None:
    for c in cards:
        expected = PRIZE_RULES.get(c.rule_box_type or "")
        if expected is not None:
            res.checked += 1
            if c.prize_cards != expected:
                res.failures.append(
                    f"{c.card_id} {c.name_full}: rule_box={c.rule_box_type} "
                    f"奖赏应为 {expected}，实为 {c.prize_cards}"
                )


def _check_ace_spec(cards: list[Card], res: A3Result) -> None:
    for c in cards:
        if c.is_ace_spec:
            res.checked += 1
            # ACE SPEC 含特殊能量卡（新冲天/遗赠/富裕能量，task 017 实测），
            # 只校验 deck_limit，不限 card_type
            if c.deck_limit != 1:
                res.failures.append(
                    f"{c.card_id} {c.name_full}: ACE SPEC 应 deck_limit=1，"
                    f"实为 deck_limit={c.deck_limit}"
                )


def _check_union(cards: list[Card], session: Session, res: A3Result) -> None:
    union_cards = [c for c in cards if c.union_position]
    if not union_cards:
        return
    rels = session.scalars(
        select(CardRelation).where(CardRelation.relation_type == "union_part_of")
    ).all()
    partners: dict[str, set[str]] = {}
    for r in rels:
        partners.setdefault(r.card_id, set()).add(r.related_card_id)
    # 按关系连通分量分组，每组应 4 部件且方位齐全
    visited: set[str] = set()
    for c in union_cards:
        res.checked += 1
        if c.card_id not in partners:
            res.failures.append(
                f"{c.card_id} {c.name_full}: union_position={c.union_position}"
                f" 但无 union_part_of 关系"
            )
        if c.union_position not in UNION_POSITIONS:
            res.failures.append(
                f"{c.card_id} {c.name_full}: 未知 V-UNION 方位 {c.union_position}"
            )
    for c in union_cards:
        if c.card_id in visited:
            continue
        group = {c.card_id, *partners.get(c.card_id, set())}
        visited |= group
        res.checked += 1
        positions = {x.union_position for x in union_cards if x.card_id in group}
        if len(group) != 4 or positions != UNION_POSITIONS:
            res.failures.append(
                f"V-UNION 组 {sorted(group)}: 部件数 {len(group)}，"
                f"方位 {sorted(p for p in positions if p)}（应 4 部件且方位齐全）"
            )


def _check_owner(cards: list[Card], res: A3Result) -> None:
    for c in cards:
        prefix_owner = None
        for o in ("火箭队", "莉莉艾", "竹兰", "玛俐", "N"):
            if c.name_full.startswith(f"{o}的"):
                prefix_owner = o
                break
        if c.owner or prefix_owner:
            res.checked += 1
            if c.owner != prefix_owner:
                res.failures.append(
                    f"{c.card_id} {c.name_full}: owner={c.owner} 与卡名前缀归属 "
                    f"{prefix_owner or '无'} 不符"
                )


def _extract_evolves_from_name(text: str) -> str:
    """从进化来源原文提取名字：有「」取内层，否则整体（如 "夜盗火蜥"）。"""
    m = re.search(r"「(.+?)」", text)
    return m[1] if m else text.strip()


def _check_evolution(cards: list[Card], session: Session, res: A3Result) -> None:
    """进化链校验（正确性 + 覆盖率分类记录）：
    - 已解析但指向不存在的卡 → failure（数据坏）
    - 未解析且库中存在同名宝可梦候选 → note（跨系列缺口：derive 只在本系列内解析，
      M1 设计边界，需功能增强而非数据修复）
    - 未解析且库中无同名宝可梦（如"古老的头盖化石"，来源非收录宝可梦）→ note（合理豁免）
    """
    for c in cards:
        if not c.evolves_from_text:
            continue
        res.checked += 1
        if c.evolves_from_id:
            if session.get(Card, c.evolves_from_id) is None:
                res.failures.append(
                    f"{c.card_id} {c.name_full}: 进化来源指向不存在的卡 {c.evolves_from_id}"
                )
            continue
        name = _extract_evolves_from_name(c.evolves_from_text)
        candidates = session.scalars(
            select(Card).where(
                Card.name_full == name, Card.status == "active", Card.card_type == "pokemon"
            )
        ).all()
        if candidates:
            res.notes.append(
                f"{c.card_id} {c.name_full}: 进化来源「{name}」在库（如 {candidates[0].card_id}）"
                f"但未解析——跨系列缺口（derive 系列内解析边界）"
            )
        else:
            res.notes.append(
                f"{c.card_id} {c.name_full}: 进化来源「{name}」非库内宝可梦（化石等），合理未解析"
            )


def run_a3_checks(db_path: Path) -> A3Result:
    """A3 自动一致性校验：全量特殊卡，五项规则（PRD A3 口径）。"""
    res = A3Result()
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        cards = session.scalars(select(Card).where(Card.status == "active")).all()
        _check_prize(cards, res)
        _check_ace_spec(cards, res)
        _check_union(cards, session, res)
        _check_owner(cards, res)
        _check_evolution(cards, session, res)
    engine.dispose()
    return res


def write_a3_report(
    db_path: Path, out_dir: Path, n: int = 50, seed: int = DEFAULT_SEED,
    *, today: date | None = None,
) -> Path:
    """A3：自动校验结果 + 抽 n 张特殊卡的卡面核对清单。"""
    today = today or date.today()
    result = run_a3_checks(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        specials = session.scalars(
            select(Card).where(
                Card.status == "active",
                (Card.has_rule_box.is_(True))
                | (Card.is_ace_spec.is_(True))
                | (Card.owner.isnot(None))
                | (Card.union_position.isnot(None))
                | (Card.evolves_from_text.isnot(None)),
            ).order_by(Card.card_id)
        ).all()
    engine.dispose()
    rng = random.Random(seed)
    sampled = sorted(rng.sample(specials, min(n, len(specials))), key=lambda c: c.card_id)

    lines = [
        f"# A3 机制字段核对报告（{today.isoformat()}）",
        "",
        f"## 自动一致性校验：{'全部通过' if result.passed else '存在不符项（需人工裁决）'}",
        "",
        f"- 校验项次：{result.checked}（全量特殊卡，非抽样）",
    ]
    for f in result.failures:
        lines.append(f"- ✗ {f}")
    if result.notes:
        lines += ["", "### 豁免与已知缺口（如实记录，非失败）", ""]
        for n in result.notes:
            lines.append(f"- {n}")
    lines += [
        "",
        f"## 卡面人工核对清单（{len(sampled)} 张，seed={seed}）",
        "",
        "方法同 A2：小程序「宝可梦卡牌会员」按系列+卡号查卡，核对机制字段（规则框/奖赏卡数/",
        "ACE SPEC 限制/训练家归属/进化链/V-UNION 部件）。",
        "",
    ]
    for c in sampled:
        tags = []
        if c.rule_box_type:
            tags.append(f"rule_box={c.rule_box_type}/prize={c.prize_cards}")
        if c.is_ace_spec:
            tags.append("ACE SPEC")
        if c.owner:
            tags.append(f"owner={c.owner}")
        if c.union_position:
            tags.append(f"V-UNION {c.union_position}")
        if c.evolves_from_text:
            tags.append(f"进化自 {c.evolves_from_id or '?'}")
        lines.append(f"- [ ] `{c.card_id}` {c.name_full}（{'; '.join(tags)}）")
    lines.append("")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"sampling-a3-{today:%Y%m%d}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path

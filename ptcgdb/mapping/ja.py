"""task 024：JP 名字级映射（PRD v1.6）。

链路：CN → mik 英文桥 → TCGdex EN id（task 022/023）→ ptcd 卡数据取 dexId
（nationalPokedexNumbers）→ PokéAPI 物种名表日文名 + 形态/机制词表组合 name_ja。

设计前提（task 023 实测）：TCGdex EN/JA 卡 id 不共构，故不做印刷级配对；
日文卡名跨印刷不变，名字级映射即可。训练家/特殊能量本里程碑不填充（无可靠
批量源），全量入 question 清单——不猜。
"""

import csv
import io
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ptcgdb.mapping.tcgdex import _load, load_set_map, normalize_name, resolve_en
from ptcgdb.orm import Card, ExternalId
from ptcgdb.scrapers.raw_store import write_raw

PTCD_CARDS_URL = (
    "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/cards/en/{}.json"
)
SPECIES_CSV_URL = (
    "https://raw.githubusercontent.com/pokeapi/pokeapi/master/data/v2/csv/"
    "pokemon_species_names.csv"
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_RULES_PATH = CONFIG_DIR / "vocabularies" / "ja_name_rules.yml"

# TCGdex → ptcd 反向名字连接的兜底（名字微差，实测同属一套）：
#   TCGdex "SVP Black Star Promos"      ≡ ptcd "Scarlet & Violet Black Star Promos"
#   TCGdex "Scarlet & Violet Energy"    ≡ ptcd "Scarlet & Violet Energies"
TCGDEX_TO_PTCD_OVERRIDES = {"svp": "svp", "sve": "sve"}


@dataclass
class JaRules:
    prefixes: list[tuple[str, str]]  # (en, ja)，长按降序
    suffixes: list[tuple[str, str]]
    suffix_modifiers: list[tuple[str, str]]  # EN 前置修饰 → JA 后置（" X"）
    basic_energies: dict[str, str]
    tag_team_joiner: str
    variant_letters: set[str]
    owners: dict[str, str]  # EN 归属名 → JA 归属名（"{X}'s" → "{JA}の"）


def load_ja_rules(path: Path = DEFAULT_RULES_PATH) -> JaRules:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return JaRules(
        prefixes=sorted(
            ((e["en"], e["ja"]) for e in doc["prefixes"]), key=lambda p: -len(p[0])
        ),
        suffixes=sorted(
            ((e["en"], e["ja"]) for e in doc["suffixes"]), key=lambda p: -len(p[0])
        ),
        suffix_modifiers=sorted(
            ((e["en"], e["ja"]) for e in doc.get("suffix_modifiers", [])),
            key=lambda p: -len(p[0]),
        ),
        basic_energies={e["en"]: e["ja"] for e in doc["basic_energies"]},
        tag_team_joiner=doc["tag_team_joiner"],
        variant_letters=set(doc["variant_letters"]),
        owners={e["en"]: e["ja"] for e in doc.get("owners", [])},
    )


def _load_species_by_lang(raw_dir: Path, lang_id: int) -> dict[int, str]:
    doc = _load(raw_dir, "pokeapi/pokemon-species-names.json", "csv")
    result: dict[int, str] = {}
    for row in csv.DictReader(io.StringIO(doc)):
        if int(row["local_language_id"]) == lang_id:
            result[int(row["pokemon_species_id"])] = row["name"]
    return result


def load_ja_species(raw_dir: Path) -> dict[int, str]:
    """dexId → 日文物种名（language_id=11 日文；缺则回退 1 ja-Hrkt）。"""
    ja = _load_species_by_lang(raw_dir, 1)
    ja.update(_load_species_by_lang(raw_dir, 11))
    return ja


def load_en_species(raw_dir: Path) -> dict[int, str]:
    return _load_species_by_lang(raw_dir, 9)


def _norm_number(local_id: str) -> tuple[str, int] | None:
    """编号归一：(字母前缀大写, 数字)（"TG02"→("TG",2)，"045"→("",45)）。"""
    m = re.fullmatch(r"([A-Za-z]*)(\d+)", local_id)
    if not m:
        return None
    return (m.group(1).upper(), int(m.group(2)))


def load_tcgdex_to_ptcd(raw_dir: Path) -> dict[str, str]:
    """TCGdex set id → ptcd set id（名字连接反向 + 名字微差覆盖）。"""
    ptcd_by_name = {
        normalize_name(s["name"]): s["id"]
        for s in _load(raw_dir, "pokemon-tcg-data/sets-en.json", "sets")
    }
    result: dict[str, str] = {}
    for s in _load(raw_dir, "tcgdex/en-sets.json", "sets"):
        ptcd_id = ptcd_by_name.get(normalize_name(s["name"]))
        if ptcd_id:
            result[s["id"]] = ptcd_id
    result.update(TCGDEX_TO_PTCD_OVERRIDES)
    return result


def load_ptcd_dex_index(raw_dir: Path) -> dict[str, list[int]]:
    """TCGdex EN card id → nationalPokedexNumbers（经 ptcd 卡数据 + 编号归一）。"""
    tcg2ptcd = load_tcgdex_to_ptcd(raw_dir)
    ptcd2tcg = {v: k for k, v in tcg2ptcd.items()}
    index: dict[str, list[int]] = {}
    cards_dir = raw_dir / "pokemon-tcg-data" / "cards-en"
    if not cards_dir.exists():
        return index
    for path in sorted(cards_dir.glob("*.json")):
        ptcd_set = path.stem
        tcgdex_set = ptcd2tcg.get(ptcd_set)
        if tcgdex_set is None:
            continue
        for card in _load(raw_dir, f"pokemon-tcg-data/cards-en/{path.name}", "cards"):
            dex_ids = card.get("nationalPokedexNumbers")
            if not dex_ids:
                continue
            key = _norm_number(str(card.get("number", "")))
            if key is not None:
                index[f"{tcgdex_set}-{key[0]}{key[1]}"] = list(dex_ids)
    return index


def _dex_key(tcgdex_id: str) -> str | None:
    """TCGdex card id（sv02-45 / sm3-TG02 / swshp-SWSH017）→ 索引键。"""
    set_id, _, local_id = tcgdex_id.rpartition("-")
    key = _norm_number(local_id)
    if key is None:
        return None
    return f"{set_id}-{key[0]}{key[1]}"


def build_ja_name(
    en_name: str,
    dex_ids: list[int],
    rules: JaRules,
    ja_species: dict[int, str],
    en_species: dict[int, str],
    species_by_en: dict[str, int] | None = None,
) -> str | None:
    """EN 卡名 + dexIds → JA 卡名；词表/物种表覆盖不了返回 None（不猜）。

    组成：尾缀剥除（GX/V/ex/◇…）→ " & " 拆成分（TAG TEAM）→ 每成分剥前置修饰
    （→JA 后置：Bloodmoon/面具）、前缀（アローラ /かがやく…）+ 归属
    （"{X}'s" → "{JA}の"）+ 变体字母（X/Y）→
    核心必须在 dexIds 池中找到归一相等的 EN 物种名（校验锚，不消耗池——
    ptcd 同物种 TAG TEAM 只列一次 dexId）。
    dexIds 为空（ptcd 缺 nationalPokedexNumbers 的数据缺口）时，单成分可用
    species_by_en 反查兜底（同样是名字级校验，不猜）。
    """
    name = en_name.replace("​", "").strip()
    if name in rules.basic_energies:
        return rules.basic_energies[name]
    suffix_ja = ""
    for en_suf, ja_suf in rules.suffixes:
        if name.endswith(en_suf):
            suffix_ja = ja_suf
            name = name[: -len(en_suf)]
            break
    components = [c.strip() for c in name.split(" & ")]
    if not dex_ids and len(components) > 1:
        return None
    parts: list[str] = []
    for comp in components:
        # EN 前置修饰 → JA 后置（"Bloodmoon Ursaluna" → "ガチグマ アカツキ"，
        # 官方「种名 + 半角空格 + 修饰」，オーガポン面具同规则）
        post_ja = ""
        for en_mod, ja_mod in rules.suffix_modifiers:
            if comp.startswith(en_mod + " "):
                post_ja = " " + ja_mod
                comp = comp[len(en_mod) + 1:]
                break
        prefixes_ja = ""
        matched = True
        while matched:
            matched = False
            for en_pre, ja_pre in rules.prefixes:
                if comp.startswith(en_pre + " "):
                    prefixes_ja += ja_pre
                    comp = comp[len(en_pre) + 1:]
                    matched = True
                    break
        owner = re.match(r"^([A-Za-z][A-Za-z. ]*?)'s\s+", comp)
        if owner:
            ja_owner = rules.owners.get(owner.group(1))
            if ja_owner is None:
                return None  # 词表外归属 → 不猜
            prefixes_ja += ja_owner + "の"
            comp = comp[owner.end():]
        variant = ""
        core = comp
        m = re.fullmatch(r"(.+) ([A-Za-z])", comp)
        if m and m.group(2) in rules.variant_letters:
            core, variant = m.group(1), m.group(2)
        # 组份池匹配：dexIds 顺序不一定与卡名成分一致（ptcd 实测，
        # 如 "Mega Lopunny & Jigglypuff-GX" 的 nationalPokedexNumbers=[39, 428]）——
        # 每个成分在池中找物种名归一相等的 dexId（校验锚，不猜）。
        hit = next(
            (
                d
                for d in dex_ids
                if d in ja_species
                and d in en_species
                and normalize_name(en_species[d]) == normalize_name(core)
            ),
            None,
        )
        if hit is None and not dex_ids and species_by_en is not None:
            # ptcd dexId 数据缺口兜底：核心名反查物种表（名字级校验同源）
            dex = species_by_en.get(normalize_name(core))
            if dex is not None and dex in ja_species:
                hit = dex
        if hit is None:
            return None
        parts.append(prefixes_ja + ja_species[hit] + variant + post_ja)
    return rules.tag_team_joiner.join(parts) + suffix_ja


def fetch_ja_raw(raw_dir: Path) -> list[str]:
    """ptcd 卡数据（已映射套）+ PokéAPI 物种名表入 raw 层（低频静态，append-only）。"""
    import httpx

    from ptcgdb.mapping.tcgdex import load_subset_map

    needed = set(load_set_map(raw_dir).values()) | set(load_subset_map(raw_dir).values())
    tcg2ptcd = load_tcgdex_to_ptcd(raw_dir)
    targets = sorted({tcg2ptcd[t] for t in needed if t in tcg2ptcd})
    written: list[str] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for ptcd_set in targets:
            rel = f"pokemon-tcg-data/cards-en/{ptcd_set}.json"
            if (raw_dir / rel).exists():
                continue
            resp = client.get(PTCD_CARDS_URL.format(ptcd_set))
            resp.raise_for_status()
            if write_raw(raw_dir / rel, {"cards": resp.json()}, source="pokemon_tcg_data"):
                written.append(rel)
            time.sleep(0.3)
        rel = "pokeapi/pokemon-species-names.json"
        if not (raw_dir / rel).exists():
            resp = client.get(SPECIES_CSV_URL)
            resp.raise_for_status()
            if write_raw(raw_dir / rel, {"csv": resp.text}, source="pokeapi"):
                written.append(rel)
    return written


@dataclass
class JaFillResult:
    external_ids_written: int = 0
    name_ja_filled: int = 0
    conflicts: list[str] = field(default_factory=list)  # 已有 name_ja 与新值冲突
    questions: dict[str, list[str]] = field(default_factory=dict)


def fill_ja(
    db_path: Path, raw_dir: Path, rules_path: Path = DEFAULT_RULES_PATH
) -> JaFillResult:
    """填充 name_ja + external_ids(system='tcgdex')；未覆盖全量入 question 清单。"""
    rules = load_ja_rules(rules_path)
    ja_species = load_ja_species(raw_dir)
    en_species = load_en_species(raw_dir)
    dex_index = load_ptcd_dex_index(raw_dir)
    species_by_en = {normalize_name(n): d for d, n in en_species.items()}
    resolve = resolve_en(db_path, raw_dir)

    result = JaFillResult()
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for card_id, tcgdex_id in resolve.tcgdex_ids.items():
            session.merge(
                ExternalId(card_id=card_id, system="tcgdex", external_id=tcgdex_id)
            )
            result.external_ids_written += 1
        # 无 TCGdex id 的卡也要分类（能量可仅凭名字填）
        all_bridge = session.execute(
            select(Card.card_id, Card.name_en, Card.card_type, Card.name_ja)
            .join(ExternalId, Card.card_id == ExternalId.card_id)
            .where(ExternalId.system == "mik_en")
        ).all()

        def ask(category: str, card_id: str) -> None:
            result.questions.setdefault(category, []).append(card_id)

        for card_id, name_en, card_type, existing_ja in all_bridge:
            if card_type == "trainer":
                ask("trainer", card_id)
                continue
            tcgdex_id = resolve.tcgdex_ids.get(card_id)
            dex_ids: list[int] = []
            if tcgdex_id is not None:
                key = _dex_key(tcgdex_id)
                dex_ids = dex_index.get(key, []) if key else []
            if card_type == "pokemon" and tcgdex_id is None:
                ask("no_set_map", card_id)
                continue
            built = build_ja_name(
                name_en or "", dex_ids, rules, ja_species, en_species, species_by_en
            )
            if built is None:
                if card_type != "pokemon":
                    ask("energy_special", card_id)
                elif not dex_ids:
                    ask("no_dex", card_id)
                else:
                    ask("name_unmatched", card_id)
                continue
            card = session.get(Card, card_id)
            if existing_ja and existing_ja != built:
                result.conflicts.append(card_id)
                continue
            card.name_ja = built
            result.name_ja_filled += 1
        session.commit()
    engine.dispose()
    for category in result.questions:
        result.questions[category].sort()
    return result

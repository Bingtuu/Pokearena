"""字段形态调查（一次性脚本，task 004）：扫描 raw 单卡文件统计 distinct 取值分布。

用法：.venv/Scripts/python.exe tools/survey_fields.py data/raw/mikmoe/CSM1aC
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

set_dir = Path(sys.argv[1])

mechanic = Counter()
label = Counter()
is_values = Counter()
card_type = Counter()
stage = Counter()
energy_type = Counter()
cost_atoms = Counter()
cost_strings = Counter()
damage_forms = Counter()
weakness_values = Counter()
resistance_values = Counter()
weakness_energy = Counter()
resistance_energy = Counter()
rarity = Counter()
reg_mark = Counter()
yoren_by_type = Counter()
trainer_names = Counter()
energy_names = Counter()
evolves_from_samples = Counter()
hp_forms = Counter()
retreat_forms = Counter()
ability_names = Counter()
mystery_keys = Counter()
damage_mult_samples = []
name_forms = Counter()

files = sorted(p for p in set_dir.glob("*.json") if p.name != "cards.json")
for p in files:
    doc = json.loads(p.read_text(encoding="utf-8"))
    d = doc["data"]
    mechanic[repr(d.get("mechanic"))] += 1
    label[repr(d.get("label"))] += 1
    card_type[d.get("cardType")] += 1
    rarity[d.get("rarity")] += 1
    reg_mark[d.get("regulationMark")] += 1
    name = d.get("name", "")
    name_forms[repr(name[-3:]) if len(name) >= 3 else repr(name)] += 1
    pa = d.get("pokemonAttr") or {}
    if pa:
        stage[repr(pa.get("stage"))] += 1
        energy_type[repr(pa.get("energyType"))] += 1
        hp_forms[repr(pa.get("hp"))] += 1
        retreat_forms[repr(pa.get("retreatCost"))] += 1
        ef = pa.get("evolvesFrom") or ""
        if ef:
            evolves_from_samples[f"{name} <- {ef}"] += 1
        for a in pa.get("ability") or []:
            ability_names[a.get("name")] += 1
            for k in a:
                mystery_keys[f"ability.{k}"] += 1
        w = pa.get("weakness")
        if w:
            weakness_energy[w.get("energy")] += 1
            weakness_values[w.get("value")] += 1
        r = pa.get("resistance")
        if r:
            resistance_energy[r.get("energy")] += 1
            resistance_values[r.get("value")] += 1
        for atk in pa.get("attack") or []:
            for k in atk:
                mystery_keys[f"attack.{k}"] += 1
            cs = atk.get("cost") or ""
            cost_strings[cs] += 1
            for ch in cs:
                cost_atoms[ch] += 1
            dmg = atk.get("damage") or ""
            m = re.fullmatch(r"(\d*)([+\-×xX]?)", dmg)
            form = f"{'digits' if m and m.group(1) else 'empty'}+{(m.group(2) if m else '?')!r}"
            if not m:
                form = f"UNPARSED:{dmg!r}"
            damage_forms[form] += 1
            if m and m.group(2) in ("×", "x", "X"):
                damage_mult_samples.append((p.name, atk["name"], dmg))
        for k in pa:
            mystery_keys[f"pokemonAttr.{k}"] += 1
    else:
        yoren_by_type[d.get("cardType")] += 1
        if d.get("cardType") == "Trainer":
            trainer_names[name] += 1
        if d.get("cardType") == "Energy":
            energy_names[name] += 1
    # cards.json 同级的 is[] 在单卡里也可能出现
    for v in d.get("is") or []:
        is_values[v] += 1
    for k in d:
        mystery_keys[f"data.{k}"] += 1


def dump(title: str, c: Counter) -> None:
    print(f"\n== {title} ==")
    for k, v in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"  {v:4d}  {k}")


print(f"files={len(files)}")
dump("mechanic", mechanic)
dump("label", label)
dump("is[] (card-detail)", is_values)
dump("cardType", card_type)
dump("pokemonAttr.stage", stage)
dump("pokemonAttr.energyType", energy_type)
dump("attack.cost distinct strings", cost_strings)
dump("attack.cost atoms", cost_atoms)
dump("attack.damage forms", damage_forms)
print("damage × samples:", damage_mult_samples)
dump("weakness.energy", weakness_energy)
dump("weakness.value", weakness_values)
dump("resistance.energy", resistance_energy)
dump("resistance.value", resistance_values)
dump("rarity", rarity)
dump("regulationMark", reg_mark)
dump("pokemonAttr.hp", hp_forms)
dump("pokemonAttr.retreatCost", retreat_forms)
dump("evolvesFrom samples", evolves_from_samples)
dump("ability names", ability_names)
dump("Trainer names", trainer_names)
dump("Energy names", energy_names)
dump("field keys", mystery_keys)
dump("name suffix (last 3 chars)", name_forms)

# cards.json 里 is[] 的分布（product-detail 层）
cards_doc = json.loads((set_dir / "cards.json").read_text(encoding="utf-8"))
is_cd = Counter()
for c in cards_doc["data"]["cards"]:
    for v in c.get("is") or []:
        is_cd[v] += 1
dump("is[] (product-detail cards.json)", is_cd)

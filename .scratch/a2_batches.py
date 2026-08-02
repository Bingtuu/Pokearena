# A2 抽样比对批次生成器：从 reports/sampling-a2-20260801.md 抽 card_id，
# 按批输出库内字段值（供与小程序卡面人工比对）。
# 用法: python .scratch/a2_batches.py <batch_no>   # 每批 10 张
import json
import re
import sqlite3
import sys

REPORT = "reports/sampling-a2-20260801.md"
DB = "data/ptcg-cn.db"
BATCH = 10

ids = re.findall(r"^### (\S+) ", open(REPORT, encoding="utf-8").read(), re.M)
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

b = int(sys.argv[1]) if len(sys.argv) > 1 else 1
chunk = ids[(b - 1) * BATCH : b * BATCH]
print(f"# A2 第 {b} 批（{len(chunk)} 张 / 共 {len(ids)} 张）\n")
for i, cid in enumerate(chunk, (b - 1) * BATCH + 1):
    r = con.execute("SELECT * FROM cards WHERE card_id=? AND status='active'", (cid,)).fetchone()
    if not r:
        print(f"## {i}. {cid} —— 库内未找到！\n")
        continue
    head = f"## {i}. {cid} {r['name_full']}"
    meta = f"系列/卡号: `{r['set_id']}` `{r['number_display']}` | 赛制 {r['regulation_mark']} | 罕贵 {r['rarity']}"
    print(head + "\n" + meta)
    if r["card_type"] == "pokemon":
        types = "·".join(json.loads(r["types"] or "[]") or [])
        line = f"HP {r['hp']} / {types}"
        if r["stage"]:
            line += f" | 阶段 {r['stage']}"
        if r["evolves_from_text"]:
            line += f" | 进化自: {r['evolves_from_text']}"
        print(line)
        ab = json.loads(r["abilities"] or "[]") or []
        for a in ab:
            print(f"特性: {a.get('name')} — {a.get('text','')}")
        for atk in json.loads(r["attacks"] or "[]") or []:
            cost = "".join(c.get("type", "?") * (c.get("count") or 1) for c in atk.get("cost") or [])
            cm = atk.get("cost_modifier") or ""
            dmg = str(atk.get("damage_base") or "") + (atk.get("damage_modifier") or "")
            print(f"招式: [{cost}{cm}] {atk.get('name')} {dmg} — {(atk.get('effect_text') or '')[:80]}")
        wk = json.loads(r["weakness"]) if r["weakness"] else None
        w = f"{wk['type']}{wk['value']}" if wk else "无"
        rs = json.loads(r["resistance"]) if r["resistance"] else None
        res = f"{rs['type']}{rs['value']}" if rs else "无"
        print(f"弱点 {w} | 抵抗 {res} | 撤退 {r['retreat_cost']}")
    else:
        print(f"类型: {r['card_type']} / {r['trainer_subtype'] or '-'}")
    tr = (r["text_raw"] or "").replace("\n", "⏎")
    print(f"text_raw: {tr}")
    print()

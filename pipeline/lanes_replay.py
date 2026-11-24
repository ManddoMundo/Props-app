"""Lab, v3.52 (research only). Two checks on proposals that were NOT made in v3.52.
A) Leans: every midday side that passes the lean test (cmd_fill's rules) with an edge of 1 to 3 points, graded from the audit,
   next to the sides that clear the full 3 point bar. The question: do leans earn a place on the live record.
B) Confident lane, alternate lines: where at least conf_books other books quote the same alternate rung with both prices,
   is the books' own de-vigged chance on that rung a better guide than the desk's curve carried out from the main line.
Run: python3 lanes_replay.py"""
import glob, json, re, sys
sys.path.insert(0, "/home/claude/props/src")
import numpy as np
import daily as D
from daily import CFG, MK, ALTK, dec, probs, power_fair, parse, norm, eligible

O = D.O; DATA, _ = D.load(); A = json.load(open(O + "audit.json"))
def rec(z):
    if not z: return "none"
    w = sum(r["win"] for r in z); u = sum((dec(r["odds"]) - 1) if r["win"] else -1 for r in z)
    return f"{w}-{len(z) - w}  hit {w / len(z):.1%}  said {np.mean([r['p'] for r in z]):.1%}  needs {np.mean([1 / dec(r['odds']) for r in z]):.1%}  per bet {u / len(z):+.1%}"

print("A) leans against full plays, every midday side since the market check began (flat one unit):")
lean, full = [], []
for f in sorted(glob.glob(O + "priced/*.json")):
    if not re.search(r"/(NBA|NFL)_\d{4}-\d\d-\d\d\.json$", f): continue
    for b in json.load(open(f)):
        a = A.get(b["id"] + "|" + b["side"])
        if not a or not b.get("ver"): continue
        try:
            soft = dict(b, edge=max(b["edge"], CFG["min_edge"]), adj=max(b["adj"], CFG["min_adj_ev"]))
            r = dict(win=a["win"], odds=b["odds"], p=b["p"], mkt=b["mkt"], date=b["date"])
            if eligible(b): full.append(r)
            elif eligible(soft) and CFG["lean_edge"] <= b["edge"] < CFG["min_edge"] and b["adj"] > 0: lean.append(r)
        except (KeyError, TypeError): pass
print("  full plays (edge 3 to 12):", rec(full)); print("  leans (edge 1 to 3):      ", rec(lean))
for m in sorted({r["mkt"] for r in lean}): print(f"    leans, {m}: {rec([r for r in lean if r['mkt'] == m])}")
print(f"  days: {len({r['date'] for r in lean})}; leans a day {len(lean) / max(len({r['date'] for r in lean}), 1):.1f}")

print("\nB) confident lane on alternate rungs (quotes inside the lane's price band, -500 to -140):")
ll = lambda p, y: -(y * np.log(np.clip(p, 1e-4, 1 - 1e-4)) + (1 - y) * np.log(1 - np.clip(p, 1e-4, 1 - 1e-4)))
rows = []
for f in sorted(glob.glob(O + "lines/*.txt")):
    m = re.search(r"/(NBA|NFL)_(\d{4}-\d\d-\d\d)\.txt$", f)
    if not m: continue
    lg, date = m.groups(); L = DATA[lg]
    try: pr = json.load(open(O + f"priced/{lg}_{date}.json"))
    except FileNotFoundError: continue
    base = {}
    for x in pr: base.setdefault((norm(x["name"]), x["mkt"]), x)
    allr = parse(f); rung = {}
    for r in allr:
        mkt = ALTK[lg].get(r["market"]) or MK[lg].get(r["market"])
        if not mkt or mkt == "any_td" or None in (r["line"], r["o"], r["u"]) or not (CFG["sane"][0] <= 1 / dec(r["o"]) + 1 / dec(r["u"]) <= CFG["sane"][1]): continue
        a, b = 1 / dec(r["o"]), 1 / dec(r["u"])
        rung.setdefault((norm(r["player"]), mkt, r["line"]), {})[r["book"]] = (power_fair(r["o"], r["u"]), a / (a + b))
    for r in allr:
        if r["market"] not in ALTK[lg] or r["book"] not in CFG["bet_books"] or r["line"] is None: continue
        mkt = ALTK[lg][r["market"]]; x = base.get((norm(r["player"]), mkt))
        if x is None or x.get("mm") is None or mkt not in L["model"]["disp"]: continue
        res = (A.get(x["id"] + "|Over") or A.get(x["id"] + "|Under") or {}).get("result")
        if res is None or res == r["line"]: continue
        oth = [v for bk, v in rung.get((norm(r["player"]), mkt, r["line"]), {}).items() if bk != r["book"]]
        for side, odds in (("Over", r["o"]), ("Under", r["u"])):
            if odds is None or not (CFG["conf_min_odds"] <= odds <= CFG["conf_max_odds"]): continue
            ov, un, _ = probs(L, lg, mkt, x["mm"], r["line"]); ch = (ov if side == "Over" else un) / (ov + un)
            curve = min(ch * ((1 - CFG["conf_exit"]) if side == "Over" else 1.0), CFG["conf_cap"])
            e = dict(win=int((res > r["line"]) == (side == "Over")), odds=int(odds), curve=curve, n_oth=len(oth), side=side, key=(x["id"], r["line"], side), book=r["book"])
            if len(oth) >= CFG["conf_books"]:
                pw, pl = np.median([v[0] for v in oth]), np.median([v[1] for v in oth])
                e.update(d_pow=min(pw if side == "Over" else 1 - pw, CFG["conf_cap"]), d_plain=min(pl if side == "Over" else 1 - pl, CFG["conf_cap"]))
            rows.append(e)
both = [r for r in rows if "d_pow" in r]
print(f"  in-band alternate quotes with a result: {len(rows)}; of those, {len(both)} have {CFG['conf_books']}+ other books on the same rung with both prices ({len({r['key'] for r in both})} distinct rungs)")
if both:
    y = np.array([r["win"] for r in both])
    for k, lab in (("curve", "desk curve from the main line (live)"), ("d_pow", "same rung, power de-vig (proposed)"), ("d_plain", "same rung, plain de-vig")):
        p = np.array([r[k] for r in both]); print(f"    {lab:<40} said {p.mean():.1%}  happened {y.mean():.1%}  log loss {ll(p, y).mean():.4f}")
    for k, lab in (("curve", "live"), ("d_pow", "proposed")):
        z = [dict(win=r["win"], odds=r["odds"], p=r[k]) for r in both if r[k] >= CFG["conf_fair"] and r[k] - 1 / dec(r["odds"]) >= CFG["conf_edge"]]
        print(f"    would pass the lane's chance and price tests, {lab}: {rec(z)}")

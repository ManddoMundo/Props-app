"""Lab (research only; the desk is not changed). How much should the desk lean on the model?
A) Every graded prop with a market check: log loss of the over at the posted line, mean = market + w x (centred model - market),
   for fixed weights and for the live calibration (weights learned only from earlier days), against the market alone.
B) The pick rules replayed on the days with saved lines, live weights against a fixed weight in every market.
Run: python3 weight_replay.py"""
import json, sys, tempfile, glob, re, os
sys.path.insert(0, "/home/claude/props/src")
import numpy as np
import daily as LIVE
from daily import probs, centre, CFG, dec

OUT = LIVE.O; DATA = json.load(open(OUT + "data.json")); A = json.load(open(OUT + "audit.json"))
ok = {k: r for k, r in A.items() if r["side"] == "Over" and r.get("ver") and r.get("nb", 0) >= 2 and r.get("mm") is not None and r["mkt"] in DATA[r["lg"]]["model"]["disp"]}
days = sorted({r["date"] for r in ok.values()}); tmp = tempfile.mkdtemp() + "/"
def weights(upto):
    json.dump({k: r for k, r in A.items() if r["date"] < upto}, open(tmp + "audit.json", "w")); LIVE.O = tmp; LIVE._CAL.clear()
    w = {k: v.get("w_fit", v["w"]) for k, v in LIVE.calib(DATA).items()}      # w_fit: the weight a paused league would carry; LIVE.O = OUT; LIVE._CAL.clear(); return w
FIX = (0.05, 0.10, 0.15, 0.25, 0.35); M = [f"w{int(x * 100):02d}" for x in FIX] + ["live"]; rows = []
for d in days[1:]:
    W = weights(d); today = [(k, r) for k, r in ok.items() if r["date"] == d]
    for key in {(r["lg"], r["mkt"]) for _, r in today}:
        z = [(k, r) for k, r in today if (r["lg"], r["mkt"]) == key]; c = centre([(r["mu"], r["mm"]) for _, r in z]); L = DATA[key[0]]
        for k, r in z:
            e = dict(lg=key[0], mkt=key[1], date=d, cl="|".join(k.split("|")[:3]))
            for m, w in list(zip(M, FIX)) + [("market", 0.0), ("live", W.get(key[0] + "|" + key[1], 0.25))]:
                ov, un, _ = probs(L, key[0], key[1], r["mm"] + w * (c * r["mu"] - r["mm"]), r["line"]); p = min(max(ov / (ov + un), 1e-4), 1 - 1e-4)
                e[m] = -(r["win"] * np.log(p) + (1 - r["win"]) * np.log(1 - p))
            rows.append(e)
rng = np.random.default_rng(7)
def show(label, z):
    if len(z) < 60: return
    base = np.array([r["market"] for r in z]); cl = np.array([r["cl"] for r in z]); u, inv = np.unique(cl, return_inverse=True)
    s = f"  {label:<16} n {len(z):5d} |"
    for m in M:
        v = np.array([r[m] for r in z]) - base; tot = np.bincount(inv, v, len(u)); cnt = np.bincount(inv, minlength=len(u))
        j = rng.integers(0, len(u), (800, len(u))); bs = tot[j].sum(1) / cnt[j].sum(1)
        s += f" {m} {v.mean() * 1000:+.2f} ({np.mean(bs < 0):.0%})"
    print(s)
print("A) log loss against the market alone, x1000 (negative = beats the market; in brackets, share of player-day resamples where it does)")
print("   days:", days[1], "to", days[-1], f"({len(days) - 1} days)")
show("all", rows)
for lg in ("NBA", "NFL"): show(lg, [r for r in rows if r["lg"] == lg])
show("NBA pts reb ast", [r for r in rows if r["lg"] == "NBA" and r["mkt"] in ("pts", "reb", "ast")])
for k in ("ast", "pts", "reb"): show("NBA " + k, [r for r in rows if r["lg"] == "NBA" and r["mkt"] == k])
show("NFL pick mkts", [r for r in rows if r["lg"] == "NFL" and r["mkt"] in CFG["pick_markets"]["NFL"]])
show("through 11-23", [r for r in rows if r["date"] <= "2026-11-23"])
show("11-24 (new day)", [r for r in rows if r["date"] == "2026-11-24"])
for d in days[1:]: show(d, [r for r in rows if r["date"] == d])

print("\nB) the pick rules on the days with saved lines (plain de-vig, median of all books, as live):")
import policy_replay as PR
def rec(z):
    z = [b for b in z if b["win"] is not None]
    if not z: return "0-0"
    w = sum(b["win"] for b in z); u = sum((dec(b["odds"]) - 1) if b["win"] else -1 for b in z); return f"{w}-{len(z) - w} ({u:+.2f}u)"
files = [re.search(r"/(NBA|NFL)_(\d{4}-\d\d-\d\d)\.txt$", f) for f in sorted(glob.glob(OUT + "lines/*.txt"))]
files = [m.groups() for m in files if m and os.path.exists(OUT + f"priced/{m.group(1)}_{m.group(2)}.json")]
for lab, wf in (("live weights", None), ("w = 0.25", 0.25), ("w = 0.15", 0.15), ("w = 0.10", 0.10), ("w = 0.05", 0.05)):
    PR.W_FIXED = wf; pool, picks, nd = [], [], 0
    for lg, date in files:
        r = PR.day(lg, date)
        if r is None: continue
        nd += 1; a, b = PR.pick([x for row in r[0] for x in row["best"]["live"].values()]); pool += a; picks += b
    hr = [b for b in pool if b["book"] == CFG["book"]]
    print(f"  {lab:<13} days {nd}  cleared {len(pool):3d} {rec(pool):<17} picked {len(picks):3d} {rec(picks):<16} cleared at Hard Rock {len(hr):2d} {rec(hr):<14} by market {dict((m, sum(b['mkt'] == m for b in pool)) for m in sorted({b['mkt'] for b in pool}))}")

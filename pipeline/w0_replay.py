"""Lab (research only). Should a market's weight on the model start from 0 instead of 0.25?
Walk-forward: weights learned only from earlier days, scored on each day's graded props (log loss of the over at the line
against the books alone, x1000; negative = the blend beats the books). NBA only: the NFL is paused in v3.54.
Run: python3 w0_replay.py"""
import json, sys, tempfile
sys.path.insert(0, "/home/claude/props/src")
import numpy as np
import daily as LIVE
from daily import probs, centre, CFG
OUT = LIVE.O; DATA = json.load(open(OUT + "data.json")); A = json.load(open(OUT + "audit.json"))
ok = {k: r for k, r in A.items() if r["lg"] == "NBA" and r["side"] == "Over" and r.get("ver") and r.get("nb", 0) >= 2 and r.get("mm") is not None and r["mkt"] in DATA["NBA"]["model"]["disp"]}
days = sorted({r["date"] for r in ok.values()}); tmp = tempfile.mkdtemp() + "/"
def weights(upto, **cfg):
    json.dump({k: r for k, r in A.items() if r["date"] < upto}, open(tmp + "audit.json", "w"))
    old = {k: LIVE.CFG[k] for k in cfg}; LIVE.CFG.update(cfg); LIVE.O = tmp; LIVE._CAL.clear()
    w = {k: v.get("w_fit", v["w"]) for k, v in LIVE.calib(DATA).items()}; LIVE.CFG.update(old); LIVE.O = OUT; LIVE._CAL.clear(); return w
V = {"live (start 0.25)": dict(), "start 0": dict(cal_w0=0.0), "start 0, prior 300": dict(cal_w0=0.0, cal_w_n0=300), "start 0.10": dict(cal_w0=0.10)}
rows = []; log = {}
for d in days[1:]:
    W = {v: weights(d, **c) for v, c in V.items()}; log[d] = W
    today = [(k, r) for k, r in ok.items() if r["date"] == d]
    for mkt in {r["mkt"] for _, r in today}:
        z = [(k, r) for k, r in today if r["mkt"] == mkt]; c = centre([(r["mu"], r["mm"]) for _, r in z]); L = DATA["NBA"]
        for k, r in z:
            e = dict(mkt=mkt, date=d, cl="|".join(k.split("|")[:3]))
            for v, w in [(v, W[v].get("NBA|" + mkt, 0.25)) for v in V] + [("market", 0.0)]:
                ov, un, _ = probs(L, "NBA", mkt, r["mm"] + w * (c * r["mu"] - r["mm"]), r["line"]); p = min(max(ov / (ov + un), 1e-4), 1 - 1e-4)
                e[v] = -(r["win"] * np.log(p) + (1 - r["win"]) * np.log(1 - p))
            rows.append(e)
rng = np.random.default_rng(7)
def show(label, z):
    if len(z) < 60: return
    cl = np.array([r["cl"] for r in z]); u, inv = np.unique(cl, return_inverse=True); cnt = np.bincount(inv, minlength=len(u)); j = rng.integers(0, len(u), (800, len(u)))
    live = np.array([r["live (start 0.25)"] for r in z]); s = f"  {label:<16} n {len(z):5d} |"
    for v in V:
        x = np.array([r[v] for r in z]); a = x - np.array([r["market"] for r in z]); s += f" {v}: {a.mean() * 1000:+.2f}"
        if v != "live (start 0.25)":
            dv = x - live; bs = np.bincount(inv, dv, len(u))[j].sum(1) / cnt[j].sum(1); s += f" (beats live {np.mean(bs < 0):.0%})"
    print(s)
print("NBA, against the books alone (x1000), days", days[1], "to", days[-1])
show("all NBA", rows); show("pts reb ast", [r for r in rows if r["mkt"] in ("pts", "reb", "ast")])
for k in ("ast", "pts", "reb", "fg3", "pra", "pr", "pa", "ra"): show(k, [r for r in rows if r["mkt"] == k])
show("11-24 (newest)", [r for r in rows if r["date"] == days[-1]])
W = {v: weights("9999", **c) for v, c in V.items()}
print("\nweights the desk would carry tomorrow:")
for k in ("ast", "pts", "reb", "fg3", "pra", "pr", "pa", "ra"): print(f"  {k:<4}", "  ".join(f"{v}: {W[v]['NBA|' + k]:.2f}" for v in V))

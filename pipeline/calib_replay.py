"""Lab, v3.52 (research only). Walk-forward test of how the weight on the model is learned.
For each graded day the weight is fitted only on earlier days, then that day's props are scored: log loss of the over at
the posted line (lower is better), using mean = market + w x (centred model - market).
  market    w = 0 (the other books alone)
  fixed25   w = 0.25 in every market
  live      v3.51 calib(): least squares on the result, prior worth 150 lines, cap 0.70
  cap45     the same with the v3.52 cap of 0.45
  n600      the same with a prior worth 600 lines
  package   the proposed calib(): log loss at the line, market-checked rows only, prior 250, cap 0.45
Run: python3 calib_replay.py"""
import importlib.util, json, os, sys, tempfile
sys.path.insert(0, "/home/claude/props/src")
import numpy as np
import daily as LIVE
from daily import probs, centre, CFG

# the proposed calib() lives in the package's own daily.py, which was not adopted. Put that file at lab/package_daily.py
# to score it too; without it the "package" column is left out.
PKG = None
_pk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "package_daily.py")
if os.path.exists(_pk):
    spec = importlib.util.spec_from_file_location("pkg_daily", _pk); PKG = importlib.util.module_from_spec(spec); spec.loader.exec_module(PKG)
OUT = LIVE.O
DATA = json.load(open(OUT + "data.json")); A = json.load(open(OUT + "audit.json"))
ok = {k: r for k, r in A.items() if r["side"] == "Over" and r.get("ver") and r.get("nb", 0) >= 2 and r.get("mm") is not None and r["mkt"] in DATA[r["lg"]]["model"]["disp"]}
days = sorted({r["date"] for r in ok.values()})
tmp = tempfile.mkdtemp() + "/"


def weights(mod, upto, **cfg):
    json.dump({k: r for k, r in A.items() if r["date"] < upto}, open(tmp + "audit.json", "w"))
    old = {k: mod.CFG[k] for k in cfg}; mod.CFG.update(cfg); mod.O = tmp; mod._CAL.clear()
    w = {k: v["w"] for k, v in mod.calib(DATA).items()}; mod.CFG.update(old); mod.O = OUT; mod._CAL.clear()
    return w


M = ["market", "fixed25", "live", "cap45", "n600"] + (["package"] if PKG else []); rows = []; wlog = {}
for d in days[1:]:
    W = dict(market={}, fixed25={}, live=weights(LIVE, d, cal_w_max=0.7, cal_w_n0=150), cap45=weights(LIVE, d, cal_w_max=0.45, cal_w_n0=150),
             n600=weights(LIVE, d, cal_w_max=0.7, cal_w_n0=600))
    if PKG: W["package"] = weights(PKG, d)
    wlog[d] = {m: {k: W[m].get("NBA|" + k) for k in ("ast", "pts", "reb")} for m in M[2:]}
    today = [r for r in ok.values() if r["date"] == d]
    for key in {(r["lg"], r["mkt"]) for r in today}:
        z = [r for r in today if (r["lg"], r["mkt"]) == key]; c = centre([(r["mu"], r["mm"]) for r in z]); L = DATA[key[0]]
        for r in z:
            e = dict(lg=key[0], mkt=key[1], date=d, y=r["win"], pid=r.get("date") + str(r["mu"]) + str(r["line"]))
            for m in M:
                w = 0.0 if m == "market" else 0.25 if m == "fixed25" else W[m].get(key[0] + "|" + key[1], 0.25)
                ov, un, _ = probs(L, key[0], key[1], r["mm"] + w * (c * r["mu"] - r["mm"]), r["line"]); p = min(max(ov / (ov + un), 1e-4), 1 - 1e-4)
                e[m] = -(r["win"] * np.log(p) + (1 - r["win"]) * np.log(1 - p))
            rows.append(e)
print("weights the desk would have carried into each day (NBA assists / points / rebounds):")
for d in days[1:]:
    print(" ", d, " ".join(f"{m}: {wlog[d][m]['ast']:.2f}/{wlog[d][m]['pts']:.2f}/{wlog[d][m]['reb']:.2f}" for m in M[2:]))
rng = np.random.default_rng(7)
def show(label, z):
    if len(z) < 40: return
    base = np.array([r["market"] for r in z]); dd = np.array([r["date"] for r in z]); ud = np.unique(dd)
    s = f"  {label:<14} n {len(z):5d}  market {base.mean():.5f} |"
    for m in M[1:]:
        v = np.array([r[m] for r in z]) - base
        idx = rng.integers(0, len(z), (1000, len(z))); bs = v[idx].mean(1)
        s += f" {m} {v.mean():+.5f} ({np.mean(bs < 0):.0%})"
    print(s)
print("\nlog loss against the market alone (negative = the blend beats the market; in brackets, share of resamples where it does):")
show("all", rows)
for lg in ("NBA", "NFL"): show(lg, [r for r in rows if r["lg"] == lg])
for k in ("ast", "pts", "reb", "fg3", "pra", "pr", "pa", "ra"): show("NBA " + k, [r for r in rows if r["lg"] == "NBA" and r["mkt"] == k])
show("NBA pick mkts", [r for r in rows if r["lg"] == "NBA" and r["mkt"] in ("pts", "reb", "ast")])
for d in days[1:]: show(d, [r for r in rows if r["date"] == d])

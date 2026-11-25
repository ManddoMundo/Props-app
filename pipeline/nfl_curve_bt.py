"""Lab (research only; nfl.py and the desk are not changed). The NFL spread curve.
The desk turns a book line into an average through a negative binomial curve whose spread is fitted by maximum likelihood on
every player-game. For yardage that curve is far more lopsided than the players who actually get lines, so a fair line of 27
receiving yards is read as an average of 38 when those players average about 31.
  mle    the curve as nfl.py fits it now
  line   the same family, spread fitted so the curve prices over/under correctly at lines around the projection
Fitted on 2023-24, scored on 2025 and 2026 (model projections), then checked on the desk's own graded lines.
Run: python3 nfl_curve_bt.py"""
import json, sys
sys.path.insert(0, "/home/claude/props/src")
from collections import defaultdict
import numpy as np
from scipy import stats, optimize
import nfl, daily
from common import nb_k, fit_dispersion
from daily import implied_mean, probs, centre

OFF = np.array([-0.35, -0.2, -0.1, 0.0, 0.1, 0.2, 0.35])
def pover(mu, line, a, b):
    k = nb_k(mu, a, b); return 1 - stats.nbinom.cdf(np.floor(line), k, k / (k + mu))
def ll_lines(p, mu, y):
    tot = 0.0
    for o in OFF:
        line = np.floor(mu * (1 + o)) + 0.5; q = np.clip(pover(mu, line, p[0], p[1]), 1e-4, 1 - 1e-4); h = y > line
        tot += -(np.where(h, np.log(q), np.log(1 - q))).mean()
    return tot / len(OFF)
def fit_line(mu, y, start):
    best = None
    for s in (start, (0.5, 0.5), (1.5, 0.3)):
        r = optimize.minimize(ll_lines, list(s), args=(mu, y), method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-6, "maxiter": 600})
        if best is None or r.fun < best.fun: best = r
    return float(best.x[0]), float(best.x[1])

pw, g = nfl.load(); P = nfl.priors(pw); pr, tr, S, C = nfl.walk(pw, g, P)
warm = ~((pr.season == 2023) & (pr.week <= 4)); twarm = ~((tr.season == 2023) & (tr.week <= 4)); is_tr = warm & (pr.season <= 2024)
m = {"lg_ip": float(tr.ip.mean()), "beta": 0.8, "cal": defaultdict(lambda: 1.0), "team": nfl.fit_team(tr[twarm & (tr.season <= 2024)])}
d = nfl.project(pr[is_tr], tr, m, P)
cal = {k: float(d.loc[d[f] >= mn, col].sum() / d.loc[d[f] >= mn, "mu_" + k].sum()) for k, (col, f, mn) in nfl.STATS.items()}
mm_ = (d.mu_tgt >= 2.5) | (d.f_rush >= 4); cal["td"] = float((d.loc[mm_, "receiving_tds"] + d.loc[mm_, "rushing_tds"]).sum() / d.loc[mm_, "mu_td"].sum()); m["cal"] = cal
d = nfl.project(pr[is_tr], tr, m, P)
m["lin"] = {k: [float(v) for v in np.polyfit(d.loc[d[f] >= mn, "mu_" + k], d.loc[d[f] >= mn, col], 1)[::-1]] for k, (col, f, mn) in nfl.STATS.items()}
dtr = nfl.project(pr[is_tr], tr, m, P); dte = nfl.project(pr[pr.season >= 2025], tr, m, P)
DATA = json.load(open(daily.O + "data.json")); A = json.load(open(daily.O + "audit.json")); live = DATA["NFL"]["model"]["disp"]
rng = np.random.default_rng(7); NEW = {}
print("market      curve   a      b     | spread k at a typical projection | 2025: log loss at lines, over rate at the curve's own middle | 2026: same")
for k, typ in (("rec_yds", 35), ("rush_yds", 45), ("pass_yds", 230), ("rec", 3.5), ("rush_att", 12)):
    col, f, mn = nfl.STATS[k]; t = dtr[dtr[f] >= mn]; mu, y = t["mu_" + k].values.astype(float), np.round(t[col].values.astype(float)).clip(0)
    mle = fit_dispersion(mu, y); lin = fit_line(mu, y, mle); NEW[k] = lin
    for lab, p in (("live", tuple(live[k])), ("mle", mle), ("line", lin)):
        s = f"{k:<9} {lab:<5} {p[0]:+6.2f} {p[1]:5.2f} | k {float(nb_k(typ, *p)):6.2f} at {typ:<5}|"
        for se in (2025, 2026):
            e = dte[(dte[f] >= mn) & (dte.season == se)]; mu2, y2 = e["mu_" + k].values.astype(float), np.round(e[col].values.astype(float)).clip(0)
            kk = nb_k(mu2, *p); med = stats.nbinom.ppf(0.5, kk, kk / (kk + mu2))
            s += f" {ll_lines(p, mu2, y2):.4f}  over {np.mean(y2 > med):.1%} (n {len(e)}) |"
        print(s)
print("\nthe desk's own graded NFL lines (audit, with a market check): what the books' line is read as, under each curve")
L0 = DATA["NFL"]
for k in ("rec_yds", "rush_yds", "pass_yds", "rec"):
    z = [r for r in A.values() if r["lg"] == "NFL" and r["mkt"] == k and r["side"] == "Over" and r.get("mm") is not None and r.get("ver")]
    if len(z) < 20: continue
    y = np.array([r["result"] for r in z]); ln = np.array([r["line"] for r in z]); mu = np.array([r["mu"] for r in z]); mm0 = np.array([r["mm"] for r in z])
    L1 = {"model": {"disp": dict(live, **{k: list(NEW[k])})}}; mm1 = []
    for r in z:
        ov, un, _ = probs(L0, "NFL", k, r["mm"], r["line"]); mm1.append(implied_mean(L1, "NFL", k, r["line"], ov / (ov + un)))
    mm1 = np.array(mm1)
    for lab, mm in (("live", mm0), ("line", mm1)):
        cen = np.mean([centre([(a_, b_) for a_, b_ in zip(mu[[r["date"] == dd for r in z]], mm[[r["date"] == dd for r in z]])]) for dd in sorted({r["date"] for r in z})])
        print(f"  {k:<9} {lab:<5} n {len(z):4d}  line {ln.mean():6.1f}  read as {mm.mean():6.1f}  model {mu.mean():6.1f}  actual {y.mean():6.1f}  read-actual {mm.mean() - y.mean():+5.1f}  model pushed by x{cen:.3f}  corr(model-market, actual-market) {np.corrcoef(mu - mm, y - mm)[0, 1]:+.3f}")
json.dump({k: list(v) for k, v in NEW.items()}, open("nfl_curve_line.json", "w"))

# Research tool (v3.24 lineup test). Run from /home/claude/props/lab.
"""v3.24 starting-lineup adjustment (research). Charter, fixed before scoring: if a player starts today after coming off the
bench in his last game ('promoted'), or comes off the bench after starting his last game ('demoted'), scale his projected
minutes, and every stat with them, by a factor fitted on 2024-25 only (the ratio of actual to projected minutes in that case).
Kept starters and kept bench players are left alone. Scored once on 2025-26 and 2026-27 (to Nov 16): mean absolute error of
minutes, points, rebounds and assists, and the CRPS of the desk curve, against the unadjusted projection on the same rows."""
import sys; sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd, json
from scipy import stats
from common import nb_k
DISP = json.load(open("nba_mtr.json"))["disp"]
A = pd.read_parquet("nba_proj.parquet").sort_values(["pid", "gd", "game_id"])
A["last_st"] = A.groupby("pid").starter.shift(1); A = A[A.last_st.notna() & (A.mn > 0)].copy()
A["case"] = np.select([A.starter & ~A.last_st.astype(bool), ~A.starter & A.last_st.astype(bool)], ["promoted", "demoted"], "same")
tr = A[A.season == 2025]
F = {c: float(tr[tr.case == c].y_min.sum() / tr[tr.case == c].mn.sum()) for c in ("promoted", "demoted")}
print("factors fitted on 2024-25:", {k: round(v, 3) for k, v in F.items()})
def crps(mu, y, k):
    kk = nb_k(mu, *DISP[k]); pp = kk / (kk + mu); g = np.arange(0, int(max(y.max(), mu.max() * 4) + 30))
    Fc = stats.nbinom.cdf(g[None, :], kk[:, None], pp[:, None]); return ((Fc - (y[:, None] <= g)) ** 2).sum(1)
for s in (2026, 2027):
    T = A[A.season == s]; f = T.case.map(F).fillna(1.0).values
    out = {"rows": len(T), "changed": int((T.case != "same").sum())}
    for k in ("min", "pts", "reb", "ast"):
        y = T["y_min" if k == "min" else k].values.astype(float); mu = T["mn" if k == "min" else "mu_" + k].values
        out[k + " MAE"] = (round(np.abs(y - mu).mean(), 4), round(np.abs(y - mu * f).mean(), 4))
        if k != "min":
            ch = (T.case != "same").values
            c0, c1 = crps(mu[ch], y[ch], k), crps(mu[ch] * f[ch], y[ch], k)
            out[k + " CRPS on changed rows"] = (round(c0.mean(), 4), round(c1.mean(), 4), f"{(1 - c1.mean() / c0.mean()) * 100:+.1f}%")
    print(s, out)
json.dump(F, open("lineup_factors.json", "w"))

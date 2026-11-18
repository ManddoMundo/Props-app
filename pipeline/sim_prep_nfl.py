# Research tool for the weekly review (v3.20). Run from a scratch folder: mkdir -p /home/claude/props/lab && cd /home/claude/props/lab && python3 ../src/<this file>. Files it reads and writes land in that folder.
"""Research only: walk-forward NFL projections for every past player-game, model fitted on 2023-24 only (as nfl.py's backtest)."""
import sys; sys.path.insert(0, "/home/claude/props/src")
import io, contextlib, json
import numpy as np, pandas as pd
from collections import defaultdict
import nfl
from nfl import STATS, project, fit_team
from common import fit_dispersion
pw, g = nfl.load(); P = nfl.priors(pw)
pr, tr, S, C = nfl.walk(pw, g, P)
warm = ~((pr.season == 2023) & (pr.week <= 4)); twarm = ~((tr.season == 2023) & (tr.week <= 4))
is_tr = warm & (pr.season <= 2024)
M = {"lg_ip": float(tr.ip.mean()), "beta": 0.8, "cal": defaultdict(lambda: 1.0)}
def fit(mask_p, mask_t, beta=None):
    m = dict(M); m["cal"] = defaultdict(lambda: 1.0)
    if beta is not None: m["beta"] = beta
    m["team"] = fit_team(tr[mask_t]); d = project(pr[mask_p], tr, m, P); cal = {}
    for k, (col, fcol, mn) in STATS.items():
        mm = d[fcol] >= mn; cal[k] = float(d.loc[mm, col].sum() / d.loc[mm, "mu_" + k].sum())
    mm = (d.mu_tgt >= 2.5) | (d.f_rush >= 4)
    cal["td"] = float((d.loc[mm, "receiving_tds"] + d.loc[mm, "rushing_tds"]).sum() / d.loc[mm, "mu_td"].sum())
    m["cal"] = cal; d = project(pr[mask_p], tr, m, P); lin = {}
    for k, (col, fcol, mn) in STATS.items():
        mm = d[fcol] >= mn; lin[k] = [float(v) for v in np.polyfit(d.loc[mm, "mu_" + k], d.loc[mm, col], 1)[::-1]]
    m["lin"] = lin; return m
best = None
for beta in (0.0, 0.4, 0.6, 0.8, 1.0):
    m = fit(is_tr, twarm & (tr.season <= 2024), beta); d = project(pr[is_tr], tr, m, P)
    e = np.abs(d.loc[d.mu_tgt >= 2.5, "receiving_yards"] - d.loc[d.mu_tgt >= 2.5, "mu_rec_yds"]).mean() + np.abs(d.loc[d.f_rush >= 4, "rushing_yards"] - d.loc[d.f_rush >= 4, "mu_rush_yds"]).mean()
    if best is None or e < best[0]: best = (e, beta)
M["beta"] = best[1]
m_tr = fit(is_tr, twarm & (tr.season <= 2024))
d = project(pr[is_tr], tr, m_tr, P)
m_tr["disp"] = {k: fit_dispersion(d.loc[d[f] >= mn, "mu_" + k], d.loc[d[f] >= mn, c]) for k, (c, f, mn) in STATS.items()}
allp = project(pr[warm], tr, m_tr, P)
X = np.c_[np.ones(len(tr)), tr[nfl.TF].values]
tr = tr.assign(PA=X @ np.array(m_tr["team"]["pa"]), CAR=X @ np.array(m_tr["team"]["car"]))
gg = g[["game_id", "home_team", "away_team", "home_score", "away_score", "spread_line", "total_line", "gameday"]]
allp.to_parquet("nfl_proj.parquet"); tr.to_parquet("nfl_team.parquet"); gg.to_parquet("nfl_games.parquet")
json.dump({k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in m_tr.items()}, open("nfl_mtr.json", "w"))
print(allp.shape, allp.season.value_counts().to_dict(), "tpa", P["lg"]["tpa"], list(allp.columns)[:80])

# Research tool for the weekly review (v3.20). Run from a scratch folder: mkdir -p /home/claude/props/lab && cd /home/claude/props/lab && python3 ../src/<this file>. Files it reads and writes land in that folder.
"""Research only (not part of the daily pipeline): walk-forward NBA projections for every past player-game, with the
model fitted on 2024-25 only (m_tr, exactly as nba.py's backtest), saved for the simulator backtest."""
import sys; sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd, json
import nba
from nba import BASE, COMBO, project
from common import fit_dispersion
d = nba.load()
pr, tr, S = nba.walk(d)
first = pr[pr.season == 2025].gd.min()
warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
is_tr = warm & (pr.season == 2025)
M = {"bm": 0.8, "bs": {k: 0.5 for k in BASE}, "cal": {}}
best = None
for bm in (0.0, 0.5, 0.8, 1.0):
    M["bm"] = bm; dd = project(pr[is_tr], tr, M); e = np.abs(dd.y_min - dd.mn).mean()
    if best is None or e < best[0]: best = (e, bm)
M["bm"] = best[1]
for k in BASE:
    best = None
    for bs in (0.0, 0.25, 0.5, 0.75, 1.0):
        M["bs"][k] = bs; dd = project(pr[is_tr], tr, M); mm = dd.mn >= 15
        e = np.abs(dd.loc[mm, k] - dd.loc[mm, "mu_" + k]).mean()
        if best is None or e < best[0]: best = (e, bs)
    M["bs"][k] = best[1]
m = dict(bm=M["bm"], bs=dict(M["bs"]), cal={})
dd = project(pr[is_tr], tr, m); mm = dd.mn >= 15
m["cal"] = {k: float(dd.loc[mm, k].sum() / dd.loc[mm, "mu_" + k].sum()) for k in BASE}
dd = project(pr[is_tr], tr, m); mm = dd.mn >= 15
m["lin"] = {k: [float(v) for v in np.polyfit(dd.loc[mm, "mu_" + k], dd.loc[mm, k], 1)[::-1]] for k in BASE}
dd = project(pr[is_tr], tr, m); mm = dd.mn >= 15
m["disp"] = {k: fit_dispersion(dd.loc[mm, "mu_" + k], dd.loc[mm, k]) for k in BASE + list(COMBO)}
allp = project(pr[warm], tr, m)
ha = d[["game_id", "team", "home_away", "starter", "pid"]].copy()
ha["game_id"] = ha.game_id
allp = allp.merge(ha.drop_duplicates(["game_id", "pid"]), on=["game_id", "team", "pid"], how="left")
keep = ["game_id", "gd", "season", "team", "opp", "pid", "name", "home_away", "starter", "m", "mn", "y_min"] + BASE + ["mu_" + k for k in BASE]
allp[keep].to_parquet("nba_proj.parquet")
json.dump(m, open("nba_mtr.json", "w"))
print(allp.shape, allp.season.value_counts().to_dict(), m["disp"])

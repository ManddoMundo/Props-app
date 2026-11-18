# Research tool (v3.21 closing-line test). Run from /home/claude/props/lab with the decrypted history files in /home/claude/hist/txt (history.yml pulls them).
"""The simulator's over chance at Hard Rock's closing line, on the model's own projections, against the model alone and the books."""
import numpy as np, pandas as pd, close_bt as C
R = pd.read_pickle("close_scored.pkl"); R = R[R.p_mkt.notna()].copy(); R["p_sim"] = np.nan
import sim_bt as B
Gx = B.G
rng = np.random.default_rng(11)
nba = R[R.lg == "NBA"]
for gid, z in nba.groupby("game"):
    k = str(gid)
    if k not in B.byg: continue
    sides = B.sim_game(rng, k, 4000, "market")
    for x, box in sides:
        nm = x.name.map(C.norm).values
        for r in z.itertuples():
            i = np.where(nm == r.key)[0]
            if len(i) == 1: R.loc[r.Index, "p_sim"] = float((box[r.mkt][:, i[0]] > r.line).mean())
import sim_bt_nfl as F
nfl = R[R.lg == "NFL"]; MAP = {"pass_yds": "pass_yds", "rush_yds": "rush_yds", "rec_yds": "rec_yds", "rec": "rec"}
for gid, z in nfl.groupby("game"):
    g = F.games[F.games.game_id == gid]
    if g.empty or (gid, g.iloc[0].away_team) not in F.byt or (gid, g.iloc[0].home_team) not in F.byt: continue
    sides, _ = F.run(g.iloc[0], 4000, rng)
    for x, box in sides:
        nm = x.name.map(C.norm).values
        for r in z.itertuples():
            i = np.where(nm == r.key)[0]
            if len(i) == 1: R.loc[r.Index, "p_sim"] = float((box[MAP[r.mkt]][:, i[0]] > r.line).mean())
Z = R[R.p_sim.notna()]
ll = lambda p, y: float(-(y * np.log(np.clip(p, .001, .999)) + (1 - y) * np.log(1 - np.clip(p, .001, .999))).mean())
rows = [dict(lg=lg, mkt=m, n=len(z), hardrock=ll(z.p_hr, z.over), model=ll(z.p_mod, z.over), sim=ll(z.p_sim, z.over), desk=ll(z.p_desk_live, z.over)) for (lg, m), z in Z.groupby(["lg", "mkt"])]
rows.append(dict(lg="ALL", mkt="all", n=len(Z), hardrock=ll(Z.p_hr, Z.over), model=ll(Z.p_mod, Z.over), sim=ll(Z.p_sim, Z.over), desk=ll(Z.p_desk_live, Z.over)))
pd.set_option("display.width", 200); print(pd.DataFrame(rows).round(4).to_string(index=False))
R.to_pickle("close_scored_sim.pkl")

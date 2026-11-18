# Research tool for the weekly review (v3.20). Run from a scratch folder: mkdir -p /home/claude/props/lab && cd /home/claude/props/lab && python3 ../src/<this file>. Files it reads and writes land in that folder.
import numpy as np, pandas as pd
from scipy import stats
import sim_bt_nfl as B
from common import nb_k
rng = np.random.default_rng(2026); lr = np.random.default_rng(5); rows = []
def pnb(mu, line, k):
    kk = nb_k(np.array([mu]), *B.DISP[k])[0]; return 1 - stats.nbinom.cdf(np.floor(line), kk, kk / (kk + mu))
for g in B.games[B.games.season >= 2025].itertuples():
    if (g.game_id, g.away_team) not in B.byt or (g.game_id, g.home_team) not in B.byt: continue
    sides, s = B.run(g, 3000, rng)
    M = s["M"]; win = [M < 0, M > 0]; ywin = [g.home_score < g.away_score, g.home_score > g.away_score]
    legs = []
    for j, (x, box) in enumerate(sides):
        for k, (col, f, mn) in (("pass_yds", B.MK["pass_yds"]), ("rec_yds", B.MK["rec_yds"]), ("rush_yds", B.MK["rush_yds"])):
            for i in np.where(x[f].values >= mn)[0]:
                mu = x["mu_" + k].values[i]
                if k == "rec_yds" and mu < 35: continue
                line = np.floor(mu * (1 + lr.choice([-.15, -.05, 0, .05, .15]))) + 0.5
                legs.append(dict(t=j, k=k, smp=box[k][:, i] > line, p=pnb(mu, line, k), y=x[col].values[i] > line))
    for a in range(len(legs)):
        la = legs[a]
        if la["k"] == "rush_yds":
            rows.append(("rusher over + his team wins", (la["smp"] & win[la["t"]]).mean(), la["p"] * win[la["t"]].mean(), la["y"] and ywin[la["t"]]))
        if la["k"] == "pass_yds":
            rows.append(("QB over + his team wins", (la["smp"] & win[la["t"]]).mean(), la["p"] * win[la["t"]].mean(), la["y"] and ywin[la["t"]]))
        for b in range(a + 1, len(legs)):
            lb = legs[b]; ks = {la["k"], lb["k"]}
            if la["t"] == lb["t"] and ks == {"pass_yds", "rec_yds"}: kind = "QB + his receiver"
            elif la["t"] == lb["t"] and ks == {"rec_yds"}: kind = "two receivers, same team"
            elif la["t"] != lb["t"] and ks == {"pass_yds"}: kind = "both QBs"
            elif la["t"] == lb["t"] and ks == {"pass_yds", "rush_yds"}: kind = "QB + his rusher"
            else: continue
            rows.append((kind, (la["smp"] & lb["smp"]).mean(), la["p"] * lb["p"], la["y"] and lb["y"]))
D = pd.DataFrame(rows, columns=["kind", "p_sim", "p_mult", "y"]); D["y"] = D.y.astype(float)
def sc(x):
    o = {"n": len(x), "actual": x.y.mean(), "sim says": x.p_sim.mean(), "multiplied says": x.p_mult.mean()}
    for c, nm in (("p_sim", "sim"), ("p_mult", "mult")):
        p = x[c].clip(.002, .998); o["ll_" + nm] = -(x.y * np.log(p) + (1 - x.y) * np.log(1 - p)).mean()
    o["ll_gain_%"] = (1 - o["ll_sim"] / o["ll_mult"]) * 100; return pd.Series(o)
T = D.groupby("kind").apply(sc); T.loc["all pairs"] = sc(D); pd.set_option("display.width", 200)
print(T.round(4).to_string()); T.round(5).to_csv("bt_joint_nfl.csv")

# Research tool for the weekly review (v3.20). Run from a scratch folder: mkdir -p /home/claude/props/lab && cd /home/claude/props/lab && python3 ../src/<this file>. Files it reads and writes land in that folder.
"""Same-game parlay test: does the simulator price two legs together better than multiplying the legs (what you get
from pricing each prop on its own)? Same test window and inputs as sim_bt.py, scored once."""
import numpy as np, pandas as pd
from scipy import stats
import sim_bt as B
from common import nb_k
rng = np.random.default_rng(2026); lr = np.random.default_rng(5)
G, PR = B.G, B.PR
gids = G.index[((G.season == 2026) & (G.gd >= "2026-01-01") | (G.season == 2027)) & G.line_m.notna()].values
rows = []
def pnb(mu, line, k):
    kk = nb_k(mu, *B.DISP[k]); return 1 - stats.nbinom.cdf(np.floor(line), kk, kk / (kk + mu))
for gid in gids:
    r = G.loc[gid]
    x = B.byg[gid]; h = x[x.ha == "home"]; a = x[x.ha == "away"]
    s = B.nba_game(rng, 4000, B.side(h), B.side(a), r.line_m, r.line_t, PR, sd_m=PR["sd_m"], sd_t=PR["sd_t"])
    teams = [(a, s["teams"][0], 0), (h, s["teams"][1], 1)]
    win = [(s["M"] < 0), (s["M"] > 0)]                     # away wins, home wins
    tot_line = np.floor(r.line_t) + 0.5; tot_over = s["score"].sum(1) > tot_line; y_tot = r.TT > tot_line
    y_win = [r.M < 0, r.M > 0]
    legs = []
    for x_, box, j in teams:
        for i in np.where(x_.mn.values >= 24)[0]:
            for k in ("pts", "reb", "ast"):
                mu = x_["mu_" + k].values[i]; line = np.floor(mu * (1 + lr.choice([-.15, -.05, 0, .05, .15]))) + 0.5
                legs.append(dict(team=j, k=k, smp=box[k][:, i] > line, p_nb=pnb(mu, line, k), y=x_[k].values[i] > line, name=x_.name.values[i]))
    for A in range(len(legs)):
        la = legs[A]
        # with the game legs
        for nm, sm, y in (("over + team wins", win[la["team"]], y_win[la["team"]]), ("over + game total over", tot_over, y_tot)):
            if la["k"] != "pts": continue
            rows.append((nm, (la["smp"] & sm).mean(), la["p_nb"] * sm.mean(), la["smp"].mean() * sm.mean(), la["y"] and y))
        for Bi in range(A + 1, len(legs)):
            lb = legs[Bi]
            if la["name"] == lb["name"]:
                kind = "same player, two stats"
            elif la["k"] != lb["k"]:
                continue
            else:
                kind = ("teammates " if la["team"] == lb["team"] else "opponents ") + la["k"]
            rows.append((kind, (la["smp"] & lb["smp"]).mean(), la["p_nb"] * lb["p_nb"], la["smp"].mean() * lb["smp"].mean(), la["y"] and lb["y"]))
D = pd.DataFrame(rows, columns=["kind", "p_sim", "p_mult", "p_simind", "y"]); D["y"] = D.y.astype(float)
def sc(x):
    out = {"n": len(x), "actual": x.y.mean(), "sim says": x.p_sim.mean(), "multiplied says": x.p_mult.mean()}
    for c, nm in (("p_sim", "sim"), ("p_mult", "mult")):
        p = x[c].clip(.002, .998); out["brier_" + nm] = ((x[c] - x.y) ** 2).mean(); out["ll_" + nm] = -(x.y * np.log(p) + (1 - x.y) * np.log(1 - p)).mean()
    out["ll_gain_%"] = (1 - out["ll_sim"] / out["ll_mult"]) * 100
    return pd.Series(out)
T = D.groupby("kind").apply(sc); T.loc["all pairs"] = sc(D)
pd.set_option("display.width", 220); print(len(gids), "games"); print(T.round(4).to_string())
T.round(5).to_csv("bt_joint.csv")

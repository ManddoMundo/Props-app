# Research tool for the weekly review (v3.20). Run from a scratch folder: mkdir -p /home/claude/props/lab && cd /home/claude/props/lab && python3 ../src/<this file>. Files it reads and writes land in that folder.
"""NFL simulator backtest (research script).
Charter (locked before fitting): targets are receptions, receiving yards, carries, rushing yards, pass attempts,
completions and passing yards, on the same relevance filters as nfl.py's backtest. Projections are nfl.py walk-forward
with the model fitted on 2023-24 only. Game inputs: the closing spread and total (nflverse), the same numbers nfl.py's
projections already use. Every simulator setting is fitted on 2023-24; folds 2025 and 2026 are scored once. Baseline:
each prop on its own negative binomial at the same projection. Primary metric CRPS; secondary Brier and log loss on lines
near the projection; then a same-game pair test against multiplying the legs."""
import sys, json, time
sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
from scipy import stats
import simcore
from simcore import nfl_game, crps_sorted
from common import nb_k

t0 = time.time()
P = pd.read_parquet("nfl_proj.parquet"); T = pd.read_parquet("nfl_team.parquet"); Gm = pd.read_parquet("nfl_games.parquet").dropna(subset=["home_score"])
MTR = json.load(open("nfl_mtr.json")); DISP = MTR["disp"]
PR = simcore.NFL
P["rfrac"] = (P.mu_tgt * P.rtd) / (P.mu_tgt * P.rtd + P.CAR * P.csn * P.rutd).clip(lower=1e-6)
byt = {k: v for k, v in P.groupby(["game_id", "team"])}
tt = T.set_index(["game_id", "team"])
games = Gm.merge(T[["game_id", "season", "week"]].drop_duplicates("game_id"), on="game_id")
games = games[games.game_id.isin(P.game_id.unique())]
MK = {"rec": ("receptions", "mu_tgt", 2.5), "rec_yds": ("receiving_yards", "mu_tgt", 2.5), "rush_att": ("carries", "f_rush", 4),
      "rush_yds": ("rushing_yards", "f_rush", 4), "pass_att": ("attempts", "f_pass", 15), "pass_cmp": ("completions", "f_pass", 15),
      "pass_yds": ("passing_yards", "f_pass", 15)}


def side(gid, team):
    x = byt[(gid, team)]; r = tt.loc[(gid, team)]
    mu = {"tgt": x.mu_tgt.values, "rec": x.mu_rec.values, "rec_yds": x.mu_rec_yds.values, "rush_att": x.mu_rush_att.values,
          "rush_yds": x.mu_rush_yds.values, "pass_att": x.mu_pass_att.values, "pass_cmp": x.mu_pass_cmp.values,
          "pass_yds": x.mu_pass_yds.values, "td": x.mu_td.values}
    return x, dict(PA=float(r.PA), CAR=float(r.CAR), ip=float(r.ip), mu=mu, qb=(x.pos == "QB").values & (x.f_pass.values >= 5), rfrac=x.rfrac.values, pos=x.pos.values)


def run(g, N, rng):
    xa, a = side(g.game_id, g.away_team); xh, h = side(g.game_id, g.home_team)
    s = nfl_game(rng, N, h, a, g.spread_line, g.total_line, PR)
    return [(xa, s["teams"][0]), (xh, s["teams"][1])], s


def evaluate(gs, N, seed, mk=MK):
    rng = np.random.default_rng(seed); lr = np.random.default_rng(11); rows = []
    for g in gs.itertuples():
        if (g.game_id, g.away_team) not in byt or (g.game_id, g.home_team) not in byt:
            continue
        sides, _ = run(g, N, rng)
        for x, box in sides:
            for k, (col, f, mn) in mk.items():
                keep = (x[f].values >= mn)
                if not keep.any():
                    continue
                smp = box[k][:, keep]; mu = x["mu_" + k].values[keep]; y = x[col].values[keep].astype(float)
                c_sim = crps_sorted(smp, y)
                kk = nb_k(mu, *DISP[k]); pp = kk / (kk + mu)
                y0 = np.maximum(np.round(y), 0)
                xmax = int(max(y0.max(), np.percentile(smp, 99.9), mu.max() * 4 + 20))
                grid = np.arange(xmax + 1)
                Fnb = stats.nbinom.cdf(grid[None, :], kk[:, None], pp[:, None])
                c_nb = ((Fnb - (y0[:, None] <= grid)) ** 2).sum(axis=1)
                # CRPS of NB is on the integer grid; for yards (which can be negative for rushing) the sample CRPS of the sim
                # is compared with the NB's grid CRPS on y clipped at 0, the same rows for both
                off = lr.choice([-0.35, -0.2, -0.1, 0.0, 0.1, 0.2, 0.35], size=len(y))
                line = np.floor(mu * (1 + off)) + 0.5
                p_sim = (smp > line).mean(axis=0); p_nb = 1 - stats.nbinom.cdf(np.floor(line), kk, pp)
                for i in range(len(y)):
                    rows.append((g.game_id, int(g.season), k, mu[i], y[i], line[i], c_sim[i], c_nb[i], p_sim[i], p_nb[i]))
    return pd.DataFrame(rows, columns=["gid", "season", "stat", "mu", "y", "line", "crps_sim", "crps_nb", "p_sim", "p_nb"])


def summ(df, label):
    df = df.assign(hit=(df.y > df.line).astype(float)); out = []
    for k, x in df.groupby("stat"):
        ps = np.clip(x.p_sim, .005, .995); pn = np.clip(x.p_nb, .005, .995)
        out.append(dict(set=label, stat=k, n=len(x), crps_sim=x.crps_sim.mean(), crps_nb=x.crps_nb.mean(),
                        brier_sim=((x.p_sim - x.hit) ** 2).mean(), brier_nb=((x.p_nb - x.hit) ** 2).mean(),
                        ll_sim=-(x.hit * np.log(ps) + (1 - x.hit) * np.log(1 - ps)).mean(), ll_nb=-(x.hit * np.log(pn) + (1 - x.hit) * np.log(1 - pn)).mean(),
                        mean_sim_bias=np.nan))
    R = pd.DataFrame(out); R["crps_gain_%"] = (1 - R.crps_sim / R.crps_nb) * 100; R["brier_gain_%"] = (1 - R.brier_sim / R.brier_nb) * 100
    return R


if __name__ == "__main__":
    tr = games[(games.season <= 2024) & ~((games.season == 2023) & (games.week <= 4))]
    fit_g = tr.sample(220, random_state=3)
    for k, stat, grid in (("tgt", "rec", [15, 30, 60, 120, 240]), ("car", "rush_att", [15, 30, 60, 120, 240])):
        res = []
        for a in grid:
            PR["alpha"][k] = a
            e = evaluate(fit_g, 800, 5, {stat: MK[stat]})
            res.append((e.crps_sim.mean(), a))
        PR["alpha"][k] = min(res)[1]
        print("alpha", k, [(a, round(c, 4)) for c, a in res], "->", PR["alpha"][k], "| NB %.4f" % e.crps_nb.mean())
    # mean check on train: the sim should keep each projection's average
    e = evaluate(fit_g, 800, 6)
    print("train means (sim mean of hits vs NB):", e.groupby("stat").apply(lambda x: round(((x.p_sim - x.p_nb)).mean(), 4)).to_dict())
    print(summ(e, "train").round(4).to_string(index=False))
    json.dump(PR, open("sim_params_nfl.json", "w"), indent=1)
    print("fit %.0fs" % (time.time() - t0))
    res = []
    for s in (2025, 2026):
        gs = games[games.season == s]
        e = evaluate(gs, 2000, 99); e.to_parquet(f"bt_nfl_{s}.parquet")
        res.append(summ(e, f"{s} ({e.gid.nunique()} games)"))
    R = pd.concat(res); pd.set_option("display.width", 250)
    print(R.round(4).to_string(index=False)); R.to_csv("bt_nfl_summary.csv", index=False)
    print("done %.0fs" % (time.time() - t0))
else:
    try:
        PR.update(json.load(open("sim_params_nfl.json")))
    except Exception:
        pass

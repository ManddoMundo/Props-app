# Research tool for the weekly review (v3.20). Run from a scratch folder: mkdir -p /home/claude/props/lab && cd /home/claude/props/lab && python3 ../src/<this file>. Files it reads and writes land in that folder.
"""Simulator backtest for the NBA (research script; the weekly review can rerun it).

Charter (locked before fitting):
  Target: points, rebounds, assists, threes and P+R+A for players projected 15+ minutes. Decision time: before tip.
  Projections: nba.py walk-forward, model fitted on 2024-25 only (prep_nba.py writes them).
  Train: 2024-25 for every simulator setting (minutes table, team noise, share concentration, model-input spreads);
         2025-26 games before Jan 1, 2026 only for the spread and total noise around the closing line.
  Test (scored once): fold A = Jan 1, 2026 to the end of 2025-26; fold B = 2026-27 so far.
  Baseline: today's pricing curve, each player on his own (negative binomial at the same projection, same dispersion).
  Primary metric: mean CRPS per stat (lower is better). Secondary: Brier and log loss on half-point lines near the
  projection (the lines the desk actually prices), reliability, and slices by how lopsided the game finished.
  Same rows for both. The simulator can only take over pricing if it beats the baseline in both folds on the primary
  metric for points, rebounds and assists without worse calibration, and then only after 200+ live graded sides."""
import sys, json, time
sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
from scipy import stats
import simcore
from simcore import nba_game, crps_samples
from common import nb_k

t0 = time.time()
P = pd.read_parquet("nba_proj.parquet")
MTR = json.load(open("nba_mtr.json"))
P["gid"] = P.game_id.astype(str)
P["ha"] = P.home_away
BASE = ["pts", "reb", "ast", "fg3"]

# ---------------- game table
t = P.groupby(["gid", "ha"]).agg(Pt=("pts", "sum"), Pm=("mu_pts", "sum"), gd=("gd", "first"), season=("season", "first"), team=("team", "first")).reset_index()
g = t.pivot(index="gid", columns="ha")
G = pd.DataFrame({"gd": g["gd"]["home"], "season": g["season"]["home"], "home": g["team"]["home"], "away": g["team"]["away"],
                  "Ph": g["Pt"]["home"], "Pa": g["Pt"]["away"], "Pmh": g["Pm"]["home"], "Pma": g["Pm"]["away"]}).dropna()
for c in ["Ph", "Pa", "Pmh", "Pma"]: G[c] = G[c].astype(float)
G["season"] = G.season.astype(int)
G["M"] = G.Ph - G.Pa; G["TT"] = G.Ph + G.Pa
lines = {}
for l in open("/home/claude/props/out/nba_lines.jsonl"):
    r = json.loads(l)
    if not r["pc"]:
        continue
    c = r["pc"][0]; oc = (c.get("oc") or {}).get("c") or [c.get("spread"), c.get("ou")]
    if oc[0] is None or oc[1] is None or not c.get("det"):
        continue
    lines[r["id"]] = (c["det"], float(oc[0]), float(oc[1]))
G["line_m"] = np.nan; G["line_t"] = np.nan
for gid, (det, sp, ou) in lines.items():
    if gid in G.index:
        tm, v = det.rsplit(" ", 1)
        try:
            v = float(v)
        except ValueError:
            v = 0.0                 # "EVEN"
        G.loc[gid, "line_m"] = -v if tm == G.loc[gid, "home"] else v
        G.loc[gid, "line_t"] = ou
chk = G.dropna(subset=["line_m"])
print("lines joined", len(chk), "| sign check corr(line margin, final margin) %.3f" % np.corrcoef(chk.line_m, chk.M)[0, 1])

tr = G.season == 2025
trB = (G.season == 2026) & (G.gd < "2026-01-01") & G.line_m.notna()
foldA = (G.season == 2026) & (G.gd >= "2026-01-01")
foldB = G.season == 2027
PR = simcore.NBA
PR["hfa_model"] = float((G.M - (G.Pmh - G.Pma))[tr].mean())
PR["sd_m_model"] = float((G.M - (G.Pmh - G.Pma) - PR["hfa_model"])[tr].std())
tb = (G.TT - (G.Pmh + G.Pma))[tr]
PR["tadj_model"] = float(tb.mean()); PR["sd_t_model"] = float(tb.std())
PR["sd_m"] = float((G.M - G.line_m)[trB].std()); PR["sd_t"] = float((G.TT - G.line_t)[trB].std())
print("model inputs: hfa %.2f sd_m %.2f total adj %.2f sd_t %.2f | market inputs (n=%d): sd_m %.2f sd_t %.2f, bias m %.2f t %.2f" % (
    PR["hfa_model"], PR["sd_m_model"], PR["tadj_model"], PR["sd_t_model"], trB.sum(), PR["sd_m"], PR["sd_t"], (G.M - G.line_m)[trB].mean(), (G.TT - G.line_t)[trB].mean()))

# ---------------- minutes table and team noise (2024-25)
P = P.merge(G[["M"]], left_on="gid", right_index=True)
P["aM"] = P.M.abs()
P["tier"] = simcore.tier_of(P.mn.values, PR["tiers"])
P["r"] = P.y_min / P.mn
ptr = P[P.season == 2025]
edges = [-1, 5, 10, 15, 20, 25, 30, 80]
tab = ptr.groupby(["tier", pd.cut(ptr.aM, edges)], observed=False).r.mean().unstack().values
w = pd.cut(ptr.aM, edges).value_counts(normalize=True, sort=False).values
tab = tab / (tab @ w)[:, None]                    # relative: averages to 1 over the margins teams actually see
PR["mrel"] = np.round(tab, 4).tolist()
ptr = ptr.assign(rel=[np.interp(a, PR["mbins"], tab[ti]) for a, ti in zip(ptr.aM, ptr.tier)])
lr = np.log(np.maximum(ptr.y_min, 1) / (ptr.mn * ptr.rel))
PR["msd"] = [round(float(lr[ptr.tier == i].std()), 4) for i in range(4)]
tt = P.groupby(["gid", "team", "season"]).agg(Pt=("pts", "sum"), Pm=("mu_pts", "sum"), **{k: (k, "sum") for k in ["fg3", "reb", "ast"]},
                                             **{"m_" + k: ("mu_" + k, "sum") for k in ["fg3", "reb", "ast"]}).reset_index()
tt = tt[tt.season == 2025]
for k in ["fg3", "reb", "ast"]:
    x = np.log(tt.Pt / tt.Pm); y = np.log(np.maximum(tt[k], 0.5) / tt["m_" + k])
    b = np.polyfit(x, y, 1)
    pred = tt["m_" + k] * np.exp(np.polyval(b, x))
    PR["gam"][k] = round(float(b[0]), 3); PR["tint"][k] = round(float(b[1]), 3)
    PR["tsd"][k] = round(float(((tt[k] - pred) / pred).std()), 4)
print("minutes table", PR["mrel"], "noise", PR["msd"])
print("team stats: gam", PR["gam"], "int", PR["tint"], "sd", PR["tsd"])

# ---------------- run helpers
byg = {gid: x for gid, x in P.groupby("gid")}
DISP = MTR["disp"]


def side(x):
    return dict(mu={k: x["mu_" + k].values for k in BASE}, mn=x.mn.values)


def sim_game(rng, gid, N, inputs):
    x = byg[gid]; h = x[x.ha == "home"]; a = x[x.ha == "away"]
    r = G.loc[gid]
    if inputs == "market" and not np.isnan(r.line_m):
        m, tot, sm, st = r.line_m, r.line_t, PR["sd_m"], PR["sd_t"]
    else:
        m = r.Pmh - r.Pma + PR["hfa_model"]; tot = r.Pmh + r.Pma + PR["tadj_model"]; sm, st = PR["sd_m_model"], PR["sd_t_model"]
    s = nba_game(rng, N, side(h), side(a), m, tot, PR, sd_m=sm, sd_t=st)
    return [(a, s["teams"][0]), (h, s["teams"][1])]


def evaluate(gids, N, inputs, seed=7, stats_=("pts", "reb", "ast", "fg3", "pra"), lines_rng=None):
    rng = np.random.default_rng(seed)
    lr = np.random.default_rng(11)
    rows = []
    for gid in gids:
        for x, box in sim_game(rng, gid, N, inputs):
            keep = (x.mn >= 15).values
            if not keep.any():
                continue
            for k in stats_:
                if k == "pra":
                    smp = box["pts"] + box["reb"] + box["ast"]; mu = (x.mu_pts + x.mu_reb + x.mu_ast).values; y = (x.pts + x.reb + x.ast).values
                else:
                    smp = box[k]; mu = x["mu_" + k].values; y = x[k].values
                smp = smp[:, keep]; mu = mu[keep]; y = y[keep].astype(int)
                xmax = int(max(smp.max(), y.max(), mu.max() * 3 + 10))
                c_sim = crps_samples(smp, y, xmax)
                kk = nb_k(mu, *DISP[k]); pp = kk / (kk + mu)
                grid = np.arange(xmax + 1)
                Fnb = stats.nbinom.cdf(grid[None, :], kk[:, None], pp[:, None])
                c_nb = ((Fnb - (y[:, None] <= grid)) ** 2).sum(axis=1)
                off = lr.choice([-0.35, -0.2, -0.1, 0.0, 0.1, 0.2, 0.35], size=len(y))
                line = np.floor(mu * (1 + off)) + 0.5
                p_sim = (smp > line).mean(axis=0)
                p_nb = 1 - stats.nbinom.cdf(np.floor(line), kk, pp)
                for i in range(len(y)):
                    rows.append((gid, k, mu[i], y[i], line[i], c_sim[i], c_nb[i], p_sim[i], p_nb[i]))
    return pd.DataFrame(rows, columns=["gid", "stat", "mu", "y", "line", "crps_sim", "crps_nb", "p_sim", "p_nb"])


def summ(df, label):
    df = df.assign(hit=(df.y > df.line).astype(float))
    out = []
    for k, x in df.groupby("stat"):
        ps = np.clip(x.p_sim, .005, .995); pn = np.clip(x.p_nb, .005, .995)
        out.append(dict(set=label, stat=k, n=len(x), crps_sim=x.crps_sim.mean(), crps_nb=x.crps_nb.mean(),
                        brier_sim=((x.p_sim - x.hit) ** 2).mean(), brier_nb=((x.p_nb - x.hit) ** 2).mean(),
                        ll_sim=-(x.hit * np.log(ps) + (1 - x.hit) * np.log(1 - ps)).mean(), ll_nb=-(x.hit * np.log(pn) + (1 - x.hit) * np.log(1 - pn)).mean()))
    return pd.DataFrame(out)


if __name__ == "__main__":
    # ---------------- concentration grid on 2024-25 (300 games, 600 runs each; the order fits threes first, then the rest)
    rng_g = np.random.default_rng(3)
    fit_g = rng_g.choice(G.index[tr].values, 300, replace=False)
    for k, grid in (("fg3", [10, 20, 40, 80, 160]), ("non3", [20, 40, 80, 160, 320]), ("reb", [60, 120, 240, 480, 1000, 3000]), ("ast", [40, 80, 160, 320, 640, 2000])):
        res = []
        stat = "pts" if k == "non3" else k
        for a in grid:
            PR["alpha"][k] = a
            e = evaluate(fit_g, 600, "model", stats_=(stat,))
            res.append((e.crps_sim.mean(), a))
        PR["alpha"][k] = min(res)[1]
        print("alpha", k, [(a, round(c, 4)) for c, a in res], "->", PR["alpha"][k], "| NB on same rows %.4f" % e.crps_nb.mean())
    json.dump({k: v for k, v in PR.items()}, open("sim_params_nba.json", "w"), indent=1)
    print("fit done %.0fs" % (time.time() - t0))

    # ---------------- test, scored once per fold
    res = []
    for label, mask in (("A model", foldA), ("B model", foldB), ("A market", foldA & G.line_m.notna()), ("B market", foldB & G.line_m.notna())):
        gids = G.index[mask].values
        e = evaluate(gids, 2000, label.split()[1], seed=99)
        e.to_parquet(f"bt_{label.replace(' ', '_')}.parquet")
        s = summ(e, label + f" ({len(gids)} games)")
        res.append(s)
        # slices by how the game finished (after the fact, for diagnosis only)
        am = G.loc[e.gid, "M"].abs().values
        for nm, m in (("final margin 20+", am >= 20), ("final margin under 10", am < 10)):
            res.append(summ(e[m], label + " | " + nm))
    R = pd.concat(res)
    R["crps_gain_%"] = (1 - R.crps_sim / R.crps_nb) * 100
    R["brier_gain_%"] = (1 - R.brier_sim / R.brier_nb) * 100
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(R.round(4).to_string(index=False))
    R.to_csv("bt_summary.csv", index=False)
    print("done %.0fs" % (time.time() - t0))
else:
    PR.update(json.load(open("sim_params_nba.json")))

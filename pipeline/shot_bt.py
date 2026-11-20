"""Lab, v3.50 (nothing here runs in the daily job; the result went into nba.py in v3.50): should NBA points and threes be built from shot volume and shooting
percentage instead of points per minute? The idea: shots per minute are steady, shooting percentage over a few weeks is
mostly luck, so remember volume on the usual 15-game half-life and remember percentages for much longer.
Walk-forward: every setting is chosen on 2024-25 after the warm-up, then scored once on 2025-26 and 2026-27.
Needs the box score files run.sh downloads. Run: python3 shot_bt.py. Findings are in CHANGELOG v3.50."""
import sys, os, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collections import defaultdict
import numpy as np, pandas as pd
import nba
BASE = nba.BASE
SHOT = ["a2", "m2", "a3", "m3", "fa", "fm"]


def shots(d):
    d = d.copy()
    f = lambda c: pd.to_numeric(d[c], errors="coerce").fillna(0)
    d["a3"], d["m3"] = f("three_point_field_goals_attempted"), d["fg3"]
    d["a2"], d["m2"] = f("field_goals_attempted") - d["a3"], f("field_goals_made") - d["m3"]
    d["fa"], d["fm"] = f("free_throws_attempted"), f("free_throws_made")
    return d


def alt_rates(d, hlc, pk, carry_c=nba.CARRY):
    """Per player-game, from earlier games only: points and threes per minute rebuilt as volume x percentage.
    hlc = half-life in games for the percentages; pk = scale on the prior (attempts at the position's percentage)."""
    tr0 = d[d.season == 2025]
    pri = {p: dict(v2=x.a2.sum() / x["min"].sum(), v3=x.a3.sum() / x["min"].sum(), vf=x.fa.sum() / x["min"].sum(),
                   p2=x.m2.sum() / x.a2.sum(), p3=x.m3.sum() / x.a3.sum(), pf=x.fm.sum() / x.fa.sum()) for p, x in tr0.groupby("pos")}
    N0 = dict(p2=60 * pk, p3=120 * pk, pf=40 * pk)
    DC = 0.5 ** (1 / hlc)
    V, C, ps, out = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float)), {}, []
    cols = ["pid", "pos", "min", "season"] + SHOT
    for gid, g in d.groupby("game_id", sort=False):
        rows = g[cols].to_dict("records")
        for r in rows:
            v, c, P = V[r["pid"]], C[r["pid"]], pri[r["pos"]]
            vol = {k: (v[a] + nba.PM0 * P[k]) / (v["min"] + nba.PM0) for k, a in (("v2", "a2"), ("v3", "a3"), ("vf", "fa"))}
            pct = {k: (c[m] + N0[k] * P[k]) / (c[a] + N0[k]) for k, m, a in (("p2", "m2", "a2"), ("p3", "m3", "a3"), ("pf", "fm", "fa"))}
            out.append((gid, r["pid"], 2 * vol["v2"] * pct["p2"] + 3 * vol["v3"] * pct["p3"] + vol["vf"] * pct["pf"], vol["v3"] * pct["p3"],
                        c["m3"] / c["a3"] if c["a3"] >= 20 else np.nan, vol["v3"]))
        for r in rows:
            pid = r["pid"]; v, c = V[pid], C[pid]
            if ps.get(pid, r["season"]) != r["season"]:
                for k in list(v): v[k] *= nba.CARRY
                for k in list(c): c[k] *= carry_c
            ps[pid] = r["season"]
            for k in ("a2", "a3", "fa", "min"): v[k] = v[k] * nba.DR + r[k]
            for k in SHOT: c[k] = c[k] * DC + r[k]
    return pd.DataFrame(out, columns=["game_id", "pid", "ra_pts", "ra_fg3", "long3", "v3"])


def fit(pr, tr, is_tr, bm):
    """the same steps nba.main() uses: team-share strength per stat, then level and slope, all on the fit season"""
    M = {"bm": bm, "bs": {k: 0.5 for k in BASE}, "cal": {}}
    for k in BASE:
        best = None
        for bs in (0.0, 0.25, 0.5, 0.75, 1.0):
            M["bs"][k] = bs; dd = nba.project(pr[is_tr], tr, M); mm = dd.mn >= 15
            e = np.abs(dd.loc[mm, k] - dd.loc[mm, "mu_" + k]).mean()
            if best is None or e < best[0]: best = (e, bs)
        M["bs"][k] = best[1]
    m = dict(bm=bm, bs=dict(M["bs"]), cal={})
    dd = nba.project(pr[is_tr], tr, m); mm = dd.mn >= 15
    m["cal"] = {k: float(dd.loc[mm, k].sum() / dd.loc[mm, "mu_" + k].sum()) for k in BASE}
    dd = nba.project(pr[is_tr], tr, m); mm = dd.mn >= 15
    m["lin"] = {k: [float(v) for v in np.polyfit(dd.loc[mm, "mu_" + k], dd.loc[mm, k], 1)[::-1]] for k in BASE}
    return m


def best_bm(pr, tr, is_tr):
    M = {"bm": 0.8, "bs": {k: 0.5 for k in BASE}, "cal": {}}; best = None
    for bm in (0.0, 0.5, 0.8, 1.0):
        M["bm"] = bm; dd = nba.project(pr[is_tr], tr, M); e = np.abs(dd.y_min - dd.mn).mean()
        if best is None or e < best[0]: best = (e, bm)
    return best[1]


def swap(pr, A, w):
    """blend the rebuilt rate into the model's own: w = 0 is today's model, w = 1 is volume x percentage only"""
    x = pr.merge(A, on=["game_id", "pid"], how="left")
    x["r_pts"] = (1 - w[0]) * x.r_pts + w[0] * x.ra_pts
    x["r_fg3"] = (1 - w[1]) * x.r_fg3 + w[1] * x.ra_fg3
    return x


def mae(dd, k):
    mm = dd.mn >= 15
    return float(np.abs(dd.loc[mm, k] - dd.loc[mm, "mu_" + k]).mean())


if __name__ == "__main__":
    nba.SHOT_ON = False      # since v3.50 the model uses the shot build; turn it off here to rebuild the old rates as the baseline
    d = nba.load(); pr, tr, S = nba.walk(d)
    first = pr[pr.season == 2025].gd.min()
    warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
    is_tr, is_te = warm & (pr.season == 2025), pr.season >= 2026
    bm = best_bm(pr, tr, is_tr)
    m0 = fit(pr, tr, is_tr, bm); b_tr = nba.project(pr[is_tr], tr, m0); b_te = nba.project(pr[is_te], tr, m0)
    print("today's model      fit pts %.4f fg3 %.4f | test pts %.4f fg3 %.4f" % (mae(b_tr, "pts"), mae(b_tr, "fg3"), mae(b_te, "pts"), mae(b_te, "fg3")))
    # 1. choose the percentage memory and the prior on the fit season only
    res = []
    for hlc, pk in itertools.product((15.0, 40.0, 100.0, 1e9), (0.5, 1.0, 2.0)):
        A = alt_rates(d, hlc, pk); x = swap(pr, A, (1.0, 1.0)); m = fit(x, tr, is_tr, bm); dd = nba.project(x[is_tr], tr, m)
        res.append((mae(dd, "pts"), mae(dd, "fg3"), hlc, pk)); print("  hl %-6g prior x%.1f  fit pts %.4f fg3 %.4f" % (hlc, pk, res[-1][0], res[-1][1]))
    kp = min(res, key=lambda r: r[0])[2:]; k3 = min(res, key=lambda r: r[1])[2:]
    print("chosen on the fit season: points", kp, "threes", k3)
    Ap, A3 = alt_rates(d, *kp), alt_rates(d, *k3)
    A = Ap[["game_id", "pid", "ra_pts"]].merge(A3[["game_id", "pid", "ra_fg3", "long3", "v3"]], on=["game_id", "pid"])
    # 2. choose the blend weight on the fit season only
    best = {}
    for i, k in ((0, "pts"), (1, "fg3")):
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            ww = [0.0, 0.0]; ww[i] = w; x = swap(pr, A, ww); m = fit(x, tr, is_tr, bm); e = mae(nba.project(x[is_tr], tr, m), k)
            print("  %s weight %.2f fit %.4f" % (k, w, e))
            if k not in best or e < best[k][0]: best[k] = (e, w)
    w = (best["pts"][1], best["fg3"][1]); print("chosen weights (points, threes):", w)
    # 3. one look at the seasons it never saw
    x = swap(pr, A, w); m1 = fit(x, tr, is_tr, bm); a_te = nba.project(x[is_te], tr, m1)
    assert (a_te.pid.values == b_te.pid.values).all() and (a_te.game_id.values == b_te.game_id.values).all()
    rng = np.random.default_rng(7)
    for k in ("pts", "fg3", "pra", "pr", "pa"):
        for lab, sm in (("2025-26", b_te.season == 2026), ("2026-27", b_te.season == 2027), ("both", b_te.season >= 2026)):
            mm = (b_te.mn >= 15) & sm
            eb, ea = np.abs(b_te.loc[mm, k] - b_te.loc[mm, "mu_" + k]), np.abs(a_te.loc[mm, k] - a_te.loc[mm, "mu_" + k])
            # paired bootstrap by game day: is the difference more than noise?
            g = pd.DataFrame(dict(d=(ea - eb).values, gd=b_te.loc[mm, "gd"].values)).groupby("gd").d.agg(["sum", "count"])
            bs = []
            for _ in range(2000):
                s = g.iloc[rng.integers(0, len(g), len(g))]; bs.append(s["sum"].sum() / s["count"].sum())
            lo, hi = np.percentile(bs, [2.5, 97.5])
            print("TEST %-4s %-8s n=%6d  today %.4f  shot build %.4f  change %+.2f%%  (95%%: %+.2f%% to %+.2f%%)" %
                  (k, lab, mm.sum(), eb.mean(), ea.mean(), 100 * (ea.mean() / eb.mean() - 1), 100 * lo / eb.mean(), 100 * hi / eb.mean()))
    # 4. the video's claim, checked directly: does today's model chase hot and cold shooting?
    t = b_te.merge(A[["game_id", "pid", "long3", "v3"]], on=["game_id", "pid"], how="left")
    t["a_pts"], t["a_fg3"] = a_te.mu_pts.values, a_te.mu_fg3.values
    q = d.sort_values(["pid", "gd"]).copy()
    for c in ("pts", "a2", "a3", "fa", "m3"):
        q["s_" + c] = q.groupby("pid")[c].transform(lambda s: s.shift().rolling(10, min_periods=6).sum())
        q["L_" + c] = q.groupby("pid")[c].transform(lambda s: s.shift().rolling(60, min_periods=25).sum())
    q["ts10"] = q.s_pts / (2 * (q.s_a2 + q.s_a3 + 0.44 * q.s_fa)); q["ts60"] = q.L_pts / (2 * (q.L_a2 + q.L_a3 + 0.44 * q.L_fa))
    q["heat"] = q.ts10 - q.ts60
    t = t.merge(q[["game_id", "pid", "heat", "s_a3"]], on=["game_id", "pid"], how="left")
    z = t[(t.mn >= 20) & t.heat.notna()]
    print("shooting over his last 10 against his last 60 (true shooting), test seasons, 20+ minutes: actual points / projected")
    for lab, m in (("cold (-5 pts or worse)", z.heat <= -.05), ("a little cold", (z.heat > -.05) & (z.heat <= -.015)), ("normal", z.heat.abs() < .015),
                   ("a little hot", (z.heat >= .015) & (z.heat < .05)), ("hot (+5 pts or better)", z.heat >= .05)):
        y = z[m]; print("  %-24s n=%6d  today %.3f  shot build %.3f   threes: today %.3f  shot build %.3f" %
                        (lab, len(y), y.pts.sum() / y.mu_pts.sum(), y.pts.sum() / y.a_pts.sum(), y.fg3.sum() / y.mu_fg3.sum(), y.fg3.sum() / y.a_fg3.sum()))
    t.to_pickle("/home/claude/props/lab/shot_te.pkl")

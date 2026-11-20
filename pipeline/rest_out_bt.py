"""Lab, v3.46 (nothing here runs in the daily job): does the NBA model need a rest adjustment, a teammate-out adjustment
or a stronger pull to average on thin files? Walk-forward: fitted on 2024-25 after the warm-up, scored on 2025-26 and
2026-27. Needs the box score files run.sh downloads. Run: python3 rest_out_bt.py. Findings are in CHANGELOG v3.46."""
import sys, json
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import nba
BASE = nba.BASE

def prep(pm0=None):
    if pm0 is not None: nba.PM0 = pm0
    d = nba.load(); pr, tr, S = nba.walk(d)
    first = pr[pr.season == 2025].gd.min()
    warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
    is_tr, is_te = warm & (pr.season == 2025), pr.season >= 2026
    M = {"bm": 0.8, "bs": {k: 0.5 for k in BASE}, "cal": {}}
    best = None
    for bm in (0.0, 0.5, 0.8, 1.0):
        M["bm"] = bm; dd = nba.project(pr[is_tr], tr, M); e = np.abs(dd.y_min - dd.mn).mean()
        if best is None or e < best[0]: best = (e, bm)
    M["bm"] = best[1]
    for k in BASE:
        best = None
        for bs in (0.0, 0.25, 0.5, 0.75, 1.0):
            M["bs"][k] = bs; dd = nba.project(pr[is_tr], tr, M); mm = dd.mn >= 15
            e = np.abs(dd.loc[mm, k] - dd.loc[mm, "mu_" + k]).mean()
            if best is None or e < best[0]: best = (e, bs)
        M["bs"][k] = best[1]
    def finish(mask):
        m = dict(bm=M["bm"], bs=dict(M["bs"]), cal={})
        dd = nba.project(pr[mask], tr, m); mm = dd.mn >= 15
        m["cal"] = {k: float(dd.loc[mm, k].sum() / dd.loc[mm, "mu_" + k].sum()) for k in BASE}
        dd = nba.project(pr[mask], tr, m); mm = dd.mn >= 15
        m["lin"] = {k: [float(v) for v in np.polyfit(dd.loc[mm, "mu_" + k], dd.loc[mm, k], 1)[::-1]] for k in BASE}
        return m
    m_tr = finish(is_tr)
    return d, nba.project(pr[is_tr], tr, m_tr), nba.project(pr[is_te], tr, m_tr), m_tr

def extras(d):
    """per team-game: days since the team's last game; per team-game and stat: what the absent regulars usually produce"""
    g = d.groupby(["team", "game_id"]).gd.first().reset_index().sort_values(["team", "gd"])
    g["rest"] = g.groupby("team").gd.transform(lambda s: pd.to_datetime(s).diff().dt.days)
    d = d.sort_values(["pid", "gd"])
    for k in BASE + ["min"]:
        d["l10_" + k] = d.groupby("pid")[k].transform(lambda s: s.shift().rolling(10, min_periods=5).mean())
    rows = []
    for t, x in d.groupby("team"):
        gids = list(dict.fromkeys(x.sort_values("gd").game_id)); by = {gid: y for gid, y in x.groupby("game_id")}
        for i, gid in enumerate(gids):
            if i < 3: continue
            here = set(by[gid].pid); reg = {}
            for pg in gids[i - 3:i]:
                for r in by[pg].itertuples():
                    reg[r.pid] = r      # last game he played among the team's previous three
            miss = [r for p, r in reg.items() if p not in here and r.l10_min == r.l10_min and r.l10_min >= 20]
            rows.append(dict(team=t, game_id=gid, n_out=len(miss), **{"out_" + k: sum(getattr(r, "l10_" + k) for r in miss) for k in BASE + ["min"]}))
    return g[["team", "game_id", "rest"]].merge(pd.DataFrame(rows), on=["team", "game_id"], how="left")

if __name__ == "__main__":
    d, tr, te = prep()[:3]
    ex = extras(d)
    tr = tr.merge(ex, on=["team", "game_id"], how="left"); te = te.merge(ex, on=["team", "game_id"], how="left")
    rat = lambda z: f"n={len(z):5d} min {z.y_min.sum() / z.mn.sum():.3f} " + " ".join(f"{k} {z[k].sum() / z['mu_' + k].sum():.3f}" for k in BASE)
    for nm, x in (("FIT 2024-25", tr), ("TEST 2025-27", te)):
        x = x[x.mn >= 15]; print(nm, "actual / projected")
        for lab, m in (("back-to-back", x.rest == 1), ("1 day off", x.rest == 2), ("2+ days off", x.rest >= 3)):
            print(f"  {lab:<14}", rat(x[m]))
        x = x[x.out_min.notna()]; x = x.assign(rk=x.groupby(["game_id", "team"]).mu_pts.rank(ascending=False))
        for lo, hi in ((0, 1), (1, 30), (30, 60), (60, 90), (90, 400)):
            for lab, m in (("top 2", x.rk <= 2), ("others", x.rk > 2)):
                print(f"  regular minutes out {lo:>3}-{hi:<3} {lab:<6}", rat(x[(x.out_min >= lo) & (x.out_min < hi) & m]))
        print(f"  no star out   ", rat(x[x.out_pts < 18])); print(f"  star out (18+)", rat(x[x.out_pts >= 18]))
    # the correction that was tried: a minutes factor by role and by how many regular minutes are out, fitted on 2024-25
    def role(x):
        x = x[x.out_min.notna()].copy(); x["top"] = x.groupby(["game_id", "team"]).mu_pts.rank(ascending=False) <= 2; x["x"] = x.out_min.clip(0, 150) / 100
        return x
    tr, te = role(tr), role(te); co = {}
    for top in (True, False):
        z = tr[(tr.top == top) & (tr.mn >= 15)]; co[top] = np.linalg.lstsq(np.c_[z.mn, z.mn * z.x], z.y_min, rcond=None)[0]
    print("minutes factor a + b * (regular minutes out / 100):", {("top 2" if k else "others"): v.round(3).tolist() for k, v in co.items()})
    for nm, x in (("2025-26", te[te.season == 2026]), ("2026-27", te[te.season == 2027])):
        f = np.where(x.top, co[True][0] + co[True][1] * x.x, co[False][0] + co[False][1] * x.x); m = x.mn >= 15
        print(" ", nm, "miss before -> after:", " ".join(f"{k} {np.abs(x[k] - x['mu_' + k])[m].mean():.4f} -> {np.abs(x[k] - x['mu_' + k] * f)[m].mean():.4f}" for k in BASE))
    for pm0 in (15, 30, 60, 120):
        t = prep(pm0)[2]; m = t.mn >= 15; thin = m & (t.n < 10)
        print(f"  prior {pm0:>3} pseudo-minutes: all", " ".join(f"{k} {np.abs(t[k] - t['mu_' + k])[m].mean():.4f}" for k in BASE),
              "| under 10 games", " ".join(f"{k} {np.abs(t[k] - t['mu_' + k])[thin].mean():.4f}" for k in BASE))

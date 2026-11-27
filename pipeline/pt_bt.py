#!/usr/bin/env python3
"""Lab research script (nothing here runs in the daily job):
Walk-forward test of decomposing NBA assists and rebounds into tracking volume x steadied conversion:
  - r_ast = (potential_assists / min) * steadied(ast / potential_assists)
  - r_reb = (reb_chances / min)       * steadied(reb / reb_chances)
Exact same methodology and charter structure as shot_bt.py (v3.50):
  - Data: nba_pb_2025..2027.parquet joined with nba_pt_2025..2027.parquet (from pt_pull.py) on (gd, team, norm(name)).
  - Fit split: 2024-25 after 21-day warmup only (selects conversion half-life hlc, prior scale pk, blend weight w).
  - Test split (scored once): 2025-26 and 2026-27 separately and combined, mn >= 15.
  - Primary metric: MAE + 2,000 paired game-day bootstrap draws (must beat baseline in BOTH folds).
  - Diagnostic: actual/projected ratio across hot vs. cold conversion bands (last 10 vs last 60 games).

Run: python3 pt_bt.py"""
import itertools, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/claude/props/src")
from collections import defaultdict
import numpy as np, pandas as pd
import nba, shot_bt
from common import norm

D = "/home/claude/props/data/"
NBA_CODE = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}


def load_pt():
    frames = []
    for y in (2025, 2026, 2027):
        p = f"{D}nba_pt_{y}.parquet"
        if os.path.exists(p):
            frames.append(pd.read_parquet(p))
    if not frames:
        raise FileNotFoundError("No nba_pt_202*.parquet files found. Run pt_pull.py first.")
    pt = pd.concat(frames, ignore_index=True)
    pt["team"] = pt["TEAM_ABBREVIATION"].map(lambda c: NBA_CODE.get(c, c))
    pt["kname"] = pt["PLAYER_NAME"].map(norm)
    pt["pot_ast"] = pd.to_numeric(pt["POTENTIAL_AST"], errors="coerce").fillna(0.0)
    pt["reb_ch"] = pd.to_numeric(pt["REB_CHANCES"], errors="coerce").fillna(0.0)
    pt["gd"] = pt["gd"].astype(str).str[:10]
    return pt.groupby(["gd", "team", "kname"], as_index=False)[["pot_ast", "reb_ch"]].max()


def alt_rates(d, hlc, pk):
    """Per player-game, from earlier games only: ast and reb per minute rebuilt as chance_rate x steadied_conversion."""
    tr0 = d[(d.season == 2025) & d.has_pt]
    pri = {}
    for p, x in tr0.groupby("pos"):
        m_sum = max(float(x["min"].sum()), 1.0)
        pa_sum = max(float(x["pot_ast"].sum()), 1.0)
        rc_sum = max(float(x["reb_ch"].sum()), 1.0)
        pri[p] = dict(
            v_pa=pa_sum / m_sum,
            c_ast=float(x["ast"].sum()) / pa_sum,
            v_rc=rc_sum / m_sum,
            c_reb=float(x["reb"].sum()) / rc_sum,
        )
    N_PA = 80.0 * pk
    N_RC = 100.0 * pk
    DC = 0.5 ** (1.0 / hlc)
    V = defaultdict(lambda: defaultdict(float))
    C = defaultdict(lambda: defaultdict(float))
    ps, out = {}, []
    cols = ["pid", "pos", "min", "season", "ast", "reb", "pot_ast", "reb_ch", "has_pt"]
    for gid, g in d.groupby("game_id", sort=False):
        rows = g[cols].to_dict("records")
        for r in rows:
            v, c, P = V[r["pid"]], C[r["pid"]], pri[r["pos"]]
            v_pa = (v["pot_ast"] + nba.PM0 * P["v_pa"]) / (v["min"] + nba.PM0)
            c_ast = (c["ast"] + N_PA * P["c_ast"]) / (c["pot_ast"] + N_PA)
            v_rc = (v["reb_ch"] + nba.PM0 * P["v_rc"]) / (v["min"] + nba.PM0)
            c_reb = (c["reb"] + N_RC * P["c_reb"]) / (c["reb_ch"] + N_RC)
            out.append((gid, r["pid"], v_pa * c_ast, v_rc * c_reb))
        for r in rows:
            if not r["has_pt"]:
                continue
            pid = r["pid"]; v, c = V[pid], C[pid]
            if ps.get(pid, r["season"]) != r["season"]:
                for k in list(v): v[k] *= nba.CARRY
                for k in list(c): c[k] *= nba.CARRY
            ps[pid] = r["season"]
            for k in ("pot_ast", "reb_ch", "min"):
                v[k] = v[k] * nba.DR + r[k]
            for k in ("ast", "pot_ast", "reb", "reb_ch"):
                c[k] = c[k] * DC + r[k]
    return pd.DataFrame(out, columns=["game_id", "pid", "ra_ast", "ra_reb"])


def swap(pr, A, w):
    x = pr.merge(A, on=["game_id", "pid"], how="left")
    x["r_ast"] = (1.0 - w[0]) * x.r_ast + w[0] * x.ra_ast.fillna(x.r_ast)
    x["r_reb"] = (1.0 - w[1]) * x.r_reb + w[1] * x.ra_reb.fillna(x.r_reb)
    return x


if __name__ == "__main__":
    d = nba.load()
    pt = load_pt()
    d["kname"] = d["name"].map(norm)
    d["gd10"] = d["gd"].astype(str).str[:10]
    d = d.merge(pt, left_on=["gd10", "team", "kname"], right_on=["gd", "team", "kname"], how="left", suffixes=("", "_pt"))
    d["has_pt"] = d["pot_ast"].notna()
    d["pot_ast"] = d["pot_ast"].fillna(0.0)
    d["reb_ch"] = d["reb_ch"].fillna(0.0)
    print(f"Tracking match rate: {d.has_pt.mean():.1%} overall | by season:", d.groupby("season").has_pt.mean().round(3).to_dict())

    pr, tr, S = nba.walk(d)
    first = pr[pr.season == 2025].gd.min()
    warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
    is_tr, is_te = warm & (pr.season == 2025), pr.season >= 2026
    bm = shot_bt.best_bm(pr, tr, is_tr)
    m0 = shot_bt.fit(pr, tr, is_tr, bm)
    b_tr = nba.project(pr[is_tr], tr, m0)
    b_te = nba.project(pr[is_te], tr, m0)
    print("baseline   fit ast %.4f reb %.4f | test ast %.4f reb %.4f" % (
        shot_bt.mae(b_tr, "ast"), shot_bt.mae(b_tr, "reb"), shot_bt.mae(b_te, "ast"), shot_bt.mae(b_te, "reb")))

    # 1. Tune (hlc, pk) strictly on 2024-25
    res = []
    for hlc, pk in itertools.product((15.0, 40.0, 100.0, 1e9), (0.5, 1.0, 2.0)):
        A = alt_rates(d, hlc, pk)
        x = swap(pr, A, (1.0, 1.0))
        m = shot_bt.fit(x, tr, is_tr, bm)
        dd = nba.project(x[is_tr], tr, m)
        res.append((shot_bt.mae(dd, "ast"), shot_bt.mae(dd, "reb"), hlc, pk))
        print("  hl %-6g prior x%.1f  fit ast %.4f reb %.4f" % (hlc, pk, res[-1][0], res[-1][1]))
    ka = min(res, key=lambda r: r[0])[2:]
    kr = min(res, key=lambda r: r[1])[2:]
    print("chosen on 2024-25: ast", ka, "reb", kr)

    Aa, Ar = alt_rates(d, *ka), alt_rates(d, *kr)
    A = Aa[["game_id", "pid", "ra_ast"]].merge(Ar[["game_id", "pid", "ra_reb"]], on=["game_id", "pid"])

    # 2. Tune blend weight w strictly on 2024-25
    best = {}
    for i, k in ((0, "ast"), (1, "reb")):
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            ww = [0.0, 0.0]; ww[i] = w
            x = swap(pr, A, ww); m = shot_bt.fit(x, tr, is_tr, bm)
            e = shot_bt.mae(nba.project(x[is_tr], tr, m), k)
            print("  %s weight %.2f fit %.4f" % (k, w, e))
            if k not in best or e < best[k][0]:
                best[k] = (e, w)
    w = (best["ast"][1], best["reb"][1])
    print("chosen weights (ast, reb):", w)

    # 3. Score once on held-out 2025-26 and 2026-27
    x = swap(pr, A, w); m1 = shot_bt.fit(x, tr, is_tr, bm); a_te = nba.project(x[is_te], tr, m1)
    rng = np.random.default_rng(7)
    for k in ("ast", "reb", "pra", "pa", "ra"):
        for lab, sm in (("2025-26", b_te.season == 2026), ("2026-27", b_te.season == 2027), ("both", b_te.season >= 2026)):
            mm = (b_te.mn >= 15) & sm
            eb = np.abs(b_te.loc[mm, k] - b_te.loc[mm, "mu_" + k])
            ea = np.abs(a_te.loc[mm, k] - a_te.loc[mm, "mu_" + k])
            g = pd.DataFrame(dict(d=(ea - eb).values, gd=b_te.loc[mm, "gd"].values)).groupby("gd").d.agg(["sum", "count"])
            bs = np.array([g.iloc[rng.integers(0, len(g), len(g))]["sum"].sum() / g.iloc[rng.integers(0, len(g), len(g))]["count"].sum() for _ in range(1)])
            bs = []
            sv, cv = g["sum"].values, g["count"].values
            for _ in range(2000):
                j = rng.integers(0, len(sv), len(sv))
                bs.append(sv[j].sum() / cv[j].sum())
            lo, hi = np.percentile(bs, [2.5, 97.5])
            sh = float((np.array(bs) < 0).mean())
            print("TEST %-4s %-8s n=%6d  base %.4f  pt build %.4f  change %+.2f%%  (95%%: %+.2f%% to %+.2f%%, better %.0f%%)" % (
                k, lab, mm.sum(), eb.mean(), ea.mean(), 100 * (ea.mean() / eb.mean() - 1), 100 * lo / eb.mean(), 100 * hi / eb.mean(), 100 * sh))

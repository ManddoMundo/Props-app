"""Lab, v3.52 (research only; nothing here runs in the daily job):
Tests positional-bucket volume renormalization in nfl.py (so RB carries redistribute inside the RB room
and WR/TE/RB targets redistribute inside their position groups, fixing the ww.py carry/target under-shift).

Charter (locked before scoring):
  - Data: nfl_pw_2023..2026.csv, nfl_games.csv, nfl_snaps_20*.csv.
  - Fit on 2023-24 (after warmup), scored out-of-sample on 2025 and 2026.
  - Baseline: nfl.py global share renormalization (grp.ts.transform('sum')**-beta).
  - Candidate: positional-room renormalization (carries grouped by RB vs non-RB; targets blended between
    positional-room sum and global team sum with weight pos_w tuned on 2023-24).
Run from /home/claude/props/src or lab: python3 nfl_pos_bt.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/claude/props/src")
from collections import defaultdict
import numpy as np, pandas as pd
import nfl


def project_pos(pr, tr, M, P, w_pos_c=1.0, w_pos_t=0.5):
    X = np.c_[np.ones(len(tr)), tr[nfl.TF].values]
    tr = tr.assign(PA=X @ np.array(M["team"]["pa"]), CAR=X @ np.array(M["team"]["car"]),
                   tdadj=(tr.ip / M["lg_ip"]).clip(0.45, 1.8))
    d = pr.merge(tr[["game_id", "team", "PA", "CAR", "padj", "radj", "tdadj"]], on=["game_id", "team"])
    d["c_room"] = np.where(d.pos == "RB", "RB", "OTHER")
    b = M["beta"]

    # Global shares (current nfl.py)
    ts_all = d.groupby(["game_id", "team"]).ts.transform("sum").clip(lower=1e-9)
    cs_all = d.groupby(["game_id", "team"]).cs.transform("sum").clip(lower=1e-9)

    # Positional-room shares (normalized to each room's historical average share)
    room_t_exp = d.pos.map(M["room_t"]).fillna(0.25)
    room_c_exp = d.c_room.map(M["room_c"]).fillna(0.50)
    ts_room = d.groupby(["game_id", "team", "pos"]).ts.transform("sum").clip(lower=1e-9)
    cs_room = d.groupby(["game_id", "team", "c_room"]).cs.transform("sum").clip(lower=1e-9)

    d["tsn"] = (1 - w_pos_t) * (d.ts * ts_all ** (-b)) + w_pos_t * (d.ts * (ts_room / room_t_exp) ** (-b))
    d["csn"] = (1 - w_pos_c) * (d.cs * cs_all ** (-b)) + w_pos_c * (d.cs * (cs_room / room_c_exp) ** (-b))
    d["asn"] = np.minimum(d.as_ / d.groupby(["game_id", "team"]).as_.transform("sum").clip(lower=1e-6), 1.0) * 0.985

    c = M["cal"]
    d["mu_tgt"] = d.PA * P["lg"]["tpa"] * d.tsn
    d["mu_rec"] = d.mu_tgt * d.cr * c["rec"]
    d["mu_rec_yds"] = d.mu_tgt * d.cr * d.ypr * d.padj * c["rec_yds"]
    d["mu_rush_att"] = d.CAR * d.csn * c["rush_att"]; d["f_rush"] = d.mu_rush_att
    d["mu_rush_yds"] = d.CAR * d.csn * d.ypc * d.radj * c["rush_yds"]
    d["mu_pass_att"] = d.PA * d.asn * c["pass_att"]; d["f_pass"] = d.mu_pass_att
    d["mu_pass_cmp"] = d.PA * d.asn * d.cp * c["pass_cmp"]
    d["mu_pass_yds"] = d.PA * d.asn * d.ypa * d.padj * c["pass_yds"]
    d["mu_pass_td"] = d.PA * d.asn * d.ptd * d.tdadj * c["pass_td"]
    d["mu_td"] = (d.mu_tgt * d.rtd + d.CAR * d.csn * d.rutd) * d.tdadj * c["td"]
    for k, (a0, b0) in M.get("lin", {}).items():
        d["mu_" + k] = np.maximum(a0 + b0 * d["mu_" + k], 0.05)
    return d


if __name__ == "__main__":
    pw, g = nfl.load()
    P = nfl.priors(pw)
    pr, tr, S, C = nfl.walk(pw, g, P)
    warm = ~((pr.season == 2023) & (pr.week <= 4))
    twarm = ~((tr.season == 2023) & (tr.week <= 4))
    is_tr = warm & (pr.season <= 2024)
    is_te = pr.season >= 2025

    # Expected positional room share sums fitted on training seasons only
    tr_p = pr[is_tr].copy()
    tr_p["c_room"] = np.where(tr_p.pos == "RB", "RB", "OTHER")
    room_t = tr_p.groupby(["game_id", "team", "pos"]).ts.sum().groupby("pos").mean().to_dict()
    room_c = tr_p.groupby(["game_id", "team", "c_room"]).cs.sum().groupby("c_room").mean().to_dict()
    print("Training room share totals:", {k: round(v, 3) for k, v in room_t.items()}, {k: round(v, 3) for k, v in room_c.items()})

    def fit_cfg(wc, wt):
        m = {"lg_ip": float(tr.ip.mean()), "beta": 0.8, "cal": defaultdict(lambda: 1.0),
             "team": nfl.fit_team(tr[twarm & (tr.season <= 2024)]), "room_t": room_t, "room_c": room_c}
        d = project_pos(pr[is_tr], tr, m, P, wc, wt)
        cal = {k: float(d.loc[d[fcol] >= mn, col].sum() / d.loc[d[fcol] >= mn, "mu_" + k].sum()) for k, (col, fcol, mn) in nfl.STATS.items()}
        mm = (d.mu_tgt >= 2.5) | (d.f_rush >= 4)
        cal["td"] = float((d.loc[mm, "receiving_tds"] + d.loc[mm, "rushing_tds"]).sum() / d.loc[mm, "mu_td"].sum())
        m["cal"] = cal
        d = project_pos(pr[is_tr], tr, m, P, wc, wt)
        m["lin"] = {k: [float(v) for v in np.polyfit(d.loc[d[fcol] >= mn, "mu_" + k], d.loc[d[fcol] >= mn, col], 1)[::-1]]
                    for k, (col, fcol, mn) in nfl.STATS.items()}
        return m

    best = None
    for wc in (0.0, 0.25, 0.5, 0.75, 1.0):
        for wt in (0.0, 0.25, 0.5, 0.75, 1.0):
            m = fit_cfg(wc, wt)
            d = project_pos(pr[is_tr], tr, m, P, wc, wt)
            e = np.abs(d.loc[d.mu_tgt >= 2.5, "receiving_yards"] - d.loc[d.mu_tgt >= 2.5, "mu_rec_yds"]).mean() + \
                np.abs(d.loc[d.f_rush >= 4, "rushing_yards"] - d.loc[d.f_rush >= 4, "mu_rush_yds"]).mean()
            if best is None or e < best[0]:
                best = (e, wc, wt)
    _, wc, wt = best
    print(f"Chosen on 2023-24: w_pos_c={wc}, w_pos_t={wt}")

    m0, m1 = fit_cfg(0.0, 0.0), fit_cfg(wc, wt)
    te0, te1 = project_pos(pr[is_te], tr, m0, P, 0.0, 0.0), project_pos(pr[is_te], tr, m1, P, wc, wt)
    for lab, fold in (("TEST 2025", te0.season == 2025), ("TEST 2026", te0.season == 2026)):
        print(f"\n{lab} MAE (baseline -> positional-room):")
        for k in ("rec", "rec_yds", "rush_att", "rush_yds"):
            col, fcol, mn = nfl.STATS[k]
            mm = (te0[fcol] >= mn) & fold
            e0 = np.abs(te0.loc[mm, col] - te0.loc[mm, "mu_" + k]).values
            e1 = np.abs(te1.loc[mm, col] - te1.loc[mm, "mu_" + k]).values
            g = te0.loc[mm, "game_id"].values; ug = np.unique(g); idx = {u: np.where(g == u)[0] for u in ug}; rng = np.random.default_rng(7)
            bs = [(e1 - e0)[np.concatenate([idx[u] for u in rng.choice(ug, len(ug))])].mean() for _ in range(500)]
            print(f"  {k:<10} n={int(mm.sum()):5d}  {e0.mean():.4f} -> {e1.mean():.4f}  ({100*(e1.mean()/e0.mean() - 1):+.2f}%, better in {np.mean(np.array(bs) < 0):.0%} of game resamples)")
    print("production beta in nfl.py is fitted on the same seasons; this script fixes it at 0.8. nfl.py prints the fitted value.")

#!/usr/bin/env python3
"""Lab research script (nothing here runs in the daily job):
Walk-forward test of decomposing NFL receiving target share into offensive snap participation (fast memory,
HL=3) times targets per offensive snap (slow memory, HL=10, positional prior), using the nfl_snaps_20*.csv
files run.sh already downloads.

Charter (locked before scoring):
  - Fit on 2023-24 after week-4 warmup (selects blend weight w_snap).
  - Scored separately on 2025 and 2026, broken out by ALL, WR, TE, and RB, with 2,000 paired game-week bootstrap draws.
  - Note: aDOT + YAC efficiency decomposition was also tested and rejected (+0.14% / +0.05% worse MAE), so only
    Snap Share x Targets Per Snap is included here.

Run: python3 nfl_snap_bt.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/claude/props/src")
from collections import defaultdict
import numpy as np, pandas as pd
import nfl, common

D = "/home/claude/props/data/"


def load_with_snaps():
    pw, g = nfl.load()
    pw["kname"] = pw.player_display_name.map(common.norm)
    sn = pd.concat([pd.read_csv(f"{D}nfl_snaps_{y}.csv", low_memory=False) for y in (2023, 2024, 2025, 2026)])
    sn = sn[sn.position.isin(["QB", "RB", "WR", "TE", "FB"]) & (sn.offense_snaps > 0) & sn.game_type.isin(["REG", "WC", "DIV", "CON", "SB"])].copy()
    # Prefer gsis_id join via nfl_players.parquet when available; fall back to (game_id, team, norm(name))
    try:
        ids = pd.read_parquet(D + "nfl_players.parquet", columns=["gsis_id", "pfr_id"]).dropna()
        mp = dict(zip(ids.pfr_id, ids.gsis_id))
        sn["player_id"] = sn["pfr_player_id"].map(mp)
        sn_id = sn.dropna(subset=["player_id"]).groupby(["game_id", "player_id"])[["offense_snaps", "offense_pct"]].max().reset_index()
        pw = pw.merge(sn_id, on=["game_id", "player_id"], how="left")
    except Exception:
        sn["kname"] = sn.player.map(common.norm)
        sn_nm = sn.groupby(["game_id", "team", "kname"])[["offense_snaps", "offense_pct"]].max().reset_index()
        pw = pw.merge(sn_nm, on=["game_id", "team", "kname"], how="left")
    pw["offense_snaps"] = pw["offense_snaps"].fillna(0.0)
    pw["offense_pct"] = pw["offense_pct"].fillna(0.0)
    return pw, g


def walk_snap_ts(pw, g, hl_pct=3.0, hl_tprs=10.0, n0_tprs=100.0):
    tr0 = pw[pw.season <= 2024]
    pri = {pos: dict(pct=float(x.offense_pct.mean()), tprs=float(x.targets.sum() / max(x.offense_snaps.sum(), 1.0)))
           for pos, x in tr0.groupby("pos")}
    dp = 0.5 ** (1.0 / hl_pct); dt = 0.5 ** (1.0 / hl_tprs)
    done = g[g.home_score.notna()].sort_values(["gameday", "game_id"])
    byg = {k: v for k, v in pw.groupby(["game_id", "team"])}
    st = defaultdict(lambda: defaultdict(float)); ps = {}; out = []
    for r in done.itertuples():
        pend = []
        for t in (r.home_team, r.away_team):
            d = byg.get((r.game_id, t))
            if d is None: continue
            rows = d.to_dict("records")
            tm_sn = max(max((x["offense_snaps"] for x in rows), default=0.0), 1.0)
            tm_tg = max(sum(x["targets"] for x in rows), 1.0)
            for x in rows:
                pid = x["player_id"]; s = st[pid]; pp = pri[x["pos"]]
                pct_hat = (s["pct"] + 0.5 * pp["pct"]) / (s["wp"] + 0.5)
                tprs_hat = (s["tgt"] + n0_tprs * pp["tprs"]) / (s["sn"] + n0_tprs)
                ts_snap = pct_hat * tprs_hat * (s["tsn"] + 65.0) / max(s["ttg"] + 33.0, 1.0)
                out.append((r.game_id, pid, ts_snap))
            pend.append((rows, tm_sn, tm_tg))
        for rows, tm_sn, tm_tg in pend:
            for x in rows:
                pid = x["player_id"]; s = st[pid]
                if ps.get(pid, r.season) != r.season:
                    s["pct"] *= 0.5; s["wp"] *= 0.5
                    for k in ("tgt", "sn", "tsn", "ttg"): s[k] *= 0.8
                ps[pid] = r.season
                s["pct"] = s["pct"] * dp + x["offense_pct"]; s["wp"] = s["wp"] * dp + 1.0
                s["tgt"] = s["tgt"] * dt + x["targets"]; s["sn"] = s["sn"] * dt + x["offense_snaps"]
                s["tsn"] = s["tsn"] * dt + tm_sn; s["ttg"] = s["ttg"] * dt + tm_tg
    return pd.DataFrame(out, columns=["game_id", "player_id", "ts_snap"])


def boot_diff(e0, e1, wks):
    rng = np.random.default_rng(7)
    df = pd.DataFrame({"d": e1 - e0, "w": wks}).groupby("w").d.agg(["sum", "count"])
    s, c = df["sum"].values, df["count"].values
    bs = np.array([s[j].sum() / c[j].sum() for j in (rng.integers(0, len(s), len(s)) for _ in range(2000))])
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), float((bs < 0).mean())


if __name__ == "__main__":
    pw, g = load_with_snaps()
    P = nfl.priors(pw)
    pr, tr, _, _ = nfl.walk(pw, g, P)
    ex = walk_snap_ts(pw, g)
    pr2 = pr.merge(ex, on=["game_id", "player_id"], how="left")
    warm = ~((pr2.season == 2023) & (pr2.week <= 4))
    twarm = ~((tr.season == 2023) & (tr.week <= 4))
    is_tr = warm & (pr2.season <= 2024)

    def run_w(w_snap):
        p_use = pr2.copy()
        p_use["ts"] = (1.0 - w_snap) * p_use["ts"] + w_snap * p_use["ts_snap"].fillna(p_use["ts"])
        M = {"lg_ip": float(tr[twarm & (tr.season <= 2024)].ip.mean()), "beta": 0.8, "cal": defaultdict(lambda: 1.0)}
        M["team"] = nfl.fit_team(tr[twarm & (tr.season <= 2024)])
        d = nfl.project(p_use[is_tr], tr, M, P)
        cal = {k: float(d.loc[d[fcol] >= mn, col].sum() / d.loc[d[fcol] >= mn, "mu_" + k].sum()) for k, (col, fcol, mn) in nfl.STATS.items()}
        mm = (d.mu_tgt >= 2.5) | (d.f_rush >= 4)
        cal["td"] = float((d.loc[mm, "receiving_tds"] + d.loc[mm, "rushing_tds"]).sum() / d.loc[mm, "mu_td"].sum())
        M["cal"] = cal
        d = nfl.project(p_use[is_tr], tr, M, P)
        M["lin"] = {k: [float(v) for v in np.polyfit(d.loc[d[fcol] >= mn, "mu_" + k], d.loc[d[fcol] >= mn, col], 1)[::-1]]
                    for k, (col, fcol, mn) in nfl.STATS.items()}
        return nfl.project(p_use[is_tr], tr, M, P), nfl.project(p_use[p_use.season >= 2025], tr, M, P)

    best = None
    print("=== Fit on 2023-24 ===")
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        tr_d, _ = run_w(w)
        mm = tr_d.mu_tgt >= 2.5
        er = np.abs(tr_d.loc[mm, "receptions"] - tr_d.loc[mm, "mu_rec"]).mean()
        ey = np.abs(tr_d.loc[mm, "receiving_yards"] - tr_d.loc[mm, "mu_rec_yds"]).mean()
        print(f"  w={w:.2f}  rec MAE {er:.4f}  rec_yds MAE {ey:.4f}")
        if best is None or ey < best[0]:
            best = (ey, w)
    print(f"Best on 2023-24 by rec_yds MAE: w={best[1]:.2f} (also reporting w=0.50 out-of-sample)")

    _, te0 = run_w(0.0)
    for w_test in sorted({0.5, best[1]}):
        _, te1 = run_w(w_test)
        print(f"\n=== Out-of-Sample Test (w_snap={w_test:.2f}) ===")
        for seas in (2025, 2026):
            m0 = (te0.season == seas) & (te0.mu_tgt >= 2.5)
            for plab, pm in [("ALL", te0.pos.isin(["WR", "TE", "RB"])), ("WR", te0.pos == "WR"), ("TE", te0.pos == "TE"), ("RB", te0.pos == "RB")]:
                mm = m0 & pm
                wks = (te0.loc[mm, "season"].astype(str) + "_" + te0.loc[mm, "week"].astype(str)).values
                for k, col in (("rec", "receptions"), ("rec_yds", "receiving_yards")):
                    e0 = np.abs(te0.loc[mm, col] - te0.loc[mm, "mu_" + k]).values
                    e1 = np.abs(te1.loc[mm, col] - te1.loc[mm, "mu_" + k]).values
                    lo, hi, sh = boot_diff(e0, e1, wks)
                    print(f"  {seas} {plab:<3} {k:<7} n={int(mm.sum()):4d}  {e0.mean():.4f} -> {e1.mean():.4f} ({100*(e1.mean()/e0.mean()-1):+.2f}%, 95% {lo:+.4f}..{hi:+.4f}, better {sh:.0%})")

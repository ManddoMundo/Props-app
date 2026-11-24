"""Lab, v3.53 (research). Carries shared inside the running back room: which form, and where does it help.
  base      nfl.py v3.52: carry share x (team sum of shares)^-beta
  both      RB room and everyone-else room each scaled to its own usual total (the v3.52 lab candidate)
  rb_only   only running backs use their room; everyone else keeps the team-wide sum
Fit on 2023-24, scored on 2025 and 2026 apart. Run: python3 nfl_room_bt.py"""
import sys
sys.path.insert(0, "/home/claude/props/src")
from collections import defaultdict
import numpy as np, pandas as pd
import nfl

def project(pr, tr, M, P, mode):
    d = nfl.project(pr, tr, dict(M, lin={}), P)
    if mode != "base":
        b = M["beta"]; rb = d.pos == "RB"
        room = np.where(rb, "RB", "OTHER")
        s_room = d.groupby(["game_id", "team", pd.Series(room, index=d.index)]).cs.transform("sum").clip(lower=1e-9)
        exp = pd.Series(room, index=d.index).map(M["room_c"])
        csn_room = d.cs * (s_room / exp) ** (-b)
        csn = csn_room if mode == "both" else np.where(rb, csn_room, d.csn)
        c = M["cal"]; d["csn"] = csn
        d["mu_rush_att"] = d.CAR * d.csn * c["rush_att"]; d["f_rush"] = d.mu_rush_att
        d["mu_rush_yds"] = d.CAR * d.csn * d.ypc * d.radj * c["rush_yds"]
        d["mu_td"] = (d.mu_tgt * d.rtd + d.CAR * d.csn * d.rutd) * d.tdadj * c["td"]
    d["rb_sum"] = d.assign(x=np.where(d.pos == "RB", d.cs, 0.0)).groupby(["game_id", "team"]).x.transform("sum")
    for k, (a0, b0) in M.get("lin", {}).items():
        d["mu_" + k] = np.maximum(a0 + b0 * d["mu_" + k], 0.05)
    return d

pw, g = nfl.load(); P = nfl.priors(pw); pr, tr, S, C = nfl.walk(pw, g, P)
warm = ~((pr.season == 2023) & (pr.week <= 4)); twarm = ~((tr.season == 2023) & (tr.week <= 4)); is_tr = warm & (pr.season <= 2024)
t = pr[is_tr].assign(room=np.where(pr[is_tr].pos == "RB", "RB", "OTHER"))
room_c = t.groupby(["game_id", "team", "room"]).cs.sum().groupby("room").mean().to_dict(); print("usual room totals", {k: round(v, 3) for k, v in room_c.items()})
def fit(mode):
    m = {"lg_ip": float(tr.ip.mean()), "beta": 0.8, "cal": defaultdict(lambda: 1.0), "team": nfl.fit_team(tr[twarm & (tr.season <= 2024)]), "room_c": room_c}
    d = project(pr[is_tr], tr, m, P, mode)
    cal = {k: float(d.loc[d[f] >= mn, col].sum() / d.loc[d[f] >= mn, "mu_" + k].sum()) for k, (col, f, mn) in nfl.STATS.items()}
    mm = (d.mu_tgt >= 2.5) | (d.f_rush >= 4); cal["td"] = float((d.loc[mm, "receiving_tds"] + d.loc[mm, "rushing_tds"]).sum() / d.loc[mm, "mu_td"].sum()); m["cal"] = cal
    d = project(pr[is_tr], tr, m, P, mode)
    m["lin"] = {k: [float(v) for v in np.polyfit(d.loc[d[f] >= mn, "mu_" + k], d.loc[d[f] >= mn, col], 1)[::-1]] for k, (col, f, mn) in nfl.STATS.items()}
    return m
T = {m: project(pr[pr.season >= 2025], tr, fit(m), P, m) for m in ("base", "both", "rb_only")}
b0 = T["base"]; rng = np.random.default_rng(7)
def row(label, mask, k):
    col = nfl.STATS[k][0]; n = int(mask.sum())
    if n < 60: return
    e0 = np.abs(b0.loc[mask, col] - b0.loc[mask, "mu_" + k]).values; s = f"  {label:<34} {k:<8} n {n:5d}  base {e0.mean():7.3f}"
    gid = b0.loc[mask, "game_id"].values; ug = np.unique(gid); idx = {u: np.where(gid == u)[0] for u in ug}
    for m in ("both", "rb_only"):
        e1 = np.abs(T[m].loc[mask, col] - T[m].loc[mask, "mu_" + k]).values
        bs = [(e1 - e0)[np.concatenate([idx[u] for u in rng.choice(ug, len(ug))])].mean() for _ in range(400)]
        s += f" | {m} {100 * (e1.mean() / e0.mean() - 1):+6.2f}% ({np.mean(np.array(bs) < 0):.0%})"
    print(s)
for se in (2025, 2026):
    print(f"\nTEST {se} (change in average miss; in brackets, share of game resamples where it is better)")
    f = b0.season == se; vol = b0.f_rush >= 4
    for k in ("rush_att", "rush_yds"):
        row("all with 4+ projected carries", f & vol, k)
        row("  running backs", f & vol & (b0.pos == "RB"), k)
        row("  quarterbacks", f & vol & (b0.pos == "QB"), k)
        row("RB room short (sum under 0.60)", f & vol & (b0.pos == "RB") & (b0.rb_sum < 0.60), k)
        row("RB room full (0.60 and up)", f & vol & (b0.pos == "RB") & (b0.rb_sum >= 0.60), k)
        row("quarterbacks, any volume", f & (b0.pos == "QB") & (b0.f_pass >= 15), k)
    q = f & (b0.pos == "QB") & (b0.f_pass >= 15)
    print("  QB projected carries, mean: base", round(float(b0.loc[q, 'mu_rush_att'].mean()), 2), "both", round(float(T['both'].loc[q, 'mu_rush_att'].mean()), 2), "rb_only", round(float(T['rb_only'].loc[q, 'mu_rush_att'].mean()), 2), "actual", round(float(b0.loc[q, 'carries'].mean()), 2))

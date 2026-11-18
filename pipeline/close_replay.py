# Research tool (v3.21 closing-line test). Run from /home/claude/props/lab with the decrypted history files in /home/claude/hist/txt (history.yml pulls them).
"""Q1 significance (paired bootstrap by game) and Q2, the desk's pick rules replayed at Hard Rock's closing prices."""
import sys, math
sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
import close_bt as C
R = pd.read_pickle("close_scored.pkl"); R = R[R.p_mkt.notna()].copy()
L = lambda p, y: -(y * np.log(np.clip(p, .001, .999)) + (1 - y) * np.log(1 - np.clip(p, .001, .999)))
rng = np.random.default_rng(7)
print("Q1 significance: desk minus Hard Rock log loss, per prop; negative = desk better. 2,000 resamples of whole games.")
for tag in ("live", "prior"):
    for lg in ("NBA", "NFL", "ALL"):
        z = R if lg == "ALL" else R[R.lg == lg]
        d = (L(z["p_desk_" + tag], z.over) - L(z.p_hr, z.over)).values; g = z.game.values; ug = np.unique(g)
        idx = {k: np.where(g == k)[0] for k in ug}; s = [d[np.concatenate([idx[k] for k in rng.choice(ug, len(ug))])].mean() for _ in range(2000)]
        print(f"  w={tag:5s} {lg}: {d.mean():+.5f} ({d.mean() / L(z.p_hr, z.over).mean() * 100:+.2f}%), 90% range {np.percentile(s, 5):+.5f} to {np.percentile(s, 95):+.5f}, share of resamples where desk is better {np.mean(np.array(s) < 0):.0%}")

# ---- Q2: price both sides at Hard Rock, as daily.py price_all, then eligible() and cmd_pick()
sides = []
for r in R.itertuples():
    for side, odds in (("Over", r.o), ("Under", r.u)):
        pw = r.p_desk_live if side == "Over" else 1 - r.p_desk_live
        pwc = r.p_modc if side == "Over" else 1 - r.p_modc
        be = 1 / C.dec(odds); edge = pw - be; ev = pw * (C.dec(odds) - 1) - (1 - pw); edgec = pwc - be
        c = 1.0; n = r.n_prev if not pd.isna(r.n_prev) else 0
        if n < 5: c *= .7
        elif n < 10: c *= .85
        if r.lg == "NBA" and not pd.isna(r.cvmin) and r.cvmin > .22: c *= .88
        if r.lg == "NFL" and r.spread is not None and not pd.isna(r.spread) and abs(r.spread) >= 9.5: c *= .92
        if r.mu < 2: c *= .92
        if edge >= .10: c *= .85
        win = (r.over == 1) if side == "Over" else (r.over == 0)
        sides.append(dict(lg=r.lg, date=r.date, game=r.game, key=r.key, name=r.name, mkt=r.mkt, side=side, line=r.line, odds=odds, edge=edge, edgec=edgec,
                          ev=ev, adj=ev * (c if ev > 0 else 1), nb=r.nb, n=n, mn=r.mn, win=win, pnl=(C.dec(odds) - 1) if win else -1.0))
S = pd.DataFrame(sides)
def ok(b):
    if b.mkt not in C.CFG["pick_markets"][b.lg]: return False
    if not (C.CFG["min_odds"] <= b.odds <= C.CFG["max_odds"]): return False
    if b.n < C.CFG["min_games"]: return False
    if b.lg == "NBA" and (b.mn or 0) < C.CFG["nba_min_minutes"]: return False
    if b.nb < C.CFG["min_books"] or b.edgec > C.CFG["max_edge"]: return False
    return C.CFG["min_edge"] <= b.edge <= C.CFG["max_edge"] and b.adj >= C.CFG["min_adj_ev"]
S["elig"] = [ok(b) for b in S.itertuples()]
picks = []
for (lg, date), z in S[S.elig].sort_values("adj", ascending=False).groupby(["lg", "date"], sort=False):
    seen, pg, k = set(), {}, 0
    for b in z.itertuples():
        if b.key in seen or pg.get(b.game, 0) >= C.CFG["max_per_game"]: continue
        seen.add(b.key); pg[b.game] = pg.get(b.game, 0) + 1; picks.append(b._asdict()); k += 1
        if k == C.CFG["max_picks"]: break
P = pd.DataFrame(picks)
def line(z, lab):
    n = len(z); w = int(z.win.sum()); u = z.pnl.sum()
    return f"  {lab:34s} {n:5d} bets  {w}-{n - w}  hit {w / max(n, 1):.1%}  units {u:+.1f}  ROI {u / max(n, 1) * 100:+.1f}%"
print("\nQ2. The desk's rules replayed at Hard Rock's closing prices (flat one unit a bet)")
print(line(P, "Picks (3 a day per league)"))
for lg in ("NBA", "NFL"): print(line(P[P.lg == lg], f"  {lg}"))
for m, z in P.groupby("mkt"): print(line(z, f"    {m}"))
print(line(S[S.elig], "Every side that cleared the bar"))
print("\nDoes a bigger edge win more? Every side in the pick markets, by the desk's edge at Hard Rock's price:")
Z = S[np.array([m in C.CFG["pick_markets"][l] for l, m in zip(S.lg, S.mkt)]) & S.odds.between(-160, 150).values]
for lo, hi in ((-1, 0), (0, .02), (.02, .03), (.03, .05), (.05, .08), (.08, .12), (.12, 1)):
    print(line(Z[(Z.edge >= lo) & (Z.edge < hi)], f"edge {lo * 100:+.0f} to {hi * 100:+.0f} pts"))
P.to_pickle("close_picks.pkl"); S.to_pickle("close_sides.pkl")

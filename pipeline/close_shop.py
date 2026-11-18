# Research tool (v3.22 best-of-books replay). Run from /home/claude/props/lab after close_bt.py and close_score.py.
"""Best-of-books replay (research). Charter, fixed before scoring: same closing lines, projections and results as close_bt.py.
Market view = median implied mean across every book quoting the player (sane quotes only: the two sides' implied chances add
to 1.00 to 1.12). Each side is priced at every book's own line and price with the desk's blend; the side is bet where the desk's
expected value is highest ("best book"), against the Hard Rock-only desk. The desk rules are daily.py's (eligible, 3 picks a day
a league, 2 a game, 1 a player); the model-alone hold is tried at 12 points (today's rule), 25 points, and off. Flat one unit."""
import numpy as np, pandas as pd, close_bt as C, glob, os
R = pd.read_pickle("close_scored.pkl"); R = R[R.mm.notna()].copy()
# every book's quote for the matched props
rows = []
for f in sorted(glob.glob(C.H + "*.txt")):
    lg = os.path.basename(f)[:3]; tip = None
    for ln in open(f):
        if ln.startswith("# tip:"): tip = ln[6:].strip()[:10]; continue
        if ln.startswith("#") or ln.startswith("bookmaker"): continue
        b, m, p, l, o, u = ln.rstrip("\n").split("|")
        if m in C.MAPK and l and o and u: rows.append((lg, tip, C.norm(p), C.MAPK[m], b, float(l), int(o), int(u)))
Q = pd.DataFrame(rows, columns=["lg", "date", "key", "mkt", "book", "line", "o", "u"])
Q["hold"] = 1 / Q.o.map(C.dec) + 1 / Q.u.map(C.dec); Q = Q[Q.hold.between(1.0, 1.12)]
Q = Q.merge(R[["lg", "date", "key", "mkt"]].reset_index(), on=["lg", "date", "key", "mkt"])
# market view from all books (median implied mean), centring per slate, the desk's blend
Q["imp"] = [C.imean(r.lg, r.mkt, r.line, (1 / C.dec(r.o)) / r.hold) for r in Q.itertuples()]
mm_all = Q.groupby("index").imp.median(); nb_all = Q.groupby("index").size()
R["mm_all"] = mm_all; R["nb_all"] = nb_all
R = R[R.mm_all.notna()]
cen = {}
for (lg, date, mkt), z in R.groupby(["lg", "date", "mkt"]):
    g = z[z.nb_all >= 3]; g = g if len(g) else z; n = len(g); r = g.mm_all.sum() / g.mu.sum()
    cen[(lg, date, mkt)] = float(np.clip((n * r + C.CFG["cal_c_n0"]) / (n + C.CFG["cal_c_n0"]), .85, 1.15))
R["c2"] = [cen[(r.lg, r.date, r.mkt)] for r in R.itertuples()]
R["muf2"] = [r.mm_all + r.w_live * (r.c2 * r.mu - r.mm_all) for r in R.itertuples()]
Q = Q.merge(R[["muf2", "c2", "mu", "y", "n_prev", "mn", "cvmin", "spread", "game", "name", "w_live", "nb_all"]], left_on="index", right_index=True)
sides = []
for r in Q.itertuples():
    po = C.pov(r.lg, r.mkt, r.muf2, r.line); pc = C.pov(r.lg, r.mkt, r.c2 * r.mu, r.line)
    for side, odds, pw, pwc in (("Over", r.o, po, pc), ("Under", r.u, 1 - po, 1 - pc)):
        if r.y == r.line: continue
        be = 1 / C.dec(odds); ev = pw * (C.dec(odds) - 1) - (1 - pw)
        c = 1.0; n = 0 if pd.isna(r.n_prev) else r.n_prev
        c *= .7 if n < 5 else .85 if n < 10 else 1
        if r.lg == "NBA" and not pd.isna(r.cvmin) and r.cvmin > .22: c *= .88
        if r.lg == "NFL" and not pd.isna(r.spread) and abs(r.spread) >= 9.5: c *= .92
        if r.mu < 2: c *= .92
        if pw - be >= .10: c *= .85
        win = (r.y > r.line) if side == "Over" else (r.y < r.line)
        sides.append(dict(idx=r.index, lg=r.lg, date=r.date, game=r.game, key=r.key, mkt=r.mkt, side=side, book=r.book, line=r.line, odds=odds,
                          edge=pw - be, edgec=pwc - be, ev=ev, adj=ev * (c if ev > 0 else 1), n=n, mn=r.mn, nb=r.nb_all - 1, win=win, pnl=(C.dec(odds) - 1) if win else -1.0))
S = pd.DataFrame(sides); S.to_pickle("shop_sides.pkl"); R.to_pickle("shop_rows.pkl")
print("quotes kept", len(Q), "| sides priced at every book", len(S))

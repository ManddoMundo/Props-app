# Research tool (v3.22 best-of-books replay). Run from /home/claude/props/lab after close_bt.py and close_score.py.
import numpy as np, pandas as pd, close_bt as C
S = pd.read_pickle("shop_sides.pkl")
PM = C.CFG["pick_markets"]
def elig(z, hold):
    m = np.array([k in PM[l] for l, k in zip(z.lg, z.mkt)]) & z.odds.between(-160, 150).values & (z.n >= 8).values & (z.nb >= 2).values
    m &= ((z.lg != "NBA") | (z.mn.fillna(0) >= 20)).values & z.edge.between(.03, .12).values & (z.adj >= .025).values
    if hold is not None: m &= (z.edgec <= hold).values if not isinstance(hold, dict) else np.array([e <= hold[l] for e, l in zip(z.edgec, z.lg)])
    return z[m]
def best_side(z):        # one quote per prop and side: the book with the highest expected value
    return z.sort_values("ev", ascending=False).drop_duplicates(["idx", "side"])
def picks(z):
    out = []
    for (lg, date), d in z.sort_values("adj", ascending=False).groupby(["lg", "date"], sort=False):
        seen, pg = set(), {}
        for b in d.itertuples():
            if b.key in seen or pg.get(b.game, 0) >= 2: continue
            seen.add(b.key); pg[b.game] = pg.get(b.game, 0) + 1; out.append(b._asdict())
            if sum(1 for x in out if x["lg"] == lg and x["date"] == date) == 3: break
    return pd.DataFrame(out)
rng = np.random.default_rng(3)
def show(z, lab):
    if not len(z): print(f"  {lab:44s}     0"); return
    n = len(z); w = int(z.win.sum()); u = z.pnl.sum(); g = z.game.values; ug = np.unique(g); ix = {k: np.where(g == k)[0] for k in ug}; p = z.pnl.values
    bs = [p[np.concatenate([ix[k] for k in rng.choice(ug, len(ug))])].mean() for _ in range(1000)]
    print(f"  {lab:44s} {n:5d}  {w}-{n - w}  hit {w / n:.1%}  units {u:+6.1f}  ROI {u / n * 100:+5.1f}%  (90% range {np.percentile(bs, 5) * 100:+.1f} to {np.percentile(bs, 95) * 100:+.1f}, chance it is above zero {np.mean(np.array(bs) > 0):.0%})")
HR = S[S.book == "hardrockbet"]; BEST = best_side(S)
for lab, src in (("Hard Rock only", HR), ("Best of seven books", BEST)):
    print(f"\n{lab}")
    for hl, hold in (("hold 12 (today)", .12), ("hold 25 NBA, 12 NFL", {"NBA": .25, "NFL": .12}), ("hold 25 both", .25), ("no hold", None)):
        E = elig(src, hold); P = picks(E)
        show(P, f"picks, {hl}"); show(E, f"every side that cleared, {hl}")
        for lg in ("NBA", "NFL"): show(E[E.lg == lg], f"   {lg}")
print("\nWhere the best price came from (best-of-seven, no hold, sides that cleared):")
E = elig(BEST, None); print(E.book.value_counts().to_dict())
print("Average price gain over Hard Rock on the same sides (cents of payout per $1):", round(float((BEST.set_index(['idx','side']).odds.map(C.dec) - HR.set_index(['idx','side']).odds.map(C.dec)).dropna().mean() * 100), 2))

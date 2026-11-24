"""Lab, 2026-11-20 (research; nothing here runs in the daily job): the shot build (v3.50) scored against real closing prices.
Charter, fixed before scoring:
Lines: the books' closing NBA player props, one snapshot ten minutes before each game, Oct 22 to Nov 16 2026 (the Nov 18
history pull, decrypted to /home/claude/hist/txt). Universe: every player and market Hard Rock quoted, matched to one
walk-forward projection and the player's result; pushes out. Both builds are fitted on games before the 2026-27 season only.
Question 1: log loss of the over at Hard Rock's line (lower is better) for Hard Rock's no-vig price, the model alone and the
desk's blend (market + 0.25 x (centred model - market), the market being the median of the other books), old build against
new. Difference judged by a paired resample of games (2,000 draws).
Question 2: sides with a blended edge of 3 to 12 points at Hard Rock's price, flat one unit: record and return, old against new.
Rebounds and assists are a control: the shot build does not touch them, so they must come out identical.
Limits: closing lines are tougher than the late-morning lines the desk bets; these projections know who played but nothing
else about the day's news; four weeks of one season."""
import sys, os, re, glob, math, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from scipy import stats
from common import nb_k, fit_dispersion
import nba, shot_bt
H = "/home/claude/hist/txt/"
MAPK = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3"}
W0, C_N0 = 0.25, 5


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'\\-]", " ", s); s = re.sub(r"\\b(jr|sr|ii|iii|iv|v)\\b", " ", s)
    return " ".join(s.split())


def dec(a): return 1 + (a / 100 if a > 0 else 100 / -a)


def pov(disp, mu, line):
    a, b = disp; mu = max(mu, .01); k = float(nb_k(np.array([mu]), a, b)[0]); pr = k / (k + mu)
    un = stats.nbinom.cdf(math.ceil(line) - 1, k, pr); push = stats.nbinom.pmf(int(line), k, pr) if float(line).is_integer() else 0
    o = 1 - un - push; return o / (o + un)


def imean(disp, line, p):
    lo, hi = .02, max(6 * line + 20, 10)
    for _ in range(36):
        mid = (lo + hi) / 2
        if pov(disp, mid, line) < p: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def build(on):
    """walk-forward projections for 2026-27, fitted on the games before it"""
    nba.SHOT_ON = on
    d = nba.load(); pr, tr, S = nba.walk(d)
    first = pr[pr.season == 2025].gd.min(); warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
    fitm = warm & (pr.season <= 2026)
    m = shot_bt.fit(pr, tr, fitm, shot_bt.best_bm(pr, tr, fitm))
    dd = nba.project(pr[fitm], tr, m); mm = dd.mn >= 15
    disp = {k: fit_dispersion(dd.loc[mm, "mu_" + k], dd.loc[mm, k]) for k in nba.BASE}
    te = nba.project(pr[pr.season == 2027], tr, m); te["key"] = te.name.map(norm); te["date"] = te.gd.astype(str)
    return te, disp


if __name__ == "__main__":
    rows = []
    for f in sorted(glob.glob(H + "NBA_*.txt")):
        gl = tip = None
        for ln in open(f):
            if ln.startswith("# game:"): gl = ln[7:].strip(); continue
            if ln.startswith("# tip:"): tip = ln[6:].strip()[:10]; continue
            if ln.startswith("#") or ln.startswith("bookmaker"): continue
            b, m, p, l, o, u = ln.rstrip("\n").split("|")
            if m not in MAPK or not l or not o or not u: continue
            rows.append(dict(date=tip, gl=gl, book=b, mkt=MAPK[m], name=p, key=norm(p), line=float(l), o=int(o), u=int(u)))
    Lq = pd.DataFrame(rows); print("closing quotes", len(Lq), "days", Lq.date.nunique())
    T0, D0 = build(False); T1, D1 = build(True)
    assert (T0.pid.values == T1.pid.values).all() and (T0.game_id.values == T1.game_id.values).all()
    for k in ("reb", "ast"): assert np.allclose(T0["mu_" + k], T1["mu_" + k]), k
    print("control: rebounds and assists projections are identical in both builds")
    # ESPN dates are UTC-based for late games: match on the tip date or the day after
    idx = {}
    for i, (dt, key) in enumerate(zip(T0.date, T0.key)): idx.setdefault((dt, key), []).append(i)
    out = []
    for (date, key, mkt), q in Lq.groupby(["date", "key", "mkt"]):
        hr = q[q.book == "hardrockbet"]
        if hr.empty: continue
        hr = hr.iloc[0]
        c = idx.get((date, key), []) or idx.get((str(pd.Timestamp(date) + pd.Timedelta(days=1))[:10], key), [])
        if len(c) != 1: continue
        i = c[0]; y = float(T0[mkt].iloc[i]); line = hr.line
        if y == line: continue
        po, pu = 1 / dec(hr.o), 1 / dec(hr.u)
        oth = [imean(D0[mkt], r.line, (1 / dec(r.o)) / (1 / dec(r.o) + 1 / dec(r.u))) for r in q[q.book != "hardrockbet"].itertuples()]
        out.append(dict(date=date, game=str(T0.game_id.iloc[i]), key=key, mkt=mkt, line=line, o=int(hr.o), u=int(hr.u), over=float(y > line), p_hr=po / (po + pu),
                        mm=float(np.median(oth)) if oth else np.nan, nb=len(oth), mu0=float(T0["mu_" + mkt].iloc[i]), mu1=float(T1["mu_" + mkt].iloc[i]), mn=float(T0.mn.iloc[i])))
    R = pd.DataFrame(out); print("matched Hard Rock props, pushes out:", len(R), R.groupby("mkt").size().to_dict())
    R = R[R.nb >= 2].copy(); print("with at least two other books:", len(R))
    for v, D in (("0", D0), ("1", D1)):
        R["c" + v] = 1.0
        for (date, mkt), g in R.groupby(["date", "mkt"]):
            n = len(g); r = g.mm.sum() / g["mu" + v].sum()
            R.loc[g.index, "c" + v] = float(np.clip((n * r + C_N0) / (n + C_N0), .85, 1.15))
        R["d" + v] = R.mm + W0 * (R["c" + v] * R["mu" + v] - R.mm)
        R["pm" + v] = [pov(D[m], mu, l) for m, mu, l in zip(R.mkt, R["mu" + v], R.line)]
        R["pd" + v] = [pov(D[m], mu, l) for m, mu, l in zip(R.mkt, R["d" + v], R.line)]
    ll = lambda p, y: -(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))
    for c in ("p_hr", "pm0", "pm1", "pd0", "pd1"): R["L_" + c] = ll(R[c], R.over)
    rng = np.random.default_rng(5)

    def boot(z, a, b):
        g = z.groupby("game")[["L_" + a, "L_" + b]].sum(); n = z.groupby("game").size(); x = (g["L_" + b] - g["L_" + a]).values; nn = n.values; bs = []
        for _ in range(2000):
            j = rng.integers(0, len(x), len(x)); bs.append(x[j].sum() / nn[j].sum())
        bs = np.array(bs); return np.percentile(bs, [2.5, 97.5]), float((bs < 0).mean())
    print("\nQ1 log loss of the over at Hard Rock's closing line (lower is better)")
    for lab, z in [("points", R[R.mkt == "pts"]), ("threes", R[R.mkt == "fg3"]), ("points + threes", R[R.mkt.isin(["pts", "fg3"])]), ("rebounds (control)", R[R.mkt == "reb"]), ("assists (control)", R[R.mkt == "ast"])]:
        m = {c: z["L_" + c].mean() for c in ("p_hr", "pm0", "pm1", "pd0", "pd1")}
        print(f"  {lab:<20} n={len(z):5d}  Hard Rock {m['p_hr']:.4f} | model alone: old {m['pm0']:.4f} new {m['pm1']:.4f} | desk blend: old {m['pd0']:.4f} new {m['pd1']:.4f}")
        if "control" not in lab:
            for nm, a, b in (("model alone", "pm0", "pm1"), ("desk blend", "pd0", "pd1")):
                (lo, hi), sh = boot(z, a, b); print(f"      {nm}: new minus old {m[b] - m[a]:+.4f} ({100 * (m[b] / m[a] - 1):+.2f}%), 95% range {lo:+.4f} to {hi:+.4f}, new better in {sh:.0%} of resamples")
            (lo, hi), sh = boot(z, "p_hr", "pd1"); print(f"      new desk blend against Hard Rock: {m['pd1'] - m['p_hr']:+.4f}, better in {sh:.0%} of resamples (old blend: {m['pd0'] - m['p_hr']:+.4f})")
    print("\nQ2 sides with a blended edge of 3 to 12 points at Hard Rock's closing price, flat one unit")
    for lab, mk in (("points", ["pts"]), ("threes", ["fg3"]), ("points + threes", ["pts", "fg3"])):
        for v in ("0", "1"):
            z = R[R.mkt.isin(mk)]; bets = []
            for r in z.itertuples():
                p = getattr(r, "pd" + v)
                for side, ps, odds, win in (("O", p, r.o, r.over == 1), ("U", 1 - p, r.u, r.over == 0)):
                    e = ps - 1 / dec(odds)
                    if .03 <= e <= .12 and -160 <= odds <= 150 and r.mn >= 20: bets.append((dec(odds) - 1) if win else -1.0)
            b = np.array(bets); print(f"  {lab:<16} {'new' if v == '1' else 'old'} build: {len(b):4d} sides, won {int((b > 0).sum()):4d} ({(b > 0).mean():.1%}), return {b.mean() * 100:+.1f}% a unit" if len(b) else f"  {lab} {v}: none")
    R.to_pickle("/home/claude/props/lab/shot_close.pkl")

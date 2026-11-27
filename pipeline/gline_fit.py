"""Lab and builder for the game price lane's score distribution (v4.2). Writes gline_dist.json (read by gline.py).
Run by hand when a season ends; the daily job never runs it.
  python3 gline_fit.py          fit on every finished game with a closing line, print the test, write the file
v4.2 upgrades:
  - Hard-sets NBA keys['0'] = 0.0 (NBA plays OT and can never end in a tie; removes 1.19% phantom pick'em push mass).
  - Exact Z(mu)-normalized expected counts in the iterative key-weight fit (removes +1.6% to +3.0% normalization bias).
  - Defensive guards on degenerate/small data (min 20 games, clamped share in (0.05, 0.95), sd >= 1.0)."""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gline, games

D, O = gline.D, gline.O
KMAX = {"NFL": 17, "NBA": 10}
N0 = 20.0


def rows(lg):
    if lg == "NFL":
        s = pd.read_csv(D + "nfl_games.csv", low_memory=False)
        s = s[s.result.notna() & s.spread_line.notna() & (s.season >= 2010) & (s.game_type == "REG")]
        return pd.DataFrame(dict(
            season=s.season.astype(int), m=s.result.astype(float), spr=s.spread_line.astype(float),
            tot=(s.home_score + s.away_score).astype(float), tl=s.total_line.astype(float),
            mh=s.home_moneyline, ma=s.away_moneyline,
        )).reset_index(drop=True)
    LN = games.nba_lines()
    b = pd.concat([
        pd.read_parquet(f"{D}nba_pb_{y}.parquet", columns=["game_id", "season", "season_type", "home_away", "team_score", "opponent_team_score"])
        for y in (2025, 2026, 2027)
    ])
    b = b[(b.home_away == "home") & b.season_type.isin([2, 3])].drop_duplicates("game_id")
    R = []
    for r in b.itertuples():
        ln = LN.get(str(int(r.game_id)))
        if not ln or ln[0] is None or pd.isna(r.team_score):
            continue
        R.append(dict(
            season=int(r.season), m=float(r.team_score - r.opponent_team_score), spr=float(ln[0]),
            tot=float(r.team_score + r.opponent_team_score), tl=None if ln[1] is None else float(ln[1]),
            mh=ln[2], ma=ln[3],
        ))
    return pd.DataFrame(R)


def mids(dist, spreads):
    """The middle margin at which each closing spread is a fair 50/50 bet (one solve per distinct spread)."""
    return {s: dist.solve(s, 0.5) for s in sorted(set(spreads))}


def winll(d, dist):
    mu = mids(dist, d.spr.values)
    z = d[d.m != 0]
    p = np.clip([dist.over(mu[s], 0)[0] for s in z.spr.values], 1e-6, 1 - 1e-6)
    y = (z.m.values > 0).astype(float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def fit(d, lg):
    """Key weights from Z(mu)-normalized actual vs expected counts; sd chosen by closing-spread win log-loss."""
    if len(d) < 20:
        raise ValueError(f"need at least 20 games to fit {lg}, got {len(d)}")
    keys = {"0": 0.0} if lg == "NBA" else {}
    sd = max(1.0, float((d.m - d.spr).std()) * 0.9)
    for _ in range(4):
        dist = gline.Dist(sd, keys)
        mu = mids(dist, d.spr.values)
        exp = np.zeros(len(dist.k))
        # Exact Z(mu)-normalized unweighted kernel: p_k(mu) / w_k = g_k(mu) / Z(mu)
        inv_w = np.where(dist.w > 0, 1.0 / dist.w, 0.0)
        for s, c in d.spr.value_counts().items():
            exp += c * (dist.pmf(mu[s]) * inv_w)
        act = np.array([(d.m == k).sum() for k in dist.k], float)
        keys = {}
        for a in range(0, KMAX[lg] + 1):
            if lg == "NBA" and a == 0:
                keys["0"] = 0.0
                continue
            i = np.abs(dist.k) == a
            keys[str(a)] = round(float((act[i].sum() + N0) / (exp[i].sum() + N0)), 3)
        lo_sd = max(1.0, sd - 2.0)
        best = min(((winll(d, gline.Dist(float(c), keys)), float(c)) for c in np.arange(lo_sd, sd + 2.01, 0.25)))
        sd = round(max(1.0, best[1]), 2)
    t = d[d.tl.notna()]
    if len(t) < 5:
        raise ValueError(f"need at least 5 totals rows to fit {lg}, got {len(t)}")
    r = (t.tot - t.tl).values
    share = min(max(float((np.abs(r) <= 7).mean()), 0.05), 0.95)
    from scipy.stats import norm
    tsd = round(max(1.0, 7.25 / float(norm.ppf(0.5 + share / 2.0))), 2)
    return dict(sd=sd, keys=keys, tsd=tsd, tmax=400 if lg == "NBA" else 160, n=int(len(d)), tn=int(len(t)))


def test(d, lg, split):
    tr, te = d[d.season < split], d[d.season >= split]
    f = fit(tr, lg)
    dm = gline.Dist(f["sd"], f["keys"])
    pn = gline.Dist(f["sd"], {"0": 0.0} if lg == "NBA" else None)
    z = te[(te.m != 0) & te.mh.notna() & te.ma.notna()]
    pb = np.clip([games.novig(float(a), float(b)) for a, b in zip(z.mh, z.ma)], 1e-6, 1 - 1e-6)
    y = (z.m.values > 0).astype(float)
    print(f"  {lg} fit before {split} ({len(tr)} games), scored {split} on ({len(z)} games): win chance read from closing spread, log loss "
          f"{winll(z, dm):.4f} with key numbers, {winll(z, pn):.4f} plain curve, against {float(-(y * np.log(pb) + (1 - y) * np.log(1 - pb)).mean()):.4f} for books' moneylines")
    mu = mids(dm, te.spr.values)
    for w in (1, 3):
        act = float((np.abs(te.m - te.spr) <= w).mean())
        pred = float(np.mean([dm.pmf(mu[s])[np.abs(dm.k - s) <= w].sum() for s in te.spr.values]))
        pl = float(np.mean([pn.pmf(s)[np.abs(pn.k - s) <= w].sum() for s in te.spr.values]))
        print(f"    later games landing within {w} of closing spread: {act * 100:.1f}% actual, {pred * 100:.1f}% with key numbers, {pl * 100:.1f}% plain curve")
    t = te[te.tl.notna()]
    dt = gline.Dist(f["tsd"], None, lo=0, hi=400)
    for w in (3, 7):
        act = float((np.abs(t.tot - t.tl) <= w).mean())
        pred = float(np.mean([dt.pmf(x)[np.abs(dt.k - x) <= w].sum() for x in t.tl.values]))
        print(f"    totals landing within {w} of closing total: {act * 100:.1f}% actual, {pred * 100:.1f}% fitted (sd {f['tsd']})")
    return f


if __name__ == "__main__":
    out = {}
    for lg, split in (("NFL", 2022), ("NBA", 2027)):
        d = rows(lg)
        test(d, lg, split)
        out[lg] = fit(d, lg)
        print(f"  {lg} final fit on {out[lg]['n']} games: margin sd {out[lg]['sd']}, total sd {out[lg]['tsd']}, key weights {out[lg]['keys']}")
    dm = gline.Dist(out["NFL"]["sd"], out["NFL"]["keys"])
    print("  NFL, what half a point is worth to the favourite's backer (chance to cover, push removed):")
    for s in (2.5, 3, 3.5, 6.5, 7, 7.5, 10):
        mu = dm.solve(s, 0.5)
        print(f"    market fair at -{s:g}: laying -{s - .5:g} covers {dm.over(mu, s - .5)[0] * 100:.1f}%, laying -{s + .5:g} covers {dm.over(mu, s + .5)[0] * 100:.1f}%")
    out["fitted"] = "gline_fit.py (v4.2 Z-normalized, NBA tie=0), NFL regular seasons 2010 on, NBA 2025-26 on; rerun after each season"
    with open(os.path.dirname(os.path.abspath(__file__)) + "/gline_dist.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("wrote gline_dist.json")

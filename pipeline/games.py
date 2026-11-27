"""Game picks: who wins and who covers, NFL and NBA. A margin-of-victory rating for every club (Elo with a home edge,
a rest edge for NBA back-to-backs, and a pull back toward average each new season), walked forward game by game so
every number the backtest scores was made before that game was played.

Writes out/games.json: {lg: {games: [...], bt: {...}, season: {...}, cfg: {...}}}. The picks are tracked in out/gpicks.json
by daily.py; they are not staked. Market numbers: NFL from the nflverse schedule (consensus spread and moneylines), and for
both leagues Hard Rock and the other books from the relay's game odds pull when it is on file (out/games/{LG}_{date}.txt)."""
import json, math, os, glob, datetime
from zoneinfo import ZoneInfo      # v3.19: real Eastern time (a fixed UTC-5 was an hour off in daylight time)
import numpy as np, pandas as pd
from scipy.stats import norm

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
CFG = {"NFL": dict(K=20, HFA=48, PPE=25.0, rev=1 / 3, sd=13.1, b2b=0),
       "NBA": dict(K=25, HFA=60, PPE=26.0, rev=0.25, sd=11.8, b2b=30)}     # v3.16: NBA sd fitted on 2025-26 by log loss (was 14.7, too timid); 2026-27 log loss .5906 -> .5869
TIERS = [(4.5, "Strong"), (3.0, "Pick"), (1.5, "Lean")]      # spread gap in points, model against the market
TIER_ON = {"NFL": True, "NBA": False}       # NBA ratings went 47.8% against DraftKings' closing spread (2025-27): no tiers there
PTS = {"NFL": dict(k=0.03, rev=0.4, hfa=1.6, mu=22.0, mr=0.004), "NBA": dict(k=0.05, rev=0.5, hfa=2.5, mu=113.0, mr=0.01)}   # fitted on 2010-18 (NFL), 2025 (NBA)


SKIP_BOOKS = ("pinnacle",)     # v4.0: the relay's game pull now carries Pinnacle for gline.py; the game picks' own consensus stays as it was


def dec(a):
    if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(a) or abs(a) < 100:
        raise ValueError(f"invalid American odds: {a!r}")
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def novig(a, b):
    try:
        da, db = dec(a), dec(b)
    except ValueError:
        return None
    pa, pb = 1 / da, 1 / db
    return pa / (pa + pb)


def tier(gap):
    return next((n for t, n in TIERS if abs(gap) >= t), None)


class Elo:
    def __init__(self, c):
        self.c, self.E, self.last = c, {}, {}

    def pre(self, t, season):
        if t not in self.E:
            self.E[t] = 1500.0
        if self.last.get(t) not in (None, season):
            self.E[t] = 1500 + (self.E[t] - 1500) * (1 - self.c["rev"])
        self.last[t] = season

    def diff(self, h, a, neutral=False, adj=0.0):
        return self.E[h] - self.E[a] + (0 if neutral else self.c["HFA"]) + adj

    def update(self, h, a, d, res, nfl):
        w = 1 if res > 0 else 0 if res < 0 else .5
        pw = 1 / (1 + 10 ** (-d / 400))
        if nfl:
            mult = math.log(abs(res) + 1) * 2.2 / ((d if res > 0 else -d) * .001 + 2.2)
        else:
            mult = ((abs(res) + 3) ** .8) / (7.5 + .006 * (d if res > 0 else -d))
        self.E[h] += self.c["K"] * mult * (w - pw); self.E[a] -= self.c["K"] * mult * (w - pw)


class Pts:
    """Points for and against: each club's offense and defense, in points above the league average, nudged by every result."""
    def __init__(self, c):
        self.c, self.O, self.D, self.last, self.mu = c, {}, {}, {}, c["mu"]

    def pre(self, t, season):
        self.O.setdefault(t, 0.0); self.D.setdefault(t, 0.0)
        if self.last.get(t) not in (None, season):
            self.O[t] *= 1 - self.c["rev"]; self.D[t] *= 1 - self.c["rev"]
        self.last[t] = season

    def proj(self, h, a, neutral=False):
        e = 0 if neutral else self.c["hfa"] / 2
        return self.mu + self.O[h] + self.D[a] + e, self.mu + self.O[a] + self.D[h] - e

    def update(self, h, a, sh, sa, neutral=False):
        ph, pa = self.proj(h, a, neutral); k = self.c["k"]; eh, ea = sh - ph, sa - pa
        self.O[h] += k * eh; self.D[a] += k * eh; self.O[a] += k * ea; self.D[h] += k * ea; self.mu += self.c["mr"] * (eh + ea) / 2


def market_files(lg):
    """Hard Rock and consensus game lines from the relay pull, newest file per league, keyed by 'AWAY@HOME|YYYY-MM-DD' and 'AWAY@HOME'."""
    fs = sorted(glob.glob(O + f"games/{lg}_*.txt"), key=os.path.getmtime)
    out = {}
    for f in fs[-2:]:
        game = None; tipday = None; buf = []
        def flush():
            if not game or not buf:
                return
            keys = [f"{game}|{tipday}", game] if tipday else [game]
            for k in keys:
                # For plain matchup key, keep the earliest upcoming day (prevents tomorrow's B2B overwriting today's game)
                if k == game and k in out and tipday and out[k].get("_tipday") and tipday > out[k]["_tipday"]:
                    continue
                slot = out.setdefault(k, {"_tipday": tipday})
                if tipday and (not slot.get("_tipday") or tipday < slot["_tipday"]):
                    slot["_tipday"] = tipday
                for bk, mk, team, pt, px in buf:
                    slot.setdefault(bk, {}).setdefault(mk, {})[team] = (pt, px)
        for ln in open(f, encoding="utf-8", errors="replace"):
            if ln.startswith("# game:"):
                flush(); game = ln.split(":", 1)[1].strip().replace(" ", ""); tipday = None; buf = []; continue
            if ln.startswith("# tip:") and game:
                tipday = ln.split(":", 1)[1].strip()[:10]; continue
            if ln.startswith("#") or "|" not in ln or ln.startswith("bookmaker_key") or game is None:
                continue
            bk, mk, team, pt, px = (ln.strip().split("|") + [""] * 5)[:5]
            if bk in SKIP_BOOKS:
                continue
            try:
                px = float(px); pt = float(pt) if pt else None
            except ValueError:
                continue
            if not (math.isfinite(px) and abs(px) >= 100) or (pt is not None and not math.isfinite(pt)):
                continue
            buf.append((bk, mk, team, pt, px))
        flush()
    for v in out.values():
        v.pop("_tipday", None)
    return out


NFN = {"OAK": "LV", "SD": "LAC", "STL": "LA"}       # nfelo keeps the old club codes


def nfelo_file():
    """nfelo's published game file (github.com/greerreNFL/nfelo): the opening and closing spread and total for every game
    since 2009, and nfelo's own line and expected value on each side. Keyed (season, week, away, home); None if not on file."""
    f = D + "nfelo_games.csv"
    if not os.path.exists(f):
        return None
    try:
        n = pd.read_csv(f)
        k = n.game_id.str.split("_", expand=True)
        n["season"] = k[0].astype(int); n["week"] = k[1].astype(int); n["away"] = k[2].replace(NFN); n["home"] = k[3].replace(NFN)
        return {(r.season, r.week, r.away, r.home): r for r in n.itertuples()}
    except Exception as e:
        print("nfelo file not read:", e); return None


def history(lg):
    """Every relay pull of game lines on file, oldest first, keyed by 'AWAY@HOME|tipday' (and 'AWAY@HOME' fallback)."""
    out = {}
    fs = sorted(f for f in glob.glob(O + f"games/{lg}_*.txt") if "test" not in os.path.basename(f))
    for f in fs:
        day = os.path.basename(f)[len(lg) + 1:-4]; cur = {}; game = None; tipday = None
        for ln in open(f, encoding="utf-8", errors="replace"):
            if ln.startswith("# game:"):
                game = ln.split(":", 1)[1].strip().replace(" ", ""); tipday = None; continue
            if ln.startswith("# tip:") and game:
                tipday = ln.split(":", 1)[1].strip()[:10]; continue
            if ln.startswith("#") or "|" not in ln or ln.startswith("bookmaker_key") or game is None:
                continue
            bk, mk, team, pt, px = (ln.strip().split("|") + [""] * 5)[:5]
            if bk in SKIP_BOOKS:
                continue
            try:
                pt = float(pt) if pt else None
            except ValueError:
                continue
            if pt is not None and not math.isfinite(pt):
                continue
            gkey = f"{game}|{tipday}" if tipday else game
            cur.setdefault(gkey, {}).setdefault(mk, {}).setdefault(team, []).append(pt)
        for gkey, m in cur.items():
            base = gkey.split("|", 1)[0]
            if "@" not in base:
                continue
            home = base.split("@")[1]
            sp = [-v for v in m.get("spreads", {}).get(home, []) if v is not None]; tl = [v for v in m.get("totals", {}).get("Over", []) if v is not None]
            if sp or tl:
                rec = [day, float(np.median(sp)) if sp else None, float(np.median(tl)) if tl else None]
                out.setdefault(gkey, []).append(rec)
                if "|" not in gkey:
                    out.setdefault(base, []).append(rec)
    return out


def move(pm, spr, tl, op, top, path, src):
    """Where the line opened, where it is now, and what the move has meant historically (see moves_nfl / moves_nba)."""
    if op is None and top is None:
        return None
    o = dict(open=op, now=spr, topen=top, tnow=tl, src=src, path=[[d[5:], a, b] for d, a, b in (path or [])][-8:])
    if op is not None and spr is not None:
        d = round(spr - op, 1); o["d"] = d
        if d:
            o["called"] = int((pm - op > 0) == (d > 0)) if abs(pm - op) >= 1 else None
            for k in (3, 7):                    # the favourite pushed up through a key number, or pulled back down to it
                if np.sign(op) == np.sign(spr) and (abs(op) <= k < abs(spr) or abs(spr) <= k < abs(op)):
                    o["key"] = [k, "up" if abs(spr) > abs(op) else "down"]; break
    if top is not None and tl is not None:
        o["td"] = round(tl - top, 1)
    return o


def rec2(mask, win):
    m = mask & win.notna(); w = int(win[m].sum()); return [w, int(m.sum()) - w]


def moves_nfl(rows, NF):
    """What line moves, key numbers, roofs and wind have meant since 2009, from nfelo's open and close numbers and the
    nflverse results. Each entry is [wins, losses] for the rule in its name."""
    R = []
    for r in rows:
        n = NF.get((r["season"], r["week"], NFN.get(r["away"], r["away"]), NFN.get(r["home"], r["home"])))
        if n is None or r["res"] is None or pd.isna(n.home_line_open) or pd.isna(n.home_line_close):
            continue
        R.append(dict(s=r["season"], pm=r["pm"], res=r["res"], tot=r["tot"], op=-n.home_line_open, cl=-n.home_line_close, tc=n.total_line_close, to=n.total_line_open,
                      roof=r.get("roof"), wind=r.get("wind"), heo=n.home_open_ev, aeo=n.away_open_ev, hec=n.home_close_ev, aec=n.away_close_ev))
    d = pd.DataFrame(R)
    if d.empty:
        return None
    d["mv"] = d.cl - d.op; yc = d.res - d.cl; yo = d.res - d.op
    cov = lambda side_home, y: pd.Series(np.where(y == 0, np.nan, (side_home == (y > 0)).astype(float)), index=d.index)
    out = dict(n=len(d), since=int(d.s.min()), moved=round(float((d.mv != 0).mean()), 3), avg=round(float(d.mv.abs().mean()), 2))
    mvd = d.mv.abs() >= 0.5
    out["follow_close"] = rec2(mvd, cov(d.mv > 0, yc)); out["follow_open"] = rec2(mvd, cov(d.mv > 0, yo))
    big = d.mv.abs() >= 2
    out["follow_close_big"] = rec2(big, cov(d.mv > 0, yc))
    g = d.pm - d.op
    out["called"] = rec2((g.abs() >= 2.5) & (d.mv != 0), pd.Series(((g > 0) == (d.mv > 0)).astype(float), index=d.index))
    out["open_ats"] = rec2(g.abs() >= 3, cov(g > 0, yo)); out["close_ats"] = rec2(g.abs() >= 3, cov(g > 0, yc))
    same = np.sign(d.op) == np.sign(d.cl)
    up3 = same & (d.op.abs() <= 3) & (d.cl.abs() > 3)
    out["key3_dog"] = rec2(up3, cov(d.cl < 0, yc))                       # favourite pushed up through 3: take the underdog at the close
    up7 = same & (d.op.abs() <= 7) & (d.cl.abs() > 7)
    out["key7_dog"] = rec2(up7, cov(d.cl < 0, yc))
    yt = d.tot - d.tc
    und = pd.Series(np.where(yt == 0, np.nan, (yt < 0).astype(float)), index=d.index)
    out["wind_under"] = rec2((d.roof == "outdoors") & (d.wind >= 10), und)
    out["wind_under_recent"] = rec2((d.roof == "outdoors") & (d.wind >= 10) & (d.s >= 2021), und)
    out["calm_under"] = rec2((d.roof == "outdoors") & (d.wind < 10), und)
    out["dome_over"] = rec2(d.roof.isin(["dome", "closed"]), 1 - und); out["out_over"] = rec2(d.roof.isin(["outdoors", "open"]), 1 - und)
    out["dome_home"] = rec2(d.roof.isin(["dome", "closed"]), cov(pd.Series(True, index=d.index), yc)); out["out_home"] = rec2(d.roof.isin(["outdoors", "open"]), cov(pd.Series(True, index=d.index), yc))
    t = d.to.notna() & d.tc.notna() & ((d.tc - d.to).abs() >= 1)
    out["tot_follow"] = rec2(t, pd.Series(np.where(yt == 0, np.nan, ((d.tc - d.to > 0) == (yt > 0)).astype(float)), index=d.index))
    for nm, he, ae, y in (("nf_close", d.hec, d.aec, yc), ("nf_open", d.heo, d.aeo, yo)):
        pk = (np.maximum(he, ae) > 0) & (he != ae); c = cov(he > ae, y)
        out[nm] = rec2(pk, c); out[nm + "_recent"] = rec2(pk & (d.s >= 2022), c)
    return out


def moves_nba(rows):
    d = pd.DataFrame([dict(pm=r["pm"], res=r["res"], tot=r["tot"], op=r["op"], cl=r["spr"], to=r.get("top"), tc=r.get("tl")) for r in rows if r.get("op") is not None and r.get("spr") is not None])
    if d.empty:
        return None
    d["mv"] = d.cl - d.op; yc = d.res - d.cl; yo = d.res - d.op
    cov = lambda side_home, y: pd.Series(np.where(y == 0, np.nan, (side_home == (y > 0)).astype(float)), index=d.index)
    out = dict(n=len(d), since=2025, moved=round(float((d.mv != 0).mean()), 3), avg=round(float(d.mv.abs().mean()), 2))
    mvd = d.mv.abs() >= 0.5
    out["follow_close"] = rec2(mvd, cov(d.mv > 0, yc)); out["follow_open"] = rec2(mvd, cov(d.mv > 0, yo)); out["follow_close_big"] = rec2(d.mv.abs() >= 2, cov(d.mv > 0, yc))
    g = d.pm - d.op
    out["called"] = rec2((g.abs() >= 3) & (d.mv != 0), pd.Series(((g > 0) == (d.mv > 0)).astype(float), index=d.index))
    out["open_ats"] = rec2(g.abs() >= 3, cov(g > 0, yo)); out["close_ats"] = rec2(g.abs() >= 3, cov(g > 0, yc))
    yt = d.tot - d.tc; t = d.to.notna() & d.tc.notna() & ((d.tc - d.to).abs() >= 2)
    out["tot_follow"] = rec2(t, pd.Series(np.where(yt == 0, np.nan, ((d.tc - d.to > 0) == (yt > 0)).astype(float)), index=d.index))
    return out


def consensus(q, away, home):
    """Median no-vig home win chance, home spread, total and moneylines across books, plus every book's own numbers."""
    pw, sp, tl, mh, ma = [], [], [], [], []
    for bk, m in q.items():
        h2h = m.get("h2h", {})
        if home in h2h and away in h2h:
            pw.append(novig(h2h[home][1], h2h[away][1])); mh.append(h2h[home][1]); ma.append(h2h[away][1])
        s = m.get("spreads", {})
        if home in s and s[home][0] is not None:
            sp.append(-s[home][0])      # books write the home side as -6.5 when home is favoured; we keep "home by 6.5" = +6.5
        t = m.get("totals", {})
        if "Over" in t and t["Over"][0] is not None:
            tl.append(t["Over"][0])
    med = lambda v: float(np.median(v)) if v else None
    return dict(p_home=med(pw), spread=med(sp), total=med(tl), ml=[med(ma), med(mh)], nb=len(q), q=q)


def book_q(r):
    """One 'book' built from the nflverse schedule's closing numbers, for weeks with no relay pull."""
    q = {}
    if not pd.isna(r.home_moneyline) and not pd.isna(r.away_moneyline):
        q["h2h"] = {r.home_team: (None, float(r.home_moneyline)), r.away_team: (None, float(r.away_moneyline))}
    if not pd.isna(r.spread_line):
        q["spreads"] = {r.home_team: (-float(r.spread_line), None if pd.isna(r.home_spread_odds) else float(r.home_spread_odds)),
                        r.away_team: (float(r.spread_line), None if pd.isna(r.away_spread_odds) else float(r.away_spread_odds))}
    if not pd.isna(r.total_line):
        q["totals"] = {"Over": (float(r.total_line), None if pd.isna(r.over_odds) else float(r.over_odds)),
                       "Under": (float(r.total_line), None if pd.isna(r.under_odds) else float(r.under_odds))}
    return {"consensus": q} if q else {}


def best(q, mk, name, hi=True):
    """The best number for the bettor on one side: more points on a spread or an under, fewer on an over, then the best price."""
    c = [(bk, m[mk][name]) for bk, m in q.items() if name in m.get(mk, {}) and m[mk][name][1] is not None]
    if not c:
        return None
    key = lambda x: (((x[1][0] or 0) if hi else -(x[1][0] or 0)), dec(x[1][1]))
    bk, (pt, px) = max(c, key=key)
    hr = q.get("hardrockbet", {}).get(mk, {}).get(name)
    return dict(bk=bk, pt=pt, px=px, hr=None if not hr or hr[1] is None else [hr[0], hr[1]])


def score(rows):
    """Walk-forward record: straight up, against the market spread by how far the model was from it, and the total."""
    t = [r for r in rows if r["res"] is not None]
    su = [(r["pm"] > 0) == (r["res"] > 0) for r in t if r["res"] != 0]
    out = dict(n=len(t), su=round(float(np.mean(su)), 4) if su else None, mae=round(float(np.mean([abs(r["res"] - r["pm"]) for r in t])), 2) if t else None)
    m = [r for r in t if r.get("spr") is not None]
    if m:
        out["mae_mkt"] = round(float(np.mean([abs(r["res"] - r["spr"]) for r in m])), 2)
        f = [r for r in m if r["res"] != 0 and r["spr"] != 0]
        out["su_mkt"] = round(float(np.mean([(r["spr"] > 0) == (r["res"] > 0) for r in f])), 4) if f else None
        out["n_mkt"] = len(m)
        pl = []
        for r in m:
            ml = r.get("ml") or (None, None)
            if ml[0] is None or ml[1] is None or r["res"] == 0 or (isinstance(ml[0], float) and math.isnan(ml[0])):
                continue
            p = float(norm.cdf(r["pm"] / r["sd"]))
            for pp, px, won in ((p, ml[0], r["res"] > 0), (1 - p, ml[1], r["res"] < 0)):
                if pp * dec(px) - 1 >= 0.03:
                    pl.append(dec(px) - 1 if won else -1.0)
        if pl:
            out["ml_value"] = [len(pl), round(float(np.mean(pl)), 4)]
        ats = {}
        for name in ("All", "None") + tuple(n for _, n in TIERS):
            z = [r for r in m if r["res"] != r["spr"] and (name == "All" or tier(r["pm"] - r["spr"]) == (None if name == "None" else name))]
            w = sum((r["pm"] > r["spr"]) == (r["res"] > r["spr"]) for r in z)
            ats[name] = [w, len(z) - w]
        out["ats"] = ats
    tt = [r for r in t if r.get("pt") is not None and r.get("tot") is not None]
    if tt:
        out["mae_tot"] = round(float(np.mean([abs(r["tot"] - r["pt"]) for r in tt])), 2)
        tm = [r for r in tt if r.get("tl") is not None]
        if tm:
            out["mae_tot_mkt"] = round(float(np.mean([abs(r["tot"] - r["tl"]) for r in tm])), 2)
            ou = {}
            for name, lo, hi in (("All", 0, 99), ("Under 3", 0, 3), ("3 plus", 3, 99)):
                z = [r for r in tm if r["tot"] != r["tl"] and lo <= abs(r["pt"] - r["tl"]) < hi]
                w = sum((r["pt"] > r["tl"]) == (r["tot"] > r["tl"]) for r in z)
                ou[name] = [w, len(z) - w]
            out["ou"] = ou
    return out


def rate(a):
    return None if not a or not sum(a) else round(a[0] / sum(a), 4)


def seasons(rows, first):
    """The same record, one season at a time, for the track record chart."""
    out = []
    for S in sorted({r["season"] for r in rows if r["season"] >= first}):
        b = score([r for r in rows if r["season"] == S])
        a = b.get("ats") or {}
        out.append(dict(s=S, n=b["n"], su=b.get("su"), su_mkt=b.get("su_mkt"), ats=a.get("All"), edge=a.get("Strong"), ou=(b.get("ou") or {}).get("All"),
                        mae=b.get("mae"), mae_mkt=b.get("mae_mkt")))
    return out


def pick(lg, r, mkt, bt):
    """One game. Where the books have a line, the projection follows them (the walk-forward test found no weight on our
    ratings that improved on the closing number); our ratings' own margin and total sit beside it, and the spread pick is
    the side our ratings favour against the books, tiered by the gap in the NFL only."""
    c = CFG[lg]; pm = r["pm"]; p = float(norm.cdf(pm / c["sd"])); pt = r.get("pt")
    out = dict(id=r["gid"], day=r["day"], time=r["time"], away=r["away"], home=r["home"], pm=round(pm, 2), p_home=round(p, 4), elo=r.get("elo"),
               rk=r.get("rk"), rest=r.get("rest"), pt=None if pt is None else round(pt, 1))
    q = mkt["q"] if mkt else {}
    spr = None if not mkt else mkt["spread"]; pmk = None if not mkt else mkt["p_home"]; tl = None if not mkt else mkt["total"]
    out.update(spread=None if spr is None else round(spr, 1), p_mkt=None if pmk is None else round(pmk, 4), total=tl, nb=mkt["nb"] if mkt else 0,
               ml_mkt=mkt["ml"] if mkt else None, src="relay" if q and "consensus" not in q else ("schedule" if q else None))
    # projection: the books' numbers when they exist, our ratings otherwise
    M = spr if spr is not None else pm; T = tl if tl is not None else pt
    if T is not None:
        out["sc"] = [round((T - M) / 2, 1), round((T + M) / 2, 1)]
    ph = pmk if pmk is not None else p
    out["proj"] = "books" if spr is not None else "ratings"
    out["p_proj"] = round(ph, 4)
    out["winner"] = r["home"] if (ph > .5 if pmk is not None else pm > 0) else r["away"]
    out["p_win"] = round(ph if out["winner"] == r["home"] else 1 - ph, 4)
    out["p_rate"] = round(p if out["winner"] == r["home"] else 1 - p, 4)
    out["ml"] = best(q, "h2h", out["winner"]) if q else None
    if out["ml"] and pmk is not None:
        out["ml"]["fair"] = out["p_win"]
    if spr is not None:
        gap = round(pm - spr, 2); side = r["home"] if gap > 0 else r["away"]; tr = tier(gap) if TIER_ON[lg] else None
        a = (bt.get("ats") or {}).get(tr or "None") if TIER_ON[lg] else (bt.get("ats") or {}).get("All")
        out.update(ats=side, gap=gap, tier=tr, p_cover=rate(a), cover_n=sum(a) if a else 0, sbest=best(q, "spreads", side))
    if tl is not None and pt is not None:
        tg = round(pt - tl, 1); ou = "Over" if tg > 0 else "Under"
        out.update(ou=ou, tgap=tg, tbest=best(q, "totals", ou, hi=(ou == "Under")))
    return out


def ranks(E, teams):
    order = sorted(teams, key=lambda t: -E.get(t, 1500))
    return {t: i + 1 for i, t in enumerate(order)}


def final(r, lg="NFL"):
    """A finished game, graded with the number the model had before it."""
    o = dict(id=r["gid"], day=r["day"], away=r["away"], home=r["home"], pm=round(r["pm"], 2), pt=None if r.get("pt") is None else round(r["pt"], 1),
             fin=[r["sa"], r["sh"]], spread=r.get("spr"), total=r.get("tl"))
    if r["res"] != 0:
        o["su"] = int((r["pm"] > 0) == (r["res"] > 0))
    if r.get("spr") is not None and r["res"] != r["spr"]:
        o["tier"] = tier(r["pm"] - r["spr"]) if TIER_ON[lg] else None; o["ats"] = r["home"] if r["pm"] > r["spr"] else r["away"]
        o["cover"] = int((r["pm"] > r["spr"]) == (r["res"] > r["spr"]))
    if r.get("tl") is not None and r.get("pt") is not None and r["tot"] != r["tl"]:
        o["ou"] = "Over" if r["pt"] > r["tl"] else "Under"; o["ou_hit"] = int((r["pt"] > r["tl"]) == (r["tot"] > r["tl"]))
    return o


def nfl():
    c = CFG["NFL"]; g = pd.read_csv(D + "nfl_games.csv", low_memory=False)
    g = g[g.season >= 2005].sort_values(["season", "week", "gameday", "gametime"]).reset_index(drop=True)
    el, pp, rows, src = Elo(c), Pts(PTS["NFL"]), [], {}
    for r in g.itertuples():
        el.pre(r.home_team, r.season); el.pre(r.away_team, r.season); pp.pre(r.home_team, r.season); pp.pre(r.away_team, r.season)
        neu = r.location == "Neutral"; d = el.diff(r.home_team, r.away_team, neu); ph, pa = pp.proj(r.home_team, r.away_team, neu)
        res = None if pd.isna(r.result) else float(r.result)
        rows.append(dict(season=int(r.season), week=int(r.week), gid=r.game_id, gt=r.game_type, day=str(r.gameday), time=None if pd.isna(r.gametime) else str(r.gametime), away=r.away_team, home=r.home_team,
                         pm=d / c["PPE"], pt=ph + pa, res=res, spr=None if pd.isna(r.spread_line) else float(r.spread_line),
                         tl=None if pd.isna(r.total_line) else float(r.total_line), tot=None if res is None else float(r.home_score + r.away_score),
                         sh=None if res is None else int(r.home_score), sa=None if res is None else int(r.away_score),
                         rest=[None if pd.isna(r.away_rest) else int(r.away_rest), None if pd.isna(r.home_rest) else int(r.home_rest)],
                         ml=(None if pd.isna(r.home_moneyline) else float(r.home_moneyline), None if pd.isna(r.away_moneyline) else float(r.away_moneyline)), sd=c["sd"],
                         roof=None if pd.isna(r.roof) else ("dome" if r.roof in ("dome", "closed") else "outdoors"), wind=None if pd.isna(r.wind) else float(r.wind), neutral=neu,
                         elo=(round(el.E[r.home_team]), round(el.E[r.away_team]))))
        src[r.game_id] = r
        if res is not None:
            el.update(r.home_team, r.away_team, d, res, True); pp.update(r.home_team, r.away_team, r.home_score, r.away_score, neu)
    cur = int(g.season.max()); test = [r for r in rows if 2015 <= r["season"] < cur]; bt = score(test)
    up = [r for r in rows if r["res"] is None and r["season"] == cur]
    wk = min((r["week"] for r in up), default=None)
    done = [r for r in rows if r["res"] is not None and r["season"] == cur]
    lastwk = max((r["week"] for r in done), default=None)
    rk = ranks(el.E, set(g[g.season == cur].home_team))
    mk = market_files("NFL"); NF = nfelo_file() or {}; HS = history("NFL")
    WX = json.load(open(O + "weather.json")) if os.path.exists(O + "weather.json") else {}
    IJ = injuries("NFL"); games = []
    for r in [r for r in up if r["week"] == wk]:
        r["rk"] = [rk.get(r["away"]), rk.get(r["home"])]
        rq = (mk.get(f'{r["away"]}@{r["home"]}|{r["day"]}') or mk.get(f'{r["away"]}@{r["home"]}')) if mk else None
        m = consensus(rq if rq else book_q(src[r["gid"]]), r["away"], r["home"])
        g = pick("NFL", r, m, bt)
        n = NF.get((r["season"], r["week"], NFN.get(r["away"], r["away"]), NFN.get(r["home"], r["home"])))
        path = HS.get(f'{r["away"]}@{r["home"]}|{r["day"]}') or HS.get(f'{r["away"]}@{r["home"]}', [])
        op = top = None; osrc = None
        if n is not None and not pd.isna(n.home_line_open):
            op = -float(n.home_line_open); top = None if pd.isna(n.total_line_open) else float(n.total_line_open); osrc = "nfelo"
        elif path:
            op, top, osrc = path[0][1], path[0][2], "first pull " + path[0][0][5:]
        g["mv"] = move(r["pm"], g.get("spread"), g.get("total"), op, top, path, osrc)
        if n is not None and not pd.isna(n.nfelo_home_line_close):
            he, ae = n.home_close_ev, n.away_close_ev
            g["nf"] = dict(line=round(-float(n.nfelo_home_line_close), 1), side=None if pd.isna(he) or he == ae or max(he, ae) <= 0 else (r["home"] if he > ae else r["away"]),
                           ev=None if pd.isna(he) else round(float(max(he, ae)), 4), at=None if pd.isna(n.home_line_close) else -float(n.home_line_close))
        w = WX.get(r["gid"])
        g["inj"] = inj_card(IJ, r["away"], r["home"], "NFL")
        g["venue"] = dict(roof="neutral" if r.get("neutral") else (r.get("roof") or "retractable"), wind=w["wind"] if w else None, temp=w.get("temp") if w else None)
        games.append(g)
    return dict(games=games, week=wk, season=cur, bt=bt, this=score(done), seasons=seasons(rows, 2015), mvbt=moves_nfl(rows, NF) if NF else None, last=dict(week=lastwk, games=[final(r) for r in done if r["week"] == lastwk]),
                cfg=dict(c, pts=PTS["NFL"], test="2015 to %d seasons, every game priced before it was played, against the closing consensus spread and total" % (cur - 1)))


def nba_lines():
    """Closing DraftKings numbers per finished game, from nba_lines.py: {game id: (home spread as home-by, total, home ML, away ML)}."""
    out = {}
    f = O + "nba_lines.jsonl"
    if not os.path.exists(f):
        return out
    for ln in open(f):
        try:
            x = json.loads(ln)
        except ValueError:
            continue
        for v in x.get("pc") or []:
            if v.get("spread") is None:
                continue
            o = (v.get("oc") or {}).get("o") or [None, None]
            out[str(x["id"])] = (-float(v["spread"]), v.get("ou"), (v.get("h") or {}).get("ml"), (v.get("a") or {}).get("ml"),
                                 None if o[0] is None else -float(o[0]), o[1])
            break
    return out


INJ_BT = dict(th=8, moved=[326, 124], close=[287, 277], open=[311, 253], since="2025-11-24", to="2026-11-02",
              note="Games where one side was missing 8 or more points of Game Score value more than the other, from Sports Leader's injury files")


def injuries(lg):
    """This league's block of out/injuries.json when it is under 36 hours old, else {}."""
    try:
        x = json.load(open(O + "injuries.json"))[lg]
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.strptime(x["asof"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc)
        return x if age.total_seconds() < 36 * 3600 else {}
    except Exception:
        return {}


def inj_card(IJ, a, hm, lg):
    """Who is out on each side, and for the NBA which way the absences tilt the game (display only)."""
    if not IJ:
        return None
    t = IJ.get("t", {}); ea, eh = t.get(a, {}), t.get(hm, {})
    keep = (lambda q: q[2] >= 1.5) if lg == "NBA" else (lambda q: True)
    g = dict(a=[q for q in ea.get("p", []) if keep(q)][:3], h=[q for q in eh.get("p", []) if keep(q)][:3], src=IJ.get("src"), asof=IJ.get("asof"))
    if lg == "NBA":
        g["ma"], g["mh"] = ea.get("m", 0.0), eh.get("m", 0.0); dm = round(g["ma"] - g["mh"], 1); g["dm"] = dm
        g["tilt"] = (hm if dm > 0 else a) if abs(dm) >= INJ_BT["th"] else None
    return g if (g["a"] or g["h"] or g.get("tilt")) else dict(g, none=True)


def nba():
    c = CFG["NBA"]; LN = nba_lines(); IJ = injuries("NBA")
    d = pd.concat([pd.read_parquet(f"{D}nba_pb_{y}.parquet", columns=["game_id", "season", "season_type", "game_date", "team_abbreviation", "opponent_team_abbreviation",
                                                                     "home_away", "team_score", "opponent_team_score"]) for y in (2025, 2026, 2027)])
    d = d[d.season_type.isin([2, 3])].drop_duplicates(["game_id", "team_abbreviation"])
    h = d[d.home_away == "home"].rename(columns={"team_abbreviation": "home", "opponent_team_abbreviation": "away"})
    h["gd"] = pd.to_datetime(h.game_date); h = h.sort_values("gd").reset_index(drop=True)
    el, pp, last, rows = Elo(c), Pts(PTS["NBA"]), {}, []
    rest = lambda t, day: (day - last[t]).days - 1 if t in last else 3
    for r in h.itertuples():
        el.pre(r.home, r.season); el.pre(r.away, r.season); pp.pre(r.home, r.season); pp.pre(r.away, r.season)
        adj = c["b2b"] * ((rest(r.away, r.gd) == 0) - (rest(r.home, r.gd) == 0))
        dd = el.diff(r.home, r.away, adj=adj); res = float(r.team_score - r.opponent_team_score); ph, pa = pp.proj(r.home, r.away)
        ln = LN.get(str(int(r.game_id)))
        rows.append(dict(season=int(r.season), gid=str(int(r.game_id)), day=str(r.gd.date()), away=r.away, home=r.home, pm=dd / c["PPE"], pt=ph + pa, res=res,
                         spr=ln[0] if ln else None, tl=None if not ln or ln[1] is None else float(ln[1]), ml=(ln[2], ln[3]) if ln else None, sd=c["sd"],
                         op=ln[4] if ln else None, top=ln[5] if ln else None,
                         tot=float(r.team_score + r.opponent_team_score), sh=int(r.team_score), sa=int(r.opponent_team_score)))
        el.update(r.home, r.away, dd, res, False); pp.update(r.home, r.away, r.team_score, r.opponent_team_score); last[r.home] = last[r.away] = r.gd
    cur = int(h.season.max()); bt = score([r for r in rows if r["season"] >= 2026])
    sch = pd.read_parquet(D + "nba_sched_2027.parquet")
    sch["gd"] = sch.game_date.astype(str)
    up = sch[(sch.gd > str(h.gd.max().date())) & (sch.status_type_name == "STATUS_SCHEDULED")].sort_values("game_date_time")
    today = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")      # Eastern; a stale data day never lists a game already played
    up = up[up.gd >= today]
    days = sorted(up.gd.unique())[:3]; up = up[up.gd.isin(days)]
    rk = ranks(el.E, set(h[h.season == cur].home))
    mk = market_files("NBA"); games = []; HS = history("NBA")
    for r in up.itertuples():
        a, hm = r.away_abbreviation, r.home_abbreviation
        el.pre(hm, cur); el.pre(a, cur); pp.pre(hm, cur); pp.pre(a, cur)
        day = pd.Timestamp(r.gd)
        adj = c["b2b"] * ((rest(a, day) == 0) - (rest(hm, day) == 0))
        dd = el.diff(hm, a, adj=adj); ph, pa = pp.proj(hm, a)
        rq = (mk.get(f"{a}@{hm}|{r.gd}") or mk.get(f"{a}@{hm}")) if mk else None
        ts_et = pd.Timestamp(r.game_date_time)
        if ts_et.tzinfo is not None:
            ts_et = ts_et.tz_convert("America/New_York")
        row = dict(gid=str(r.game_id), day=r.gd, time=ts_et.strftime("%H:%M"), away=a, home=hm, pm=dd / c["PPE"], pt=ph + pa,
                   elo=(round(el.E[hm]), round(el.E[a])), rk=[rk.get(a), rk.get(hm)], rest=[min(rest(a, day), 3), min(rest(hm, day), 3)])
        g = pick("NBA", row, consensus(rq, a, hm) if rq else None, bt)
        g["b2b"] = [int(rest(a, day) == 0), int(rest(hm, day) == 0)]
        g["inj"] = inj_card(IJ, a, hm, "NBA")
        path = HS.get(f"{a}@{hm}|{r.gd}") or HS.get(f"{a}@{hm}", [])
        if path:
            g["mv"] = move(row["pm"], g.get("spread"), g.get("total"), path[0][1], path[0][2], path, "first pull " + path[0][0][5:])
        games.append(g)
    pd_ = sorted({r["day"] for r in rows if r["season"] == cur})[-2:]
    return dict(games=games, days=days, season=cur, bt=bt, this=score([r for r in rows if r["season"] == cur]), seasons=seasons(rows, 2026), mvbt=moves_nba(rows),
                last=dict(days=pd_, games=[final(r, "NBA") for r in rows if r["day"] in pd_]),
                cfg=dict(c, pts=PTS["NBA"], inj=INJ_BT, test="2025-26 and 2026-27 seasons, every game priced before it was played, against DraftKings' closing spread, total and moneylines where ESPN carries them"))


if __name__ == "__main__":
    res = {}
    for lg, f in (("NFL", nfl), ("NBA", nba)):
        try:
            res[lg] = f(); b = res[lg]["bt"]
            print(lg, "games", len(res[lg]["games"]), "| test", b.get("n"), "SU", b.get("su"), "MAE", b.get("mae"), "market MAE", b.get("mae_mkt"), "ATS", b.get("ats"),
                  "| total MAE", b.get("mae_tot"), "market", b.get("mae_tot_mkt"), "O/U", b.get("ou"))
        except Exception as e:
            print(lg, "game model failed:", e)
    json.dump(res, open(O + "games.json", "w"), separators=(",", ":"))

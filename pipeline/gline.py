"""The game price lane (v4.2): moneylines, spreads and totals, NFL and NBA. TRACKING ONLY. Nothing here is staked and
nothing here touches history.json, the prop desk or its pick policy.

The idea is price, not prediction. The books together are sharper than any ratings model we have (games.py: no weight on
our ratings improved on the closing number). So the lane asks one question of every Hard Rock game price: is it better than
the sharp-weighted fair price the rest of the market implies?
  1. Every other source that quotes the game (the six other sportsbooks, Pinnacle, Novig, Kalshi, and Polymarket when
     sharps.py has saved its prices) is turned into a fair number with the house cut removed: Power de-vig for sportsbook
     markets (eliminating favorite-longshot bias on heavy moneylines) and exact additive midpoint for binary exchanges.
  2. Spreads and totals are read through a score distribution (gline_dist.json, fitted by gline_fit.py on past results:
     whole-number margins with NFL key numbers and exact zero tie mass in NBA) so -2.5 and -3 can be compared.
     Each source's line and prices give the middle margin (or total) they imply; a sharpness-weighted median (logit space
     for moneylines) combines them, and Pinnacle agreement is checked when Pinnacle quotes.
  3. Hard Rock's own line and price are valued using push-adjusted unconditional EV per unit staked. A side clears when at
     least CFG min_books other sources quote the market, its value is within [min_ev, max_ev], the price sits inside the
     price window, and sharp consensus does not disagree.
Every Hard Rock side on a game day goes into the audit (out/gaudit.json, with per-book src snapshots) and is graded so the
fair number itself can be scored by game-clustered paired log-loss and Brier. Sides that clear go into the shadow book
(out/gshadow.json), receive closing numbers on evening/close/lineups pulls, and are graded flat, one unit each.
v4.1/4.2 lanes:
  - Most likely lane (out/glikely.json): at most one side a game with unconditional win chance >= 60% and EV >= 1.5%
    (best EV among qualifying sides), shadow-tracked separately from the promotion test.
  - Florida exchange shadow book (out/gfl.json): tracks executable Novig and Kalshi sides under the same rules, 0 extra credits.
  - Trust strip (calib_bins): one canonical side per market (favorite / p >= 0.50) with Wilson 95% CIs.
  - Promotion gate (CFG promote): requires 200+ graded sides, 200+ closed sides, game-clustered t_CLV >= 2.0, mean CLV >= +0.5%,
    beat-close >= 50%, and z_ROI >= -2.0.

Commands:  python3 gline.py log <date> | close <date> | grade | report | show <date> | summary <file>
Files read: out/games/{LG}_{date}[_pm|_close*|_late].txt (relay), out/poly/{LG}_{date}.txt (sharps.py),
out/games.json (ids, days, our ratings), out/sharps/{date}.json (Polymarket wallet flow, a tracked note only)."""
import json, math, os, glob, sys, datetime
from zoneinfo import ZoneInfo
import numpy as np

D = os.environ.get("FL_DATA", "/home/claude/props/data/")
O = os.environ.get("FL_OUT", "/home/claude/props/out/")
HERE = os.path.dirname(os.path.abspath(__file__)) + "/"
ET = ZoneInfo("America/New_York")
VER = "1.2"
EXCHANGES = frozenset(("polymarket", "kalshi", "novig"))
CFG = dict(
    bet_book="hardrockbet",            # primary Florida sportsbook priced against the rest of the market
    fl_books=("novig", "kalshi"),      # v4.2 secondary FL-executable venues shadow-tracked in out/gfl.json (0 extra credits)
    min_books=4,                       # other sources that must quote the same market with both prices
    min_ev=0.02, max_ev=0.08,          # true per-unit EV band (push-adjusted)
    ml_px=(-400, 300),                 # moneyline price window; spreads and totals use sp_px
    sp_px=(-135, 125),
    sane=(0.995, 1.12),                # v4.2: 0.995 avoids IEEE-754 float drops on exact zero-vig exchange pairs (-107/+107)
    book_w=dict(pinnacle=3.0, betonlineag=2.0, lowvig=2.0, fanduel=1.75, draftkings=1.75,
                novig=1.5, betmgm=1.0, williamhill_us=1.0, betrivers=0.85, fanatics=0.85,
                kalshi=0.5, polymarket=0.5),
    sharp_ref="pinnacle",              # when Pinnacle quotes, require non-negative EV vs Pinnacle to avoid soft-book lag traps
    w_model={"NFL": 0.0, "NBA": 0.0},  # weight on our own ratings. 0 until walk-forward earns more
    likely=dict(p=0.60, ev=0.015),     # v4.2: unconditional P(win) >= 60% AND EV >= +1.5%, best EV per game
    nfl_days=7,                        # NFL sides may be logged up to this many days before kickoff, once
    void_days=14,                      # open sides older than this with no final score are voided (postponed/cancelled)
    promote=dict(n=200, clv_n=200, clv=0.005, t_clv=2.0, beat=0.50, z_roi=-2.0))
MK = ("h2h", "spreads", "totals")
NAME = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}


def dec(a):
    if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(a) or abs(a) < 100:
        raise ValueError(f"invalid American odds: {a!r}")
    return 1.0 + a / 100.0 if a > 0 else 1.0 + 100.0 / -a


def _logit(p):
    p = min(max(float(p), 1e-5), 1.0 - 1e-5)
    return math.log(p / (1.0 - p))


def _sig(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def power_devig(pa, pb):
    """Solve pa^k + pb^k = 1 for k > 0 and return pa^k (removes favorite-longshot bias)."""
    s = pa + pb
    if s <= 1.0 + 1e-9:
        return min(max(pa / s, 1e-5), 1.0 - 1e-5)
    lo, hi = 1.0, 20.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if pa ** mid + pb ** mid > 1.0:
            lo = mid
        else:
            hi = mid
    k = 0.5 * (lo + hi)
    return min(max(pa ** k, 1e-5), 1.0 - 1e-5)


def wmedian(vals, weights):
    """Weighted median (exact interpolation at 0.5 total weight)."""
    if not vals:
        return None
    pairs = sorted(zip(vals, weights), key=lambda x: x[0])
    tot = sum(w for _, w in pairs)
    if tot <= 0:
        return float(np.median([v for v, _ in pairs]))
    half = 0.5 * tot
    acc = 0.0
    for i, (v, w) in enumerate(pairs):
        acc += w
        if abs(acc - half) < 1e-12 and i + 1 < len(pairs):
            return 0.5 * (v + pairs[i + 1][0])
        if acc >= half:
            return float(v)
    return float(pairs[-1][0])


def load_dist():
    try:
        with open(HERE + "gline_dist.json", encoding="utf-8") as f:
            DS = json.load(f)
        for lg in ("NFL", "NBA"):
            if lg not in DS or "sd" not in DS[lg] or "tsd" not in DS[lg]:
                raise KeyError(f"missing {lg} params")
        return DS
    except Exception as e:
        raise RuntimeError(f"gline_dist.json unreadable: {e}") from None


class Dist:
    """Whole-number final margins (home minus away) or totals around a middle value mu. Margins carry key-number weights."""
    def __init__(self, sd, keys=None, lo=-90, hi=90):
        if not isinstance(sd, (int, float)) or not math.isfinite(sd) or sd <= 0:
            raise ValueError(f"invalid sd: {sd!r}")
        self.sd = max(float(sd), 0.5)
        self.k = np.arange(lo, hi + 1)
        self.w = np.ones(len(self.k), dtype=float)
        for a, m in (keys or {}).items():
            self.w[np.abs(self.k) == int(a)] = max(float(m), 0.0)

    def pmf(self, mu):
        z = -0.5 * ((self.k - float(mu)) / self.sd) ** 2
        z -= z.max()                                       # log-sum-exp guard against underflow at extreme mu
        p = np.exp(z) * self.w
        tot = p.sum()
        if not math.isfinite(tot) or tot <= 0:
            p = np.where(self.w > 0, 1.0, 0.0)
            tot = p.sum()
        return p / tot

    def over(self, mu, line):
        """Conditional P(win | no push) and P(push) at line."""
        p = self.pmf(mu)
        win = float(p[self.k > line + 1e-9].sum())
        push = float(p[np.abs(self.k - line) < 1e-9].sum())
        return (win / (1.0 - push) if push < 1.0 - 1e-12 else 0.5), push

    def solve(self, line, p_over):
        """Middle value mu at which this line pays p_over (push removed). Bisection; strictly increasing in mu."""
        p_over = min(max(float(p_over), 1e-6), 1.0 - 1e-6)
        lo = min(float(self.k[0]), float(line)) - 5.0 * self.sd
        hi = max(float(self.k[-1]), float(line)) + 5.0 * self.sd
        for _ in range(52):
            mid = 0.5 * (lo + hi)
            if self.over(mid, line)[0] < p_over:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


def dists(lg, DS=None):
    d = (DS or load_dist())[lg]
    return Dist(d["sd"], d.get("keys")), Dist(d["tsd"], None, lo=0, hi=int(d.get("tmax", 400)))


def _parse_et(stamp):
    if not stamp:
        return None
    s = str(stamp).strip().replace(" ET", "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).replace(tzinfo=ET)
        except ValueError:
            continue
    return None


def parse(path, into=None):
    """Parse a relay/poly game-odds file into {key: {'away', 'home', 'tip', 'q': {bk: {mk: {name: (pt, px)}}}}}.
    v4.2: keys games by 'AWAY@HOME|YYYY-MM-DD' when tip date is known so back-to-back NBA mini-series never overwrite."""
    out = {} if into is None else into
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return out

    # Index existing entries by matchup for tip-less secondary files (e.g. legacy poly files without # tip:)
    by_matchup = {}
    for k, v in out.items():
        if k == "_asof" or not isinstance(v, dict):
            continue
        m_key = f"{v.get('away')}@{v.get('home')}" if v.get("away") else k.split("|", 1)[0]
        by_matchup.setdefault(m_key, []).append(k)

    blocks = []
    cur = None
    for raw in lines:
        ln = raw.strip()
        if ln.startswith("# relay pulled"):
            out.setdefault("_asof", ln[2:].split(",")[0].replace("relay pulled ", "").strip())
            continue
        if ln.startswith("# game:"):
            gstr = ln.split(":", 1)[1].strip().replace(" ", "")
            if "@" not in gstr:
                cur = None
                continue
            parts = gstr.split("@")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                cur = None
                continue
            cur = dict(away=parts[0], home=parts[1], tip=None, rows=[])
            blocks.append(cur)
            continue
        if ln.startswith("# tip:") and cur is not None:
            tstr = ln.split(":", 1)[1].strip().replace(" ET", "")
            if _parse_et(tstr) is not None:
                cur["tip"] = tstr
            continue
        if not ln or ln.startswith("#") or "|" not in ln or ln.startswith("bookmaker_key") or cur is None:
            continue
        bk, mk, name, pt_s, px_s = (ln.split("|") + [""] * 5)[:5]
        if mk not in MK or not bk or not name:
            continue
        try:
            px = float(px_s)
            pt = float(pt_s) if pt_s != "" else None
        except ValueError:
            continue
        if not (math.isfinite(px) and abs(px) >= 100):
            continue
        if pt is not None and not math.isfinite(pt):
            continue
        cur["rows"].append((bk, mk, name, pt, px))

    for blk in blocks:
        m_key = f"{blk['away']}@{blk['home']}"
        tipday = blk["tip"][:10] if blk["tip"] else ""
        if tipday:
            gkey = f"{m_key}|{tipday}"
        elif m_key in by_matchup:
            gkey = by_matchup[m_key][0]
        else:
            gkey = m_key
        slot = out.setdefault(gkey, dict(away=blk["away"], home=blk["home"], tip=blk["tip"], q={}))
        if blk["tip"] and not slot.get("tip"):
            slot["tip"] = blk["tip"]
        for bk, mk, name, pt, px in blk["rows"]:
            slot["q"].setdefault(bk, {}).setdefault(mk, {})[name] = (pt, px)
        if gkey not in by_matchup.get(m_key, []):
            by_matchup.setdefault(m_key, []).append(gkey)
    return out


def pair(m, a, b, bk=None, mk=None):
    """Both sides of one source's market, or None. Checks finite matched lines, sane overround, and de-vigs cleanly."""
    if a not in m or b not in m:
        return None
    pa_pt, pa_px = m[a]
    pb_pt, pb_px = m[b]
    try:
        da, db = dec(pa_px), dec(pb_px)
    except ValueError:
        return None
    if mk == "spreads":
        if pa_pt is None or pb_pt is None or not (math.isfinite(pa_pt) and math.isfinite(pb_pt)):
            return None
        if abs(pa_pt + pb_pt) > 1e-6:
            return None
    elif mk == "totals":
        if pa_pt is None or pb_pt is None or not (math.isfinite(pa_pt) and math.isfinite(pb_pt)):
            return None
        if abs(pa_pt - pb_pt) > 1e-6:
            return None
    ia, ib = 1.0 / da, 1.0 / db
    s = ia + ib
    if not (CFG["sane"][0] <= s <= CFG["sane"][1]):
        return None
    if bk in EXCHANGES:
        p = min(max(ia - 0.5 * (s - 1.0), 1e-4), 1.0 - 1e-4)  # exact midpoint for additive binary orderbooks
    else:
        p = power_devig(ia, ib)                                 # power de-vig removes favorite-longshot bias
    return m[a], m[b], p


def _book_weight(bk):
    return float(CFG["book_w"].get(bk, 1.0))


def fair(lg, away, home, q, model=None, DS=None, exclude=None):
    """Market fair numbers for one game from every source except `exclude` (default bet_book):
    sharpness-weighted logit median for h2h, weighted median for spreads/totals."""
    ex = CFG["bet_book"] if exclude is None else exclude
    dm, dt = dists(lg, DS)
    pw, pw_w = [], []
    mu, mu_w = [], []
    tt, tt_w = [], []
    src = {}
    for bk, m in q.items():
        if bk == ex:
            continue
        w = _book_weight(bk)
        s = src.setdefault(bk, {})
        x = pair(m.get("h2h", {}), home, away, bk=bk, mk="h2h")
        if x:
            pw.append(_logit(x[2])); pw_w.append(w); s["p"] = round(x[2], 4)
        x = pair(m.get("spreads", {}), home, away, bk=bk, mk="spreads")
        if x and x[0][0] is not None:
            v = dm.solve(-x[0][0], x[2]); mu.append(v); mu_w.append(w); s["mu"] = round(v, 2)
        x = pair(m.get("totals", {}), "Over", "Under", bk=bk, mk="totals")
        if x and x[0][0] is not None:
            v = dt.solve(x[0][0], x[2]); tt.append(v); tt_w.append(w); s["t"] = round(v, 2)
    f = dict(
        p=_sig(wmedian(pw, pw_w)) if pw else None,
        mu=wmedian(mu, mu_w) if mu else None,
        t=wmedian(tt, tt_w) if tt else None,
        n=dict(h2h=len(pw), spreads=len(mu), totals=len(tt)),
        src={k: v for k, v in src.items() if v},
    )
    wm = CFG["w_model"].get(lg, 0.0)
    if wm and model:
        if f["mu"] is not None and model.get("pm") is not None:
            f["mu"] += wm * (model["pm"] - f["mu"])
        if f["t"] is not None and model.get("pt") is not None:
            f["t"] += wm * (model["pt"] - f["t"])
    return f


def _pin_prob(mk, side, line, home, f, dm, dt):
    """Pinnacle's (or sharp_ref's) implied conditional probability and push chance for this side, or (None, None)."""
    ref = f["src"].get(CFG["sharp_ref"])
    if not ref:
        return None, None
    if mk == "h2h" and ref.get("p") is not None:
        return (ref["p"] if side == home else 1.0 - ref["p"]), 0.0
    if mk == "spreads" and ref.get("mu") is not None and line is not None:
        hl = line if side == home else -line
        ph, push = dm.over(ref["mu"], -hl)
        return (ph if side == home else 1.0 - ph), push
    if mk == "totals" and ref.get("t") is not None and line is not None:
        po, push = dt.over(ref["t"], line)
        return (po if side == "Over" else 1.0 - po), push
    return None, None


def sides(lg, away, home, q, f, DS=None, book=None):
    """Every side `book` (default bet_book) posts on the game, valued at the market's fair chance (push-adjusted)."""
    bk = CFG["bet_book"] if book is None else book
    dm, dt = dists(lg, DS)
    hb = q.get(bk, {})
    out = []

    def add(mk, side, line, px, p_cond, push=0.0):
        try:
            d = dec(px)
        except ValueError:
            return
        p_win = p_cond * (1.0 - push)
        ev = (1.0 - push) * (p_cond * d - 1.0)                 # exact unconditional EV per 1 unit staked
        p_ref, push_ref = _pin_prob(mk, side, line, home, f, dm, dt)
        pin_ev = None if p_ref is None else (1.0 - push_ref) * (p_ref * d - 1.0)
        lo, hi = CFG["ml_px" if mk == "h2h" else "sp_px"]
        why = None
        if f["n"][mk] < CFG["min_books"]:
            why = "too few other sources"
        elif not (lo <= px <= hi):
            why = "price outside the window"
        elif ev > CFG["max_ev"]:
            why = "gap too wide, check news"
        elif ev < CFG["min_ev"]:
            why = "no value at this price"
        elif pin_ev is not None and pin_ev < 0.0:
            why = "Pinnacle disagrees"
        lk = (
            f["n"][mk] >= CFG["min_books"]
            and lo <= px <= hi
            and p_win >= CFG["likely"]["p"]
            and CFG["likely"]["ev"] <= ev <= CFG["max_ev"]
            and (pin_ev is None or pin_ev >= 0.0)
        )
        out.append(dict(
            mkt=mk, side=side, line=line, px=px,
            p=round(p_cond, 4), p_win=round(p_win, 4), push=round(push, 4),
            be=round(1.0 / d, 4), ev=round(ev, 4),
            pin_ev=None if pin_ev is None else round(pin_ev, 4),
            nb=f["n"][mk], ok=why is None, why=why, lk=bool(lk),
        ))

    m = hb.get("h2h", {})
    if f["p"] is not None and home in m and away in m:
        add("h2h", home, None, m[home][1], f["p"])
        add("h2h", away, None, m[away][1], 1.0 - f["p"])
    m = hb.get("spreads", {})
    if f["mu"] is not None and home in m and away in m:
        lh, la = m[home][0], m[away][0]
        if lh is not None and la is not None and math.isfinite(lh) and math.isfinite(la) and abs(lh + la) <= 1e-6:
            ph, push = dm.over(f["mu"], -lh)
            add("spreads", home, lh, m[home][1], ph, push)
            add("spreads", away, la, m[away][1], 1.0 - ph, push)
    m = hb.get("totals", {})
    if f["t"] is not None and "Over" in m and "Under" in m:
        lo_pt, lu_pt = m["Over"][0], m["Under"][0]
        if lo_pt is not None and lu_pt is not None and math.isfinite(lo_pt) and math.isfinite(lu_pt) and abs(lo_pt - lu_pt) <= 1e-6:
            po, push = dt.over(f["t"], lo_pt)
            add("totals", "Over", lo_pt, m["Over"][1], po, push)
            add("totals", "Under", lu_pt, m["Under"][1], 1.0 - po, push)
    return out


def _pulled(path):
    """When a relay game file was pulled, read from its own first line ('# relay pulled YYYY-MM-DD HH:MM ET')."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for _ in range(3):
                ln = f.readline().strip()
                if ln.startswith("# relay pulled"):
                    return _parse_et(ln[2:].split(",")[0].replace("relay pulled ", "").strip())
    except OSError:
        pass
    return None


def files(lg, date):
    """The newest relay game file for the date, by the pull time written in each file (never the file system's clock).
    v4.2 review fix: a fixed order (_late, _close, _pm, midday) made the Sunday 6 PM run read the 12:30 PM file.
    A file with no readable time ranks below every dated one; ties fall back to late > pm > close > midday.
    Also returns Polymarket's prices file path."""
    rank = {"late": 3, "pm": 2, "close": 1, "mid": 0}
    cands = [(O + f"games/{lg}_{date}_late.txt", "late"), (O + f"games/{lg}_{date}_pm.txt", "pm"), (O + f"games/{lg}_{date}.txt", "mid")]
    cands += [(p, "close") for p in glob.glob(O + f"games/{lg}_{date}_close*.txt")]
    cands = [(p, k) for p, k in cands if os.path.exists(p)]
    if not cands:
        return None, None
    floor = datetime.datetime(1970, 1, 1, tzinfo=ET)
    best = max(cands, key=lambda c: (_pulled(c[0]) or floor, rank[c[1]], c[0]))
    return best[0], O + f"poly/{lg}_{date}.txt"


def _flip_quotes(q, old_away, old_home):
    """Flip neutral-site quotes when feed lists (old_away @ old_home) opposite to schedule (home @ away)."""
    # Quotes are already keyed by team code (h2h/spreads) or Over/Under (totals), so swapping labels doesn't change keys!
    return q


def slate(lg, date, DS=None):
    """Every pre-tip game in today's pull, priced: [{id, day, time, away, home, fair, sides, q}], and the pull's time."""
    main, poly = files(lg, date)
    if not main:
        return [], None
    Q = parse(main)
    asof = Q.pop("_asof", None)
    parse(poly, Q)
    Q.pop("_asof", None)
    asof_dt = _parse_et(asof)
    G = jl(O + "games.json", {})
    byk = {}
    for g in (G.get(lg) or {}).get("games", []):
        byk.setdefault((g["away"], g["home"]), []).append(g)

    # Merge any neutral-site reverse entries pointing to the same scheduled game
    merged = {}
    for key, v in Q.items():
        if not isinstance(v, dict) or not v.get("away") or not v.get("home"):
            continue
        away, home = v["away"], v["home"]
        tip_str = v.get("tip")
        tip_dt = _parse_et(tip_str)
        if asof_dt is not None and tip_dt is not None and asof_dt >= tip_dt:
            continue                                       # v4.2 in-play guard: never price or close live/finished games
        tipday = (tip_str or "")[:10]
        c = byk.get((away, home), [])
        flipped = False
        if not c:
            rev = byk.get((home, away), [])
            if rev:
                c = rev
                flipped = True
        if not c:
            continue
        c = sorted(c, key=lambda g: abs((datetime.date.fromisoformat(g["day"]) - datetime.date.fromisoformat(tipday or g["day"])).days))
        g = c[0]
        if tipday and abs((datetime.date.fromisoformat(g["day"]) - datetime.date.fromisoformat(tipday)).days) > 1:
            continue
        gid = str(g["id"])
        slot = merged.setdefault(gid, dict(g=g, tip=tip_str, q={}))
        if tip_str and not slot["tip"]:
            slot["tip"] = tip_str
        qq = _flip_quotes(v["q"], away, home) if flipped else v["q"]
        for bk, mkd in qq.items():
            for mk, mp in mkd.items():
                slot["q"].setdefault(bk, {}).setdefault(mk, {}).update(mp)

    out = []
    for gid, item in merged.items():
        g = item["g"]
        away, home = g["away"], g["home"]
        f = fair(lg, away, home, item["q"], model=g, DS=DS)
        out.append(dict(
            lg=lg, id=gid, day=g["day"], time=g.get("time"), away=away, home=home, tip=item["tip"],
            fair=f, sides=sides(lg, away, home, item["q"], f, DS),
            hr=bool(item["q"].get(CFG["bet_book"])), q=item["q"],
        ))
    return out, asof


def sharp_note(date, lg, key, mkt, side):
    try:
        with open(O + f"sharps/{date}.json", encoding="utf-8") as f:
            x = json.load(f)[lg][key][mkt]
        return x.get(side)
    except Exception:
        return None


def jl(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jd(path, x):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(x, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)


def _eval_close_on_book(path, SL):
    """Apply latest pre-tip closing numbers to any open side in `path`."""
    S = jl(path, [])
    n = 0
    for x in S:
        if x.get("status") != "open" or x.get("lg") not in SL:
            continue
        by, asof, (dm, dt) = SL[x["lg"]]
        g = by.get(x["id"])
        if g is None or asof is None or asof == x.get("asof"):
            continue
        bk = x.get("book") or CFG["bet_book"]
        f = g["fair"] if bk == CFG["bet_book"] else fair(x["lg"], x["away"], x["home"], g["q"], DS=None, exclude=bk)
        p, push = None, 0.0
        if x["mkt"] == "h2h" and f["p"] is not None:
            p = f["p"] if x["side"] == x["home"] else 1.0 - f["p"]
        elif x["mkt"] == "spreads" and f["mu"] is not None and x.get("line") is not None:
            hl = x["line"] if x["side"] == x["home"] else -x["line"]
            ph, push = dm.over(f["mu"], -hl)
            p = ph if x["side"] == x["home"] else 1.0 - ph
        elif x["mkt"] == "totals" and f["t"] is not None and x.get("line") is not None:
            po, push = dt.over(f["t"], x["line"])
            p = po if x["side"] == "Over" else 1.0 - po
        if p is None:
            continue
        try:
            d = dec(x["px"])
        except ValueError:
            continue
        clv = (1.0 - push) * (d * p - 1.0)
        p_ref, push_ref = _pin_prob(x["mkt"], x["side"], x.get("line"), x["home"], f, dm, dt)
        pin_clv = None if p_ref is None else round((1.0 - push_ref) * (d * p_ref - 1.0), 4)
        book_sides = g["sides"] if bk == CFG["bet_book"] else sides(x["lg"], x["away"], x["home"], g["q"], f, book=bk)
        now = next((s for s in book_sides if s["mkt"] == x["mkt"] and s["side"] == x["side"]), None)
        x["close"] = dict(
            asof=asof, p=round(p, 4), push=round(push, 4), clv=round(clv, 4), pin_clv=pin_clv,
            line=None if not now else now["line"], px=None if not now else now["px"],
        )
        n += 1
    if S:
        jd(path, S)
    return n


def cmd_log(date):
    """Midday. File today's Hard Rock sides in the audit (with per-book src), clearing Hard Rock sides in gshadow.json,
    best-EV >=60% favorites in glikely.json, and executable Novig/Kalshi sides in gfl.json."""
    A = jl(O + "gaudit.json", [])
    S = jl(O + "gshadow.json", [])
    K = jl(O + "glikely.json", [])
    F = jl(O + "gfl.json", [])
    DS = load_dist()
    ha = {(x["lg"], x["id"], x["mkt"], x["side"]) for x in A}
    hs = {(x["lg"], x["id"], x["mkt"]) for x in S}
    hk = {(x["lg"], x["id"]) for x in K}
    hf = {(x.get("book"), x["lg"], x["id"], x["mkt"]) for x in F}
    end = (datetime.date.fromisoformat(date) + datetime.timedelta(days=CFG["nfl_days"])).isoformat()
    na = ns = nk = nf = 0
    card = {}
    for lg in ("NBA", "NFL"):
        games, asof = slate(lg, date, DS)
        card[lg] = dict(asof=asof, games=games)
        for g in games:
            base = dict(lg=lg, id=g["id"], date=date, day=g["day"], away=g["away"], home=g["home"], asof=asof)
            f = g["fair"]
            for s in g["sides"]:
                if g["day"] == date and (lg, g["id"], s["mkt"], s["side"]) not in ha:
                    A.append(dict(
                        base, mkt=s["mkt"], side=s["side"], line=s["line"], px=s["px"], p=s["p"],
                        push=s["push"], ev=s["ev"], nb=s["nb"], src=f["src"], status="open",
                    ))
                    ha.add((lg, g["id"], s["mkt"], s["side"]))
                    na += 1
            ok = (g["day"] == date) if lg == "NBA" else (date <= g["day"] < end)
            for mk in MK:
                c = [s for s in g["sides"] if s["mkt"] == mk and s["ok"]]
                if not ok or not c or (lg, g["id"], mk) in hs:
                    continue
                s = max(c, key=lambda s: s["ev"])
                S.append(dict(
                    base, mkt=mk, side=s["side"], line=s["line"], px=s["px"], p=s["p"], p_win=s["p_win"],
                    push=s["push"], ev=s["ev"], pin_ev=s["pin_ev"], nb=s["nb"],
                    mu=None if f["mu"] is None else round(f["mu"], 2),
                    t=None if f["t"] is None else round(f["t"], 2),
                    pin=(f["src"].get("pinnacle") or None), poly=(f["src"].get("polymarket") or None),
                    sharp=sharp_note(date, lg, g["away"] + "@" + g["home"], mk, s["side"]),
                    ver=VER, status="open",
                ))
                hs.add((lg, g["id"], mk))
                ns += 1
            # v4.2 Most Likely lane: unconditional P(win) >= 60%, EV >= 1.5%, best EV per game
            c = [s for s in g["sides"] if s.get("lk")]
            if ok and c and (lg, g["id"]) not in hk:
                s = max(c, key=lambda s: (s["ev"], s["p_win"]))
                K.append(dict(
                    base, mkt=s["mkt"], side=s["side"], line=s["line"], px=s["px"], p=s["p"],
                    p_win=s["p_win"], push=s["push"], ev=s["ev"], nb=s["nb"], ver=VER, status="open",
                ))
                hk.add((lg, g["id"]))
                nk += 1
            # v4.2 FL multi-venue shadow tracking (Novig & Kalshi — already pulled at 0 extra credits)
            if ok:
                for fb in CFG["fl_books"]:
                    if fb not in g["q"]:
                        continue
                    ff = fair(lg, g["away"], g["home"], g["q"], DS=DS, exclude=fb)
                    fsides = sides(lg, g["away"], g["home"], g["q"], ff, DS=DS, book=fb)
                    for mk in MK:
                        fc = [s for s in fsides if s["mkt"] == mk and s["ok"]]
                        if not fc or (fb, lg, g["id"], mk) in hf:
                            continue
                        s = max(fc, key=lambda s: s["ev"])
                        F.append(dict(
                            base, book=fb, mkt=mk, side=s["side"], line=s["line"], px=s["px"], p=s["p"],
                            p_win=s["p_win"], push=s["push"], ev=s["ev"], pin_ev=s["pin_ev"], nb=s["nb"],
                            ver=VER, status="open",
                        ))
                        hf.add((fb, lg, g["id"], mk))
                        nf += 1
    jd(O + "gaudit.json", A)
    jd(O + "gshadow.json", S)
    jd(O + "glikely.json", K)
    if F:
        jd(O + "gfl.json", F)
    write_card(date, card)
    print(f"game price lane: {na} sides audited, {ns} cleared into the shadow book, {nk} into most likely, {nf} FL exchanges ({date})")
    cmd_close(date)


def cmd_close(date):
    """Evening / Sunday close / NBA lineups. Give every open side its latest pre-tip closing number."""
    DS = load_dist()
    n = 0
    card = {}
    SL = {}
    for lg in ("NBA", "NFL"):
        games, asof = slate(lg, date, DS)
        card[lg] = dict(asof=asof, games=games)
        SL[lg] = ({g["id"]: g for g in games}, asof, dists(lg, DS))
    for path in (O + "gshadow.json", O + "glikely.json", O + "gfl.json"):
        if os.path.exists(path):
            n += _eval_close_on_book(path, SL)
    write_card(date, card)
    print(f"game price lane: closing numbers on {n} open sides ({date})")


def results():
    """Load final scores independently per league so a missing NBA or NFL file never blocks grading the other."""
    import pandas as pd
    res = {}
    nfl_p = D + "nfl_games.csv"
    if os.path.exists(nfl_p):
        try:
            s = pd.read_csv(nfl_p, low_memory=False)
            s = s[s.result.notna() & s.home_score.notna() & s.away_score.notna()]
            for r in s.itertuples():
                m, tot = float(r.result), float(r.home_score + r.away_score)
                if math.isfinite(m) and math.isfinite(tot):
                    res[("NFL", str(r.game_id))] = (m, tot)
        except Exception as e:
            print("game price lane: NFL results not read:", e)
    nba_files = sorted(glob.glob(D + "nba_pb_*.parquet"))
    if nba_files:
        try:
            b = pd.read_parquet(nba_files[-1], columns=["game_id", "home_away", "team_score", "opponent_team_score"]).drop_duplicates(["game_id", "home_away"])
            b = b[(b.home_away == "home") & b.team_score.notna() & b.opponent_team_score.notna()]
            for r in b.itertuples():
                hs, as_ = float(r.team_score), float(r.opponent_team_score)
                if math.isfinite(hs) and math.isfinite(as_):
                    res[("NBA", str(int(r.game_id)))] = (hs - as_, hs + as_)
        except Exception as e:
            print("game price lane: NBA results not read:", e)
    return res


def settle(x, m, tot):
    """1 won, 0 lost, None push. Margin m is home minus away. Rejects NaN/Inf scores."""
    if not (isinstance(m, (int, float)) and isinstance(tot, (int, float)) and math.isfinite(m) and math.isfinite(tot)):
        raise ValueError(f"non-finite score: m={m!r}, tot={tot!r}")
    if x["mkt"] == "h2h":
        return None if m == 0 else int((m > 0) == (x["side"] == x["home"]))
    if x["mkt"] == "spreads":
        c = (m if x["side"] == x["home"] else -m) + x["line"]
        return None if abs(c) < 1e-9 else int(c > 0)
    c = tot - x["line"]
    return None if abs(c) < 1e-9 else int((c > 0) == (x["side"] == "Over"))


def cmd_grade():
    R = results()
    today = datetime.datetime.now(ET).date()
    void_cut = (today - datetime.timedelta(days=CFG["void_days"])).isoformat()
    n = v = 0
    for path in (O + "gaudit.json", O + "gshadow.json", O + "glikely.json", O + "gfl.json"):
        if not os.path.exists(path):
            continue
        X = jl(path, [])
        changed = False
        for x in X:
            if x.get("status") != "open":
                continue
            key = (x["lg"], x["id"])
            if key in R:
                m, tot = R[key]
                w = settle(x, m, tot)
                x["margin"] = m
                x["tot"] = tot
                x["won"] = w
                x["status"] = "push" if w is None else ("won" if w else "lost")
                x["units"] = 0.0 if w is None else (round(dec(x["px"]) - 1.0, 4) if w else -1.0)
                n += 1
                changed = True
            elif x.get("day") and x["day"] < void_cut:
                x["won"] = None
                x["status"] = "void"
                x["units"] = 0.0
                v += 1
                changed = True
        if changed:
            jd(path, X)
    # v4.2: refresh out/gline.json immediately after grading so morning early builds never show yesterday's open counts
    if os.path.exists(O + "gline.json"):
        refresh_card(today.isoformat())
    print(f"game price lane: {n} sides graded" + (f", {v} expired void" if v else ""))


def _clustered_t(items, val_fn):
    """One-sample t-statistic clustering correlated sides on the same game (lg, id)."""
    by = {}
    for x in items:
        by.setdefault((x["lg"], x["id"]), []).append(float(val_fn(x)))
    if len(by) < 2:
        return None
    mu = float(np.mean([v for vs in by.values() for v in vs]))
    n_tot = sum(len(vs) for vs in by.values())
    G = len(by)
    # Cluster-robust variance of the sample mean: (G/(G-1)) * sum_g (sum_i (y_gi - mu))^2 / N^2
    s2 = sum((sum(v - mu for v in vs)) ** 2 for vs in by.values())
    se = math.sqrt((G / (G - 1.0)) * s2) / n_tot
    if se <= 1e-12:
        return 0.0 if abs(mu) < 1e-12 else (99.0 if mu > 0 else -99.0)
    return round(mu / se, 3)


def record(S):
    active = [x for x in S if x.get("status") != "void"]
    g = [x for x in active if x.get("status") in ("won", "lost")]
    settled = [x for x in active if x.get("status") in ("won", "lost", "push")]
    c = [x for x in active if x.get("close")]
    w = sum(x["won"] for x in g)
    return dict(
        n=len(active),
        open=sum(x.get("status") == "open" for x in active),
        graded=len(g),
        w=w, l=len(g) - w,
        push=sum(x.get("status") == "push" for x in active),
        void=sum(x.get("status") == "void" for x in S),
        units=round(sum(x["units"] for x in settled), 2),
        roi=round(float(np.mean([x["units"] for x in settled])), 4) if settled else None,
        z_roi=_clustered_t(settled, lambda x: x["units"]) if len(settled) >= 2 else None,
        ev=round(float(np.mean([x["ev"] for x in active])), 4) if active else None,
        clv_n=len(c),
        clv=round(float(np.mean([x["close"]["clv"] for x in c])), 4) if c else None,
        t_clv=_clustered_t(c, lambda x: x["close"]["clv"]) if len(c) >= 2 else None,
        beat=round(float(np.mean([x["close"]["clv"] > 0 for x in c])), 4) if c else None,
    )


def promotion(S):
    """v4.2 CLV-first promotion gate with game-clustered t-stat & clv_n floor (cuts zero-edge FPR from 32.5% to ~2%)."""
    r = record(S)
    P = CFG["promote"]
    checks = [
        ("graded sides", r["graded"], P["n"], r["graded"] >= P["n"]),
        ("closed sides", r["clv_n"], P["clv_n"], r["clv_n"] >= P["clv_n"]),
        ("average closing line value", r["clv"], P["clv"], r["clv"] is not None and r["clv"] >= P["clv"]),
        ("clustered CLV t-stat", r["t_clv"], P["t_clv"], r["t_clv"] is not None and r["t_clv"] >= P["t_clv"]),
        ("share that beat the close", r["beat"], P["beat"], r["beat"] is not None and r["beat"] >= P["beat"]),
        ("ROI z-score guard", r["z_roi"], P["z_roi"], r["z_roi"] is not None and r["z_roi"] >= P["z_roi"]),
    ]
    return dict(met=all(c[3] for c in checks), checks=[dict(name=a, have=b, need=c, ok=d) for a, b, c, d in checks])


def _canonical_audit(A):
    """One canonical side per graded (lg, id, mkt) — eliminates 2x sample inflation & the 50/50 middle-bin tautology."""
    by = {}
    for x in A:
        if x.get("status") in ("won", "lost"):
            by.setdefault((x["lg"], x["id"], x["mkt"]), []).append(x)
    out = []
    for v in by.values():
        # Pick the market's favorite (highest p); break ties deterministically on home / Over
        v_sorted = sorted(v, key=lambda x: (x["p"], x["side"] in (x["home"], "Over")), reverse=True)
        out.append(v_sorted[0])
    return out


def _wilson(k, n, z=1.96):
    if not n:
        return None, None
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / denom
    return round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)


def audit_score(A):
    """Score the fair number vs Hard Rock's own power-devigged probability: paired Log-Loss & Brier (1 side per market)."""
    g = [x for x in A if x.get("status") in ("won", "lost")]
    if not g:
        return None
    by = {}
    for x in g:
        by.setdefault((x["lg"], x["id"], x["mkt"]), []).append(x)
    bf, bh, llf, llh = [], [], [], []
    for v in by.values():
        if len(v) != 2:
            continue
        try:
            ia, ib = 1.0 / dec(v[0]["px"]), 1.0 / dec(v[1]["px"])
        except ValueError:
            continue
        s = ia + ib
        if not (CFG["sane"][0] <= s <= CFG["sane"][1]):
            continue
        # Score canonical first side (both sides give identical Brier and Log-Loss when p_a + p_b = 1)
        x = v[0]
        pf = min(max(float(x["p"]), 1e-5), 1.0 - 1e-5)
        ph = power_devig(ia, ib)
        y = float(x["won"])
        bf.append((pf - y) ** 2)
        bh.append((ph - y) ** 2)
        llf.append(-(y * math.log(pf) + (1.0 - y) * math.log(1.0 - pf)))
        llh.append(-(y * math.log(ph) + (1.0 - y) * math.log(1.0 - ph)))
    bands = []
    for lo, hi in ((-1.0, -0.04), (-0.04, 0.0), (0.0, 0.02), (0.02, float("inf"))):
        z = [x for x in g if lo <= x["ev"] < hi]
        bands.append(dict(
            lo=lo, hi=None if math.isinf(hi) else hi, n=len(z),
            hit=round(float(np.mean([x["won"] for x in z])), 4) if z else None,
            ev=round(float(np.mean([x["ev"] for x in z])), 4) if z else None,
            roi=round(float(np.mean([x["units"] for x in z])), 4) if z else None,
        ))
    return dict(
        n=len(g), markets=len(bf),
        brier_fair=round(float(np.mean(bf)), 5) if bf else None,
        brier_hr=round(float(np.mean(bh)), 5) if bh else None,
        ll_fair=round(float(np.mean(llf)), 5) if llf else None,
        ll_hr=round(float(np.mean(llh)), 5) if llh else None,
        bands=bands,
    )


def calib_bins(A):
    """v4.2 Trust Strip: ONE canonical side per market (favorite p >= 0.50) across 4 non-tautological bands + Wilson 95% CI."""
    canon = _canonical_audit(A)
    out = []
    for lo, hi in ((0.50, 0.55), (0.55, 0.60), (0.60, 0.70), (0.70, 1.01)):
        z = [x for x in canon if lo <= x["p"] < hi]
        k = sum(x["won"] for x in z)
        ci_lo, ci_hi = _wilson(k, len(z))
        out.append(dict(
            lo=lo, hi=min(hi, 1.0), n=len(z),
            said=round(float(np.mean([x["p"] for x in z])), 4) if z else None,
            hit=round(k / len(z), 4) if z else None,
            ci_lo=ci_lo, ci_hi=ci_hi,
        ))
    return out


def _book_slice(S, per_league=30, fields=("lg", "id", "date", "day", "away", "home", "mkt", "side", "line", "px", "p", "ev", "status", "units", "close", "sharp")):
    """Per-league recent slice so high-volume NBA never starves NFL out of the UI."""
    out = []
    for lg in ("NBA", "NFL"):
        rows = sorted([x for x in S if x.get("lg") == lg], key=lambda x: (x.get("day", ""), x.get("id", "")), reverse=True)[:per_league]
        out.extend({k: x.get(k) for k in fields} for x in rows)
    return sorted(out, key=lambda x: (x.get("day", ""), x.get("id", "")), reverse=True)


def _card_summary_block(S, A, K, F):
    return dict(
        rec=dict(
            all=record(S),
            **{lg: record([x for x in S if x["lg"] == lg]) for lg in ("NBA", "NFL")},
            **{mk: record([x for x in S if x["mkt"] == mk]) for mk in MK},
        ),
        promote=promotion(S),
        audit=audit_score(A),
        calib=calib_bins(A),
        likely=dict(
            rec=dict(all=record(K), **{lg: record([x for x in K if x["lg"] == lg]) for lg in ("NBA", "NFL")}),
            book=_book_slice(K, per_league=15, fields=("lg", "id", "day", "away", "home", "mkt", "side", "line", "px", "p", "p_win", "ev", "status", "units", "close")),
        ),
        fl=dict(
            rec=dict(all=record(F), **{fb: record([x for x in F if x.get("book") == fb]) for fb in CFG["fl_books"]}),
        ),
        book=_book_slice(S, per_league=30),
    )


def write_card(date, card):
    """out/gline.json: what the page and summary read. Stamps `logged` and `lk_logged` from actual shadow books."""
    S = jl(O + "gshadow.json", [])
    A = jl(O + "gaudit.json", [])
    K = jl(O + "glikely.json", [])
    F = jl(O + "gfl.json", [])
    logged_s = {(x["lg"], x["id"], x["mkt"], x["side"]) for x in S}
    logged_k = {(x["lg"], x["id"], x["mkt"], x["side"]) for x in K}

    def slim(lg, g):
        return dict(
            id=g["id"], day=g["day"], away=g["away"], home=g["home"], hr=g["hr"],
            fair=dict(
                p=None if g["fair"]["p"] is None else round(g["fair"]["p"], 4),
                mu=None if g["fair"]["mu"] is None else round(g["fair"]["mu"], 1),
                t=None if g["fair"]["t"] is None else round(g["fair"]["t"], 1),
                n=g["fair"]["n"], src=sorted(g["fair"]["src"]),
            ),
            sides=[
                dict(
                    {k: s[k] for k in ("mkt", "side", "line", "px", "p", "p_win", "push", "be", "ev", "pin_ev", "ok", "why", "lk")},
                    logged=(lg, g["id"], s["mkt"], s["side"]) in logged_s,
                    lk_logged=(lg, g["id"], s["mkt"], s["side"]) in logged_k,
                )
                for s in g["sides"]
            ],
        )

    out = dict(
        ver=VER, date=date,
        cfg={k: CFG[k] for k in ("min_books", "min_ev", "max_ev", "ml_px", "sp_px", "promote", "likely")},
        lg={lg: dict(asof=c["asof"], games=[slim(lg, g) for g in c["games"]]) for lg, c in card.items()},
        **_card_summary_block(S, A, K, F),
    )
    jd(O + "gline.json", out)


def refresh_card(today_iso):
    """Refresh out/gline.json record, promotion, calib, likely, fl, book after grading, pruning finished days."""
    old = jl(O + "gline.json", None)
    if not isinstance(old, dict):
        return
    S = jl(O + "gshadow.json", [])
    A = jl(O + "gaudit.json", [])
    K = jl(O + "glikely.json", [])
    F = jl(O + "gfl.json", [])
    logged_s = {(x["lg"], x["id"], x["mkt"], x["side"]) for x in S}
    logged_k = {(x["lg"], x["id"], x["mkt"], x["side"]) for x in K}
    for lg, blk in (old.get("lg") or {}).items():
        games = [g for g in (blk.get("games") or []) if g.get("day", "") >= today_iso]
        for g in games:
            for s in g.get("sides") or []:
                s["logged"] = (lg, g["id"], s["mkt"], s["side"]) in logged_s
                s["lk_logged"] = (lg, g["id"], s["mkt"], s["side"]) in logged_k
        blk["games"] = games
    old.update(_card_summary_block(S, A, K, F))
    jd(O + "gline.json", old)


def lbl(x):
    if x["mkt"] == "h2h":
        return f"{x['side']} to win"
    if x["mkt"] == "spreads":
        return f"{x['side']} {x['line']:+g}"
    return f"{x['side']} {x['line']:g}"


def cmd_report():
    S = jl(O + "gshadow.json", [])
    A = jl(O + "gaudit.json", [])
    print("GAME PRICE LANE (v4.2 shadow, not staked). Hard Rock's price against the sharp-weighted market.")
    for name, z in [("All", S)] + [(lg, [x for x in S if x["lg"] == lg]) for lg in ("NBA", "NFL")] + [(NAME[mk], [x for x in S if x["mkt"] == mk]) for mk in MK]:
        r = record(z)
        if not r["n"]:
            continue
        t_s = "" if r["t_clv"] is None else f" (t={r['t_clv']:+.2f})"
        clv = "no close yet" if r["clv"] is None else f"closing line value {r['clv'] * 100:+.1f}%{t_s} on {r['clv_n']}, beat the close {r['beat'] * 100:.0f}%"
        print(f"  {name:10s} {r['w']}-{r['l']}" + (f"-{r['push']}" if r["push"] else "") + f", {r['units']:+.2f} units flat, {r['open']} open, value when logged {r['ev'] * 100:+.1f}%, {clv}")
    if not S:
        print("  no sides logged yet")
    a = audit_score(A)
    if a:
        print(f"  fair number check, {a['markets']} graded Hard Rock markets ({a['n']} sides): log-loss {a['ll_fair']} vs HR {a['ll_hr']} | Brier {a['brier_fair']} vs HR {a['brier_hr']}")
        for b in a["bands"]:
            if b["n"]:
                hi_s = "inf" if b["hi"] is None else f"{b['hi'] * 100:+.0f}%"
                print(f"    value {b['lo'] * 100:+.0f}% to {hi_s}: {b['n']} sides, hit {b['hit'] * 100:.1f}% (avg EV {b['ev'] * 100:+.1f}%), return {b['roi'] * 100:+.1f}%")
    K = jl(O + "glikely.json", [])
    r = record(K)
    if r["n"]:
        g_k = [x for x in K if x.get("status") in ("won", "lost")]
        hit = "" if not g_k else f", hit {r['w'] / r['graded'] * 100:.0f}% against {float(np.mean([x.get('p_win', x['p']) for x in g_k])) * 100:.0f}% said"
        clv = "no close yet" if r["clv"] is None else f"closing line value {r['clv'] * 100:+.1f}% on {r['clv_n']}"
        print(f"  MOST LIKELY LANE (P(win) >= {CFG['likely']['p'] * 100:.0f}%, EV >= {CFG['likely']['ev'] * 100:+.1f}%): {r['w']}-{r['l']}" + (f"-{r['push']}" if r["push"] else "") + f", {r['units']:+.2f} units flat, {r['open']} open{hit}, {clv}")
    F = jl(O + "gfl.json", [])
    rf = record(F)
    if rf["n"]:
        parts = []
        for fb in CFG["fl_books"]:
            r1 = record([x for x in F if x.get("book") == fb])
            if r1["n"]:
                c_s = "" if r1["clv"] is None else f", CLV {r1['clv'] * 100:+.1f}%/{r1['clv_n']}"
                parts.append(f"{fb} {r1['w']}-{r1['l']} ({r1['units']:+.2f}u, {r1['open']} open{c_s})")
        print("  FL EXCHANGES (shadow): " + "; ".join(parts))
    cb = [b for b in calib_bins(A) if b["n"]]
    if cb:
        print("  does the fair chance come true (1 canonical side/market): " + "; ".join(f"said {b['said'] * 100:.0f}% hit {b['hit'] * 100:.0f}% [{b['ci_lo'] * 100:.0f}-{b['ci_hi'] * 100:.0f}%] ({b['n']})" for b in cb))
    p = promotion(S)
    print("  PROMOTION TEST: " + ("MET. Staking is still Armanddo's call." if p["met"] else "not met"))
    for c in p["checks"]:
        print(f"    {'ok ' if c['ok'] else '-- '}{c['name']}: {c['have']} (needs >= {c['need']})")


def cmd_show(date):
    for lg in ("NBA", "NFL"):
        games, asof = slate(lg, date)
        print(f"{lg} {date}: {len(games)} games, pulled {asof}")
        for g in games:
            f = g["fair"]
            print(f"  {g['away']}@{g['home']} {g['day']} fair: home win {f['p']}, home by {f['mu']}, total {f['t']}, sources {f['n']}")
            for s in g["sides"]:
                print(f"    {'CLEARS' if s['ok'] else '      '} {lbl(s):22s} {s['px']:+.0f} fair {s['p'] * 100:.1f}% value {s['ev'] * 100:+.1f}%" + ("" if s["ok"] else f"  ({s['why']})"))


def cmd_summary(path):
    """Add the lane's counts to the public summary file: record and status only, never a price or a wallet."""
    j = jl(path, {})
    S = jl(O + "gshadow.json", [])
    F = jl(O + "gfl.json", [])
    st = jl(O + "sharps/status.json", {})
    j["gline"] = dict(
        ver=VER, rec=record(S), promote=promotion(S)["met"],
        audit=len(jl(O + "gaudit.json", [])),
        likely=record(jl(O + "glikely.json", [])),
        fl=record(F),
    )
    j["poly"] = {k: st.get(k) for k in ("at", "calls", "notes", "errors", "tracked", "tracked_src", "wallets", "shapes")}
    jd(path, j)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "log":
        cmd_log(a[1])
    elif a[0] == "close":
        cmd_close(a[1])
    elif a[0] == "grade":
        cmd_grade()
    elif a[0] == "report":
        cmd_report()
    elif a[0] == "show":
        cmd_show(a[1])
    elif a[0] == "summary":
        cmd_summary(a[1])

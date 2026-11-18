"""Game simulator for the Sim tab (v3.20). Plays every game on the slate 10,000 times with simcore, so the players in a game
move together: a blowout sits the starters, a shootout lifts both offenses, a quarterback's yards are his receivers'
yards. Writes research/sim_nba.json and research/sim_nfl.json for the page (fetched when the Sim tab opens) and keeps a
running log of every prop it priced next to the model's own price and the books' price, graded after the games.

Display and tracking only. Nothing here feeds daily.py's prices or picks. It earns a say only if the weekly review finds
it beats the current pricing over 200+ graded sides (RUNBOOK, Sim).

  python3 sim.py            simulate the slate, log today's priced props, write the research files
  python3 sim.py grade      grade logged props whose games are over (run.sh runs this first)
  python3 sim.py report     print the record"""
import base64, datetime, json, os, re, sys, time
from zoneinfo import ZoneInfo
import numpy as np
from scipy import stats
import simcore
from common import norm, nb_k, load_lineups

O = "/home/claude/props/out/"
DT = "/home/claude/props/data/"
ET = ZoneInfo("America/New_York")
SIMS, BITS, SAMPLES = 10000, 2000, 12
LOG = os.environ.get("SIM_LOG") or O + "simlog.json"      # SIM_LOG: a scratch log for local replays only
MKT = {"NBA": {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3",
               "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa", "player_rebounds_assists": "ra"},
       "NFL": {"player_pass_yds": "pass_yds", "player_pass_attempts": "pass_att", "player_pass_completions": "pass_cmp", "player_pass_tds": "pass_td",
               "player_rush_yds": "rush_yds", "player_rush_attempts": "rush_att", "player_receptions": "rec", "player_reception_yds": "rec_yds",
               "player_anytime_td": "any_td"}}
COMBO = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
SHOW = {"NBA": ["min", "pts", "reb", "ast", "fg3", "pra"], "NFL": ["pass_yds", "pass_att", "pass_cmp", "pass_td", "rush_yds", "rush_att", "rec", "rec_yds", "td"]}
BOOK = "hardrockbet"
# Walk-forward test, written by sim_bt.py and sim_bt_nfl.py (CHANGELOG v3.20). Shown on the page as-is.
BT = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_bt.json"))) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_bt.json")) else {}


def now_et():
    t = os.environ.get("SIM_NOW")          # a local replay of an earlier day, for testing only (never set in the daily job)
    return datetime.datetime.fromisoformat(t).replace(tzinfo=ET) if t else datetime.datetime.now(ET)


def dec(a):
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def latest_lines(lg):
    try:
        import books
        return books.latest(lg)
    except Exception:
        return None


def read_lines(path):
    """{(away, home): {(name key, market): {book: (line, over, under)}}} from a relay lines file (game markers kept)."""
    out, game = {}, None
    if not path or not os.path.exists(path):
        return out
    for ln in open(path):
        if ln.startswith("# game:"):
            a, h = [x.strip() for x in ln.split(":", 1)[1].split("@")]
            game = (a, h); out.setdefault(game, {}); continue
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if game is None or len(c) < 6 or c[0] in ("bookmaker_key", "") or c[0].startswith("#"):
            continue
        num = lambda s: float(s.replace("+", "")) if re.fullmatch(r"[+-]?\d+(\.\d+)?", s) else None
        out[game].setdefault((norm(c[2]), c[1]), {})[c[0]] = (num(c[3]), num(c[4]), num(c[5]))
    return out


def pick_line(books_):
    """Hard Rock's line when it has one (the book the desk bets), otherwise the most common line. Returns line, book,
    over, under, the books' no-vig chance of the over at that line (median), and how many books quote that line."""
    q = {b: v for b, v in books_.items() if v[1] is not None}
    if not q:
        return None
    if BOOK in q:
        bk = BOOK
    else:
        ls = [v[0] for v in q.values()]
        common = max(set(ls), key=lambda l: (ls.count(l), -abs((l or 0) - np.median([x for x in ls if x is not None] or [0]))))
        bk = sorted(b for b, v in q.items() if v[0] == common)[0]
    line, o, u = q[bk]
    same = [v for v in q.values() if v[0] == line and v[1] is not None and v[2] is not None]
    fair = [(1 / dec(v[1])) / (1 / dec(v[1]) + 1 / dec(v[2])) for v in same]
    return dict(line=line, book=bk, o=o, u=u, p_mkt=float(np.median(fair)) if fair else None, nb=len(same))


def b64bits(mask):
    return base64.b64encode(np.packbits(mask[:BITS].astype(np.uint8)).tobytes()).decode()


def qs(x):
    q = np.percentile(x, [10, 25, 50, 75, 90], axis=0)
    return q


def nb_over(lg, disp, mkt, mu, line):
    if mkt == "any_td":
        return float(1 - np.exp(-mu))
    a, b = disp[mkt]
    k = nb_k(np.array([mu]), a, b)[0]
    return float(1 - stats.nbinom.cdf(np.floor(line), k, k / (k + mu)))


# ------------------------------------------------------------------------------------------------ league inputs

def nba_inputs(D, G):
    L = D["NBA"]; chk = json.load(open(O + "nba_check.json"))
    byteam = {}
    for p in L["players"]:
        byteam.setdefault(p["team"], []).append(p)
    gm = {g["id"]: g for g in (G.get("NBA") or {}).get("games", [])}
    out = []
    for g in L["games"]:
        sides = []
        for t in (g["away"], g["home"]):
            ps = [p for p in byteam.get(t, []) if f'{g["id"]}|{p["id"]}' in chk]
            ps.sort(key=lambda p: -chk[f'{g["id"]}|{p["id"]}']["mn"])
            c = [chk[f'{g["id"]}|{p["id"]}'] for p in ps]
            sides.append((ps, dict(mu={k: np.array([x[k] for x in c]) for k in ("pts", "reb", "ast", "fg3")}, mn=np.array([x["mn"] for x in c]))))
        if not len(sides[0][0]) or not len(sides[1][0]):
            continue
        m = gm.get(g["id"]) or {}
        P = simcore.NBA
        if m.get("spread") is not None and m.get("total") is not None:
            spread, total, src, sd = float(m["spread"]), float(m["total"]), "the books' spread and total", (P["sd_m"], P["sd_t"])
        else:
            pa, ph = sides[0][1]["mu"]["pts"].sum(), sides[1][1]["mu"]["pts"].sum()
            spread, total, src, sd = ph - pa + P["hfa_model"], pa + ph + P["tadj_model"], "the model's projections (no line yet)", (P["sd_m_model"], P["sd_t_model"])
        out.append(dict(g=g, sides=sides, spread=spread, total=total, src=src, sd=sd, ml=m))
    return out


def nfl_inputs(D, G):
    L = D["NFL"]; chk = json.load(open(O + "nfl_check.json"))
    sides = {s["team"]: s for s in L["sides"]}
    byteam = {}
    for p in L["players"]:
        if p["id"] in chk and p.get("active"):
            byteam.setdefault(p["team"], []).append(p)
    gm = {g["id"]: g for g in (G.get("NFL") or {}).get("games", [])}
    out = []
    for g in L["games"]:
        ss = []
        for t in (g["away"], g["home"]):
            s = sides.get(t); ps = byteam.get(t, [])
            if not s or not ps:
                break
            ps = sorted(ps, key=lambda p: -(chk[p["id"]]["tgt"] + chk[p["id"]]["f_rush"] + chk[p["id"]]["f_pass"]))
            c = [chk[p["id"]] for p in ps]
            arr = lambda k: np.array([x[k] for x in c], float)
            tgt, car = arr("tgt"), arr("f_rush")
            rf = np.array([(tg * p["rtd"]) / max(tg * p["rtd"] + cr * p["rutd"], 1e-6) for p, tg, cr in zip(ps, tgt, car)])
            ss.append((ps, dict(PA=s["PA"], CAR=s["CAR"], ip=s["ip"], qb=np.array([p["pos"] == "QB" and x["f_pass"] >= 5 for p, x in zip(ps, c)]), rfrac=rf, pos=np.array([p["pos"] for p in ps]),
                                mu={"tgt": tgt, "rec": arr("rec"), "rec_yds": arr("rec_yds"), "rush_att": arr("rush_att"), "rush_yds": arr("rush_yds"),
                                    "pass_att": arr("pass_att"), "pass_cmp": arr("pass_cmp"), "pass_yds": arr("pass_yds"), "td": arr("td")})))
        if len(ss) < 2:
            continue
        m = gm.get(g["id"]) or {}
        spread = float(m["spread"]) if m.get("spread") is not None else float(g.get("spread") or 0)
        total = float(m["total"]) if m.get("total") is not None else float(g.get("total") or 44)
        out.append(dict(g=g, sides=ss, spread=spread, total=total, src="the books' spread and total" if m.get("spread") is not None else "the schedule's line", sd=None, ml=m))
    return out


# ------------------------------------------------------------------------------------------------ the desk's own numbers
# The sim starts from what the desk believes about each player, not the raw model: the model is centred on the market
# for the slate, market by market, then blended with each book-quoted player's market number at the desk's learned
# weight (daily.py: mean = market + w x (c x model - market)). Players with no line keep the centred model. So the sim's
# lean on a prop is the desk's lean, played out with everyone else in the game, never a general tilt against the books.
BASEK = {"NBA": {"pts": "player_points", "reb": "player_rebounds", "ast": "player_assists", "fg3": "player_threes"},
         "NFL": {"rec_yds": "player_reception_yds", "rush_yds": "player_rush_yds", "pass_yds": "player_pass_yds", "rec": "player_receptions",
                 "rush_att": "player_rush_attempts", "pass_att": "player_pass_attempts", "pass_cmp": "player_pass_completions"}}


def desk_means(lg, D, xs, lines):
    try:
        import daily
        cal = daily.calib(D)
    except Exception as e:
        print("sim: desk blend not available, raw model used:", str(e)[:80]); return {}
    L = D[lg]; notes = {}
    for k, bm in BASEK[lg].items():
        if k not in L["model"]["disp"]:
            continue
        rows = []
        for x in xs:
            gl = lines.get((x["g"]["away"], x["g"]["home"]), {})
            for j, (ps, inp) in enumerate(x["sides"]):
                for i, p in enumerate(ps):
                    mu = float(inp["mu"][k][i]); q = gl.get((norm(p["name"]), bm))
                    mm = None
                    if q and mu > 0.05:
                        ims = [(b, daily.implied_mean(L, lg, k, v[0], (1 / dec(v[1])) / (1 / dec(v[1]) + 1 / dec(v[2])))) for b, v in q.items()
                               if v[0] is not None and v[1] is not None and v[2] is not None]
                        oth = [m for b, m in ims if b != BOOK]
                        mm = float(np.median(oth if len(oth) >= 2 else [m for _, m in ims])) if ims else None
                    rows.append((x, j, i, mu, mm))
        q = [(r[3], r[4]) for r in rows if r[4] is not None]
        c = daily.centre(q) if q else 1.0
        w = cal.get(lg + "|" + k, {}).get("w", daily.CFG["cal_w0"])
        for x, j, i, mu, mm in rows:
            new = mm + w * (c * mu - mm) if mm is not None else c * mu
            arr = x["sides"][j][1]["mu"][k]
            if lg == "NFL" and k == "rec" and mu > 0:
                x["sides"][j][1]["mu"]["tgt"][i] *= new / mu       # targets follow catches, so the catch rate holds
            arr[i] = max(new, 0.0)
        notes[k] = dict(c=round(c, 3), w=round(w, 3), quoted=len(q))
    return notes


def fit_team_points(xs, lines):
    """NBA: the books' team totals are the best number on how many points a side scores, and the books' player lines the
    best number on who scores them. The players with a points line keep the desk's number; the rest of the rotation
    shares what is left of the team total. (The sum of every player's number runs well over the team total: the rotation
    is filled past 240 minutes and nobody's line is shaded for it. Left alone the runs would pull every scorer down.)"""
    for x in xs:
        sc = x["ml"].get("sc")
        if not sc:
            continue
        gl = lines.get((x["g"]["away"], x["g"]["home"]), {})
        for j, (ps, inp) in enumerate(x["sides"]):
            mu = inp["mu"]["pts"]; q = np.array([bool(gl.get((norm(p["name"]), "player_points"))) for p in ps])
            tgt = float(sc[j]); qs_ = mu[q].sum(); rest = mu[~q].sum()
            if rest <= 0:
                continue
            k = (tgt - qs_) / rest
            if k < 0.35:                       # the quoted players alone nearly reach the total: trim them a little too
                k = 0.35; kq = (tgt - 0.35 * rest) / max(qs_, 1e-6); mu[q] *= max(kq, 0.8)
            mu[~q] *= min(k, 1.25)
            x.setdefault("fit", []).append(dict(t=j, k=round(float(k), 3), quoted=round(float(qs_), 1), total=round(tgt, 1), n=int(q.sum())))


# ------------------------------------------------------------------------------------------------ one game

def stat_of(lg, box, k):
    if k in COMBO:
        return sum(box[c] for c in COMBO[k])
    if k == "any_td":
        return (box["td"] >= 1).astype(int)
    return box[k]


TYP = 6         # typical runs shown by default


def _rk(v, rng):
    """Percentile rank of every run on one number, ties broken at random, in (0, 1)."""
    o = np.argsort(np.asarray(v, float) + rng.random(len(v)) * 1e-6)
    u = np.empty(len(v)); u[o] = (np.arange(len(v)) + 0.5) / len(v)
    return u


def _last(name):
    bits = str(name).replace(" Jr.", "").replace(" III", "").replace(" II", "").split()
    return bits[-1] if bits else str(name)


def pick_runs(lg, x, s, M, tot, rng):
    """Choose the replay runs. Typical: six runs that sit near the middle on the margin (within the winner's share of runs),
    the total and the key players' main stats, split between the sides by how often each wins. Outliers: one representative run for
    each named way the game can break (an upset under one in five, blowouts, shootout, low scoring, the top player's big and off nights), with its share
    of runs and the two stats that move most against all runs. Returns ([(run, meta)], index of the most typical run)."""
    N = len(M); nba = lg == "NBA"; tm = (x["g"]["away"], x["g"]["home"])
    # key players: top two a side on points (NBA), top three a side on their main yards (NFL)
    kp = []
    for j, (ps, inp) in enumerate(x["sides"]):
        box = s["teams"][j]; cand = []
        for i, p in enumerate(ps):
            if nba:
                k = "pts"
            else:
                k = "pass_yds" if inp["qb"][i] else ("rush_yds" if inp["mu"]["rush_att"][i] >= inp["mu"]["tgt"][i] else "rec_yds")
            v = box[k][:, i].astype(float)
            cand.append((v.mean(), j, i, k, p["name"], v))
        kp += sorted(cand, key=lambda c: -c[0])[:2 if nba else 3]
    uM, uT = _rk(M, rng), _rk(tot, rng)
    uP = [_rk(c[5], rng) for c in kp]
    pl = sum((u - 0.5) ** 2 for u in uP) * (2.0 / max(1, len(uP)))
    base = 1.5 * (uT - 0.5) ** 2 + pl                       # how far a run sits from the middle, margin aside
    d_all = 2.0 * (uM - 0.5) ** 2 + base
    w = 3 if nba else 4
    seen, out = set(), []
    def key_of(r):
        return (int(s["score"][r, 0]), int(s["score"][r, 1]))
    # typical: split six runs between the sides by win share, each side's runs spread over the middle of its own margins
    home, away = M > 0, M < 0
    ph, pa = home.mean(), away.mean()
    nh = int(round(TYP * ph / max(1e-9, ph + pa)))
    nh = TYP if pa < 0.2 else (0 if ph < 0.2 else min(max(nh, 1), TYP - 1))     # a side that wins under one run in five is an outlier, not typical
    typ = []
    for mask, n in ((home, nh), (away, TYP - nh)):
        if n <= 0 or not mask.any():
            continue
        idx = np.flatnonzero(mask); uc = _rk(np.abs(M[idx]), rng)
        for t in ([0.5] if n == 1 else np.linspace(0.25, 0.75, n)):
            cost = 4.0 * (uc - t) ** 2 + base[idx]
            for c in np.argsort(cost)[:400]:
                r = int(idx[c])
                if key_of(r) not in seen:
                    seen.add(key_of(r)); typ.append(r); break
    typ.sort(key=lambda r: (M[r], r))
    dflt = int(min(range(len(typ)), key=lambda i: d_all[typ[i]])) if typ else 0
    for r in typ:
        m = M[r]
        near = (np.sign(M) == np.sign(m)) & (np.abs(M - m) <= w)
        out.append((r, dict(k="t", pct=round(float(near.mean()), 4))))
    # outliers
    sc = s["score"].astype(float)
    feats = []                                              # (label, unit, values) checked for the why line
    for j in (0, 1):
        box = s["teams"][j]
        if nba:
            feats.append((f"{tm[j]} threes", "", box["fg3"].sum(1).astype(float)))
        else:
            if not any(c[1] == j and c[3] == "pass_yds" for c in kp):       # the QB's own line says the same thing
                feats.append((f"{tm[j]} passing", " yds", box["pass_yds"].sum(1).astype(float)))
            feats.append((f"{tm[j]} rushing", " yds", box["rush_yds"].sum(1).astype(float)))
    for c in kp:
        _, j, i, k, nm, v = c
        feats.append((_last(nm), " pts" if k == "pts" else " yds", v))
        if nba:
            feats.append((f"{_last(nm)} minutes", "", s["teams"][j]["min"][:, i].astype(float)))
    fm = [(f[2].mean(), f[2].std() + 1e-9) for f in feats]
    def why(mask, skip=()):
        z = []
        for (lab, unit, v), (mu, sd) in zip(feats, fm):
            if lab in skip:
                continue
            g = v[mask].mean(); z.append((abs(g - mu) / sd, lab, unit, g, mu))
        z.sort(key=lambda t: -t[0])
        return " · ".join(f"{lab} {g:.0f}{unit}, usually {mu:.0f}" for _, lab, unit, g, mu in z[:2] if _ > 0.1)
    def rep(mask):
        idx = np.flatnonzero(mask)
        dims = [(2.0, uM), (1.5, uT)] + [(2.0 / max(1, len(uP)), u) for u in uP]
        cost = sum(wt * (u[idx] - np.median(u[idx])) ** 2 for wt, u in dims)
        for c in np.argsort(cost)[:400]:
            r = int(idx[c])
            if key_of(r) not in seen:
                seen.add(key_of(r)); return r
        return int(idx[np.argmin(cost)])
    big = 20 if nba else 17
    t90, t10 = np.percentile(tot, 90), np.percentile(tot, 10)
    sc_ = []
    fav = 1 if ph >= pa else 0
    if min(ph, pa) < 0.2:                                   # at one in five or more the underdog's wins sit in Typical
        sc_.append(("upset", f"{tm[1 - fav]} wins", (M < 0) if fav == 1 else (M > 0), ()))
    bh = max(big, int(np.ceil(np.percentile(M, 90))))          # a blowout is past the side's own 90th percentile, never under 20 (NBA) / 17 (NFL)
    ba = max(big, int(np.ceil(np.percentile(-M, 90))))
    sc_.append(("bh", f"{tm[1]} by {bh}+", M >= bh, ()))
    sc_.append(("ba", f"{tm[0]} by {ba}+", M <= -ba, ()))
    sc_.append(("hi", f"Total {int(np.ceil(t90))}+", tot >= t90, ()))
    sc_.append(("lo", f"Total {int(np.floor(t10))} or less", tot <= t10, ()))
    if kp:
        st = max(kp, key=lambda c: c[0]); v = st[5]; nm = _last(st[4]); unit = "pts" if st[3] == "pts" else "yds"
        q9, q1 = np.percentile(v, 90), np.percentile(v, 10)
        sc_.append(("big", f"{nm} {int(np.ceil(q9))}+ {unit}", v >= q9, (nm,)))
        sc_.append(("off", f"{nm} {int(np.floor(q1))} {unit} or less", v <= q1, (nm,)))
    for key, lab, mask, skip in sc_:
        pct = float(mask.mean())
        if pct < 0.01 or mask.sum() < 20:
            continue
        r = rep(mask)
        out.append((r, dict(k="o", key=key, lab=lab, pct=round(pct, 4), why=why(mask, skip))))
    return out, dflt


LUD = {}


def run_game(lg, x, rng, lines, disp, slate_day):
    g = x["g"]
    if lg == "NBA":
        sd_m, sd_t = x["sd"]
        s = simcore.nba_game(rng, SIMS, x["sides"][1][1], x["sides"][0][1], x["spread"], x["total"], simcore.NBA, sd_m=sd_m, sd_t=sd_t)
    else:
        s = simcore.nfl_game(rng, SIMS, x["sides"][1][1], x["sides"][0][1], x["spread"], x["total"], simcore.NFL)
    M = s["M"].astype(float); sc = s["score"].astype(float)
    tot = sc.sum(1)
    tl = x["ml"].get("total") if x["ml"].get("total") is not None else None
    legs = {"away": M < 0, "home": M > 0, "hcover": M > x["spread"], "acover": M < x["spread"]}
    if tl is not None:
        legs["over"] = tot > tl; legs["under"] = tot < tl
    hist_lo = -40 if lg == "NBA" else -35
    hb = np.bincount(np.clip(M - hist_lo, 0, -2 * hist_lo).astype(int), minlength=-2 * hist_lo + 1)
    game = dict(id=g["id"], day=g.get("day"), time=g.get("time"), away=g["away"], home=g["home"], src=x["src"], fit=x.get("fit", []),
                spread=round(x["spread"], 1), total=round(x["total"], 1), tline=tl,
                score=[round(float(sc[:, 0].mean()), 1), round(float(sc[:, 1].mean()), 1)],
                sq=[[int(v) for v in np.percentile(sc[:, j], [10, 50, 90])] for j in (0, 1)],
                p=dict(home=round(float(legs["home"].mean()), 4), hcover=round(float(legs["hcover"].mean()), 4),
                       over=None if tl is None else round(float(legs["over"].mean()), 4),
                       blow=round(float((np.abs(M) >= (20 if lg == "NBA" else 17)).mean()), 4), close=round(float((np.abs(M) <= (5 if lg == "NBA" else 7)).mean()), 4)),
                hist=dict(lo=hist_lo, c=hb.tolist()), legs={k: b64bits(v) for k, v in legs.items()}, teams=[], props=[], samples=[])
    key = (g["away"], g["home"])
    gl = lines.get(key, {})
    close = np.abs(M) <= (9 if lg == "NBA" else 7)
    blow = np.abs(M) >= (20 if lg == "NBA" else 17)
    for j, (ps, inp) in enumerate(x["sides"]):
        box = s["teams"][j]
        lead = (M if j == 1 else -M)
        T = dict(team=(g["away"], g["home"])[j], players=[])
        for i, p in enumerate(ps):
            st = {}
            for k in SHOW[lg]:
                v = stat_of(lg, box, k)[:, i].astype(float)
                if lg == "NFL" and v.max() == 0 and k != "td":
                    continue
                q = qs(v)
                st[k] = [round(float(v.mean()), 2)] + [round(float(z), 1) for z in q]
            if lg == "NBA":
                main = box["pts"][:, i].astype(float); mn_ = box["min"][:, i]
                cond = dict(k="pts", close=round(float(main[close].mean()), 1), blow=round(float(main[blow].mean()), 1),
                            mclose=round(float(mn_[close].mean()), 1), mblow=round(float(mn_[blow].mean()), 1))
            else:
                k = "pass_yds" if inp["qb"][i] else ("rush_yds" if inp["mu"]["rush_att"][i] >= inp["mu"]["tgt"][i] else "rec_yds")
                v = box[k][:, i].astype(float)
                cond = dict(k=k, behind=round(float(v[lead <= -10].mean()), 1) if (lead <= -10).any() else None, ahead=round(float(v[lead >= 10].mean()), 1) if (lead >= 10).any() else None)
            on5 = lg == "NBA" and p.get("lu") and T["team"] in LUD.setdefault(g.get("day"), load_lineups("NBA", g.get("day")))      # v3.24: only a game the league has posted a lineup for
            T["players"].append(dict(id=p["id"], name=p["name"], pos=p.get("pos"), st=st, cond=cond, **({"lu": p["lu"], "luc": p.get("luc")} if on5 else {})))
            # props: book lines where there are any; on a day with no lines yet, a sim line at the median for the main stats
            nk = norm(p["name"])
            for bm, mk in MKT[lg].items():
                bq = gl.get((nk, bm))
                pl = pick_line(bq) if bq else None
                v = stat_of(lg, box, mk)[:, i]
                if pl is None:
                    if gl or mk not in (("pts", "reb", "ast") if lg == "NBA" else ("pass_yds", "rush_yds", "rec_yds")):
                        continue
                    med = float(np.median(v))
                    if (lg == "NBA" and (box["min"][:, i].mean() < 20 or med < 2)) or (lg == "NFL" and med < 15):
                        continue
                    pl = dict(line=np.floor(med) + 0.5, book=None, o=None, u=None, p_mkt=None, nb=0)
                if pl["line"] is None and mk != "any_td":
                    continue
                line = pl["line"] if pl["line"] is not None else 0.5
                over = v > line
                mu = float(inp["mu"][mk][i]) if lg == "NFL" and mk in inp["mu"] else None
                if lg == "NBA":
                    mu = float(sum(inp["mu"][c][i] for c in COMBO.get(mk, (mk,))))
                elif mk == "any_td":
                    mu = float(inp["mu"]["td"][i])
                pnb = nb_over(lg, disp, mk, mu, line) if mu is not None and (mk in disp or mk == "any_td") else None
                game["props"].append(dict(pid=p["id"], t=j, mkt=mk, line=line, book=pl["book"], o=pl["o"], u=pl["u"], nb=pl["nb"],
                                          p=round(float(over.mean()), 4), pm=None if pnb is None else round(pnb, 4),
                                          pk=None if pl["p_mkt"] is None else round(pl["p_mkt"], 4), mu=round(mu, 2) if mu is not None else None,
                                          b=b64bits(over)))
        game["teams"].append(T)
    # replay runs (v3.25): six typical games for the default set, then the outliers as named scenarios with how often each happened
    keys = ("min", "pts", "fg3", "reb", "ast") if lg == "NBA" else ("pass_att", "pass_cmp", "pass_yds", "pass_td", "rush_att", "rush_yds", "tgt", "rec", "rec_yds", "td", "rec_td")
    picks, game["def"] = pick_runs(lg, x, s, M, tot, rng)
    for r, meta in picks:
        game["samples"].append(dict(sc=[int(sc[r, 0]), int(sc[r, 1])], **meta, b=[{k: [round(float(v), 1) if k == "min" else int(v) for v in s["teams"][j][k][r, :len(x["sides"][j][0])]] for k in keys} for j in (0, 1)]))
    game["mq"] = [int(round(v)) for v in np.percentile(M, [25, 50, 75])]
    game["tq"] = [int(round(v)) for v in np.percentile(tot, [25, 50, 75])]
    return game


def tip_et(g):
    try:
        return datetime.datetime.fromisoformat(f'{g["day"]}T{g["time"]}').replace(tzinfo=ET)
    except Exception:
        return None


def main():
    t0 = time.time()
    D = json.load(open(O + "data.json"))
    G = json.load(open(O + "games.json")) if os.path.exists(O + "games.json") else {}
    try:
        log = json.load(open(LOG))
    except Exception:
        log = {}
    now = now_et(); today = now.strftime("%Y-%m-%d")
    os.makedirs(O + "research", exist_ok=True)
    for lg, fn in (("NBA", nba_inputs), ("NFL", nfl_inputs)):
        try:
            # games still to be played: today on, and for the NBA the next two days (the board's slate can trail the box scores by a day)
            horizon = (now + datetime.timedelta(days=1 if lg == "NBA" else 7)).strftime("%Y-%m-%d")
            xs = [x for x in fn(D, G) if today <= (x["g"].get("day") or "") <= horizon and (tip_et(x["g"]) is None or tip_et(x["g"]) > now - datetime.timedelta(hours=3))]
            lf = latest_lines(lg); lines = read_lines(lf)
            blend = desk_means(lg, D, xs, lines)
            if lg == "NBA":
                fit_team_points(xs, lines)
            disp = {k: tuple(v) for k, v in D[lg]["model"]["disp"].items()}
            rng = np.random.default_rng(int(now.strftime("%Y%m%d")) + (0 if lg == "NBA" else 7))
            games = [run_game(lg, x, rng, lines, disp, today) for x in xs]
            nlog = 0
            for x, gm in zip(xs, games):
                tip = tip_et(x["g"])
                if tip is None or tip <= now or gm["day"] != today:
                    continue
                for pr in gm["props"]:
                    if pr["book"] is None:
                        continue
                    k = f'{today}|{lg}|{gm["id"]}|{pr["pid"]}|{pr["mkt"]}'
                    log[k] = dict(d=today, lg=lg, g=gm["id"], pid=pr["pid"], mkt=pr["mkt"], line=pr["line"], book=pr["book"], o=pr["o"], u=pr["u"],
                                  p_sim=pr["p"], p_nb=pr["pm"], p_mkt=pr["pk"], at=now.strftime("%H:%M"), y=None, res=None)
                    nlog += 1
            out = dict(lg=lg, asof=now.strftime("%Y-%m-%d %H:%M ET"), runs=SIMS, bits=BITS, lines=os.path.basename(lf) if lf else None, blend=blend,
                       games=games, bt=dict(BT.get(lg, {}), ver=BT.get("ver"), was=BT.get("was")), rec=record(log, lg))
            if lg == "NFL":       # v3.21: the replay's real-play library (2023-24 play-by-play, built by lab prep_plays.py)
                pl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nfl_play_lib.json")
                if os.path.exists(pl):
                    out["plib"] = json.load(open(pl))
            json.dump(out, open(O + f"research/sim_{lg.lower()}.json", "w"), separators=(",", ":"))
            print(f"sim: {lg} {len(games)} games x {SIMS} runs, {sum(len(g['props']) for g in games)} props "
                  f"({sum(p['book'] is not None for g in games for p in g['props'])} with book lines from {os.path.basename(lf) if lf else 'no lines file'}), "
                  f"{nlog} logged, {os.path.getsize(O + f'research/sim_{lg.lower()}.json') // 1024} KB")
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"SIM STEP FAILED for {lg}: {e}")
    json.dump(log, open(LOG, "w"), separators=(",", ":"))
    print("sim done %.0fs" % (time.time() - t0))


# ------------------------------------------------------------------------------------------------ grading and the record

def outcomes(lg):
    """{(game id, player id): {market: value}} from the box score files."""
    import pandas as pd
    res = {}
    if lg == "NBA":
        b = pd.read_parquet(DT + "nba_pb_2027.parquet")
        b = b[b.minutes.notna() & (b.minutes > 0)]
        for r in b.itertuples():
            v = dict(pts=r.points or 0, reb=r.rebounds or 0, ast=r.assists or 0, fg3=r.three_point_field_goals_made or 0)
            v = {k: float(z) for k, z in v.items()}
            for c, parts in COMBO.items():
                v[c] = sum(v[q] for q in parts)
            res[(str(r.game_id), str(float(r.athlete_id)))] = v
    else:
        w = pd.read_csv(DT + "nfl_pw_2026.csv", low_memory=False)
        g = pd.read_csv(DT + "nfl_games.csv", low_memory=False)
        if "game_id" in w.columns:
            w = w.drop(columns=["game_id"])
        w = w.merge(g[["game_id", "season", "week", "home_team", "away_team"]], on=["season", "week"], how="inner")
        w = w[(w.team == w.home_team) | (w.team == w.away_team)]
        for r in w.itertuples():
            f = lambda c: float(getattr(r, c) if getattr(r, c) == getattr(r, c) else 0)
            res[(r.game_id, r.player_id)] = dict(pass_yds=f("passing_yards"), pass_att=f("attempts"), pass_cmp=f("completions"), pass_td=f("passing_tds"),
                                                rush_yds=f("rushing_yards"), rush_att=f("carries"), rec=f("receptions"), rec_yds=f("receiving_yards"),
                                                any_td=float(f("rushing_tds") + f("receiving_tds") > 0))
    return res


def grade():
    try:
        log = json.load(open(LOG))
    except Exception:
        print("sim grade: no log yet"); return
    today = now_et().strftime("%Y-%m-%d"); n = 0
    for lg in ("NBA", "NFL"):
        open_ = [k for k, v in log.items() if v["lg"] == lg and v["res"] is None and v["d"] < today]
        if not open_:
            continue
        try:
            Y = outcomes(lg)
        except Exception as e:
            print(f"sim grade {lg}: box scores not readable ({e})"); continue
        played_games = {g for g, _ in Y}
        for k in open_:
            v = log[k]
            if v["g"] not in played_games:
                if v["d"] < (now_et() - datetime.timedelta(days=4)).strftime("%Y-%m-%d"):
                    v["res"] = "void"
                continue
            y = Y.get((v["g"], v["pid"]))
            if y is None or v["mkt"] not in y:
                v["res"] = "void"; n += 1; continue
            v["y"] = y[v["mkt"]]
            line = v["line"] if v["mkt"] != "any_td" else 0.5
            v["res"] = "push" if v["y"] == line else ("over" if v["y"] > line else "under"); n += 1
    cut = (now_et() - datetime.timedelta(days=200)).strftime("%Y-%m-%d")      # keep the log to about half a year
    log = {k: v for k, v in log.items() if v["d"] >= cut}
    json.dump(log, open(LOG, "w"), separators=(",", ":"))
    print(f"sim grade: {n} props graded")


def record(log, lg):
    """Sim against the model's own price and the books' no-vig price, on the same graded props."""
    rows = [v for v in log.values() if v["lg"] == lg and v["res"] in ("over", "under") and v["p_nb"] is not None]
    if not rows:
        return dict(n=0)
    y = np.array([v["res"] == "over" for v in rows], float)
    def sc(p):
        p = np.asarray(p, float); c = np.clip(p, .01, .99)
        return dict(brier=round(float(((p - y) ** 2).mean()), 4), ll=round(float(-(y * np.log(c) + (1 - y) * np.log(1 - c)).mean()), 4))
    out = dict(n=len(rows), sim=sc([v["p_sim"] for v in rows]), model=sc([v["p_nb"] for v in rows]), over=round(float(y.mean()), 3))
    mk = [v for v in rows if v["p_mkt"] is not None]
    if mk:
        y2 = np.array([v["res"] == "over" for v in mk], float)
        f = lambda key: float(((np.array([v[key] for v in mk]) - y2) ** 2).mean())
        out["vs_books"] = dict(n=len(mk), sim=round(f("p_sim"), 4), model=round(f("p_nb"), 4), books=round(f("p_mkt"), 4))
    days = sorted({v["d"] for v in rows})
    out["since"] = days[0]; out["through"] = days[-1]
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["grade"]:
        grade()
    elif a[:1] == ["report"]:
        log = json.load(open(LOG)) if os.path.exists(LOG) else {}
        for lg in ("NBA", "NFL"):
            print(lg, json.dumps(record(log, lg)))
    else:
        main()

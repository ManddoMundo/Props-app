#!/usr/bin/env python3
"""The desk: price book lines against the model, log daily best bets, grade them, report.

  python3 daily.py news  <YYYY-MM-DD> <NBA|NFL> <injuries.txt|-> [lines.txt ...]   lineup news -> out/news.json (run BEFORE the models)
  python3 daily.py lines <YYYY-MM-DD> <NBA|NFL> <lines.txt> [...]   price pasted odds tables, write out/feed.json
  python3 daily.py pick  <YYYY-MM-DD> <NBA|NFL>                     log the day's best bets to out/history.json
  python3 daily.py evening <YYYY-MM-DD> <NBA|NFL> [late]            second look on the evening pull; "late" = refill scratched slots from the lineups run's pull
  python3 daily.py scratch <YYYY-MM-DD> <NBA|NFL>                   void today's open tickets on players ruled out (run AFTER the models, BEFORE evening)
  python3 daily.py explain <YYYY-MM-DD> <NBA|NFL>                   (re)write the case file on each bet and the day's pass list
  python3 daily.py close <YYYY-MM-DD> <NBA|NFL> "<label>" <late_lines.txt>   closing line check on the open bets
  python3 daily.py relay <YYYY-MM-DD>                              fetch and decrypt the day's lines and injury files from the GitHub relay
  python3 daily.py grade                                           settle open bets from the latest box scores
  python3 daily.py report                                          print the record
  python3 daily.py audit                                           grade every priced side (model vs book), update out/audit.json
  python3 daily.py shadow                                          update and report the shadow book (including market lane and Hard Rock-only cut)
Run after nfl.py / nba.py / build_data.py so out/data.json and the *_check.json files are current.

v3.52 upgrades:
  - Leave-one-out, sharp-weighted, power-devigged consensus in price_all() (toggled via use_loo_cons / use_power_devig).
  - Log-loss calib() restricted to market-checked post-v1.3 rows with tighter w cap (0.45) and prior (250).
  - Direct multi-book power-devig on alternate rungs in cmd_confident() when >= conf_books other books quote the same rung.
  - Direct NBA parquet grading (nba_box / nba_actual) so 4+ day schedule gaps never drop or mis-void NBA tickets.
  - Midday-only glob filter in cmd_audit() so _pm/_late priced files never leak into audit.json.
  - Hard Rock-only shadow tracking (hr_edge / hr_elig) for Florida execution visibility.
  - fill_live=False option so sub-3% leans track in shadow.json rather than diluting live history.json."""
import json, math, os, re, sys, unicodedata, datetime
import numpy as np
from scipy import stats, optimize
from common import nb_k, norm, pid_str, load_lineups

O = "/home/claude/props/out/"
D = "/home/claude/props/data/"
CFG = dict(bankroll=500.0, unit=25.0,
           max_units=2.0, day_units=10.0,
           min_daily=2, lean_edge=0.01, lean_units=0.25,
           fill_live=False,                  # v3.52: keep sub-3% leans in shadow tracking until 200+ graded sides prove +EV
           max_picks=3, max_per_game=2, min_edge=0.03, max_edge=0.12, min_adj_ev=0.025,
           min_odds=-160, max_odds=150, min_games=8, nba_min_minutes=20.0, book="hardrockbet",
           bet_books=["hardrockbet", "draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "fanatics"],
           sane=(1.0, 1.12),
           hold_edge={"NBA": 0.25, "NFL": 0.12},
           min_books=2,
           news_share=0.5, news_min=2,
           use_power_devig=True,             # v3.52: use power_fair() instead of proportional vig split
           use_loo_cons=True,                # v3.52: leave-one-out sharp-weighted consensus per candidate book
           mk_w={"fanduel": 1.5, "draftkings": 1.5, "kalshi": 0.5, "polymarket": 0.5},
           ref_books=["pinnacle"],
           mk_min_edge=0.01,
           pick_markets={"NBA": ["pts", "reb", "ast"], "NFL": ["rec_yds", "rush_yds", "pass_yds"]},
           cal_w0=0.25, cal_w_n0=250,        # v3.52: stronger prior (was 150) & lower cap (was 0.70) to prevent 1-week spikes
           cal_c_n0=5, cal_w_max=0.45,
           use_logloss_calib=True,           # v3.52: fit w by binary log-loss at the line on post-v1.3 market-checked rows
           conf_fair=0.72, conf_model=0.68, conf_edge=0.01, conf_min_odds=-500, conf_max_odds=-140, conf_books=3,
           conf_max=3, conf_nba_min=24.0,
           conf_exit=0.02, conf_cap=0.93)
VER = "1.7"
BOOKN = {"hardrockbet": "Hard Rock", "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars",
         "espnbet": "ESPN Bet", "pinnacle": "Pinnacle", "betrivers": "BetRivers", "fanatics": "Fanatics", "bovada": "Bovada",
         "polymarket": "Polymarket", "novig": "Novig", "kalshi": "Kalshi", "polymarket_us": "Polymarket US"}
TEAM = {"NBA": {"hawks": "ATL", "celtics": "BOS", "nets": "BKN", "hornets": "CHA", "bulls": "CHI", "cavaliers": "CLE", "mavericks": "DAL", "nuggets": "DEN",
                "pistons": "DET", "warriors": "GS", "rockets": "HOU", "pacers": "IND", "clippers": "LAC", "lakers": "LAL", "grizzlies": "MEM", "heat": "MIA",
                "bucks": "MIL", "timberwolves": "MIN", "pelicans": "NO", "knicks": "NY", "thunder": "OKC", "magic": "ORL", "76ers": "PHI", "suns": "PHX",
                "blazers": "POR", "kings": "SAC", "spurs": "SA", "raptors": "TOR", "jazz": "UTAH", "wizards": "WSH"},
        "NFL": {"cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF", "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
                "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB", "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
                "rams": "LA", "chargers": "LAC", "raiders": "LV", "dolphins": "MIA", "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
                "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "seahawks": "SEA", "49ers": "SF", "buccaneers": "TB", "titans": "TEN", "commanders": "WAS"}}
UNIT = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3": "threes", "pra": "points, rebounds and assists", "pr": "points and rebounds",
        "pa": "points and assists", "ra": "rebounds and assists", "pass_yds": "passing yards", "pass_att": "pass attempts", "pass_cmp": "completions",
        "pass_td": "passing touchdowns", "rush_yds": "rushing yards", "rush_att": "carries", "rec": "catches", "rec_yds": "receiving yards", "any_td": "touchdowns"}
NEWS = "/home/claude/props/out/news.json"
TIERS = [(.08, "AAA"), (.06, "AA"), (.04, "A"), (.025, "BBB"), (.01, "BB"), (0, "B"), (-9, "C")]
MK = {"NBA": {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3",
              "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa",
              "player_rebounds_assists": "ra"},
      "NFL": {"player_pass_yds": "pass_yds", "player_pass_attempts": "pass_att", "player_pass_completions": "pass_cmp",
              "player_pass_tds": "pass_td", "player_rush_yds": "rush_yds", "player_rush_attempts": "rush_att",
              "player_receptions": "rec", "player_reception_yds": "rec_yds", "player_anytime_td": "any_td"}}
COMBO = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
INV = {lg: {v: k for k, v in MK[lg].items()} for lg in MK}
NFL_LOG = {"pass_yds": "pyd", "pass_att": "att", "pass_cmp": "cmp", "pass_td": "ptd", "rush_yds": "ryd", "rush_att": "car",
           "rec": "rec", "rec_yds": "recyd"}
DATA = "/home/claude/props/data/"
NFL_RAW = {"pass_yds": "passing_yards", "pass_att": "attempts", "pass_cmp": "completions", "pass_td": "passing_tds",
           "rush_yds": "rushing_yards", "rush_att": "carries", "rec": "receptions", "rec_yds": "receiving_yards"}
_NFL_BOX, _NBA_BOX = {}, {}


def dec(a):
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def load():
    D = json.load(open(O + "data.json"))
    chk = {"NBA": json.load(open(O + "nba_check.json")), "NFL": json.load(open(O + "nfl_check.json"))}
    return D, chk


def history():
    p = O + "history.json"
    h = json.load(open(p)) if os.path.exists(p) else {"bets": [], "days": [], "updated": ""}
    if "legacy_unit" not in h:
        h["legacy_unit"] = h.get("unit", 0.5)
    h.update(bankroll=CFG["bankroll"], unit=CFG["unit"], lanes={"edge": CFG["bankroll"], "confident": CFG["bankroll"]})
    return h


EDGE_U = {"AAA": 1.5, "AA": 1.0, "A": 0.75, "BBB": 0.5}


def stake_units(b):
    if b.get("lean"):
        u = CFG["lean_units"]
    elif b.get("lane") == "confident":
        e, f = b["edge"], b["p"]
        u = 2.0 if (e >= .03 and f >= .80) else 1.5 if e >= .025 else 1.0 if e >= .015 else 0.5
    else:
        u = EDGE_U.get(b.get("rating"), 0.25) + (0.5 if b.get("best") else 0.0)
    return min(u, CFG["max_units"])


def scratched(b):
    return b.get("status") == "void" and bool(b.get("scratch"))


def day_units(h, date):
    return sum(b["units"] for b in h["bets"] if b["date"] == date and not b.get("superseded") and b.get("unit") and not scratched(b))


def put_stake(h, b):
    u = stake_units(b); room = CFG["day_units"] - day_units(h, b["date"])
    if room < CFG["lean_units"]:
        return False
    u = min(u, room)
    b.update(units=u, unit=CFG["unit"], usd=round(u * CFG["unit"], 2))
    return True


def save_history(h):
    h["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    json.dump(h, open(O + "history.json", "w"), indent=1)


def probs(L, lg, mkt, mu, line):
    if mkt == "any_td":
        p = 1 - math.exp(-max(mu, 0.0))
        return p, 1 - p, 0.0
    a, b = L["model"]["disp"][mkt]
    mu = max(float(mu), 1e-4)
    k = float(nb_k(mu, a, b)); pr = k / (k + mu)
    under = float(stats.nbinom.cdf(math.ceil(line) - 1, k, pr))
    push = float(stats.nbinom.pmf(int(line), k, pr)) if float(line).is_integer() else 0.0
    return 1 - under - push, under, push


def implied_mean(L, lg, mkt, line, p_over):
    """The projection a book's line and prices imply: the mean at which our own curve gives the book's no-vig over chance."""
    lo, hi = 0.02, max(6 * line + 20, 10)
    for _ in range(40):
        mid = (lo + hi) / 2
        ov, un, _ = probs(L, lg, mkt, mid, line)
        if ov / (ov + un) < p_over: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def power_fair(o, u):
    """v3.47/v3.52 the over's fair chance with the house cut removed via the power method:
    find k >= 1 such that (1/dec(o))^k + (1/dec(u))^k = 1; fair over chance = (1/dec(o))^k."""
    a, b = 1 / dec(o), 1 / dec(u)
    if a + b <= 1:
        return a / (a + b)
    lo, hi = 1.0, 6.0
    for _ in range(40):
        k = (lo + hi) / 2
        if a ** k + b ** k > 1: lo = k
        else: hi = k
    return a ** ((lo + hi) / 2)


def devig_over(o, u):
    """Over no-vig probability using power method (default since v3.52) or proportional split."""
    if CFG.get("use_power_devig", True):
        return power_fair(o, u)
    po, pu = 1 / dec(o), 1 / dec(u)
    return po / (po + pu)


def weighted_cons(impd, exclude=None):
    """Leave-one-out sharp-weighted mean of implied projections (falls back to unweighted median if disabled)."""
    items = [(v, CFG["mk_w"].get(k, 1.0)) for k, v in impd.items() if k != exclude]
    if not items:
        items = [(v, CFG["mk_w"].get(k, 1.0)) for k, v in impd.items()]
    if not items:
        return None
    if CFG.get("use_loo_cons", True):
        return float(sum(v * w for v, w in items) / sum(w for _, w in items))
    return float(np.median([v for v, _ in items]))


_CAL, _CEN = {}, {}


def centre(pairs):
    """Per-slate centring: the factor that puts the model's average projection on the market's average for one market."""
    n = len(pairs)
    if not n or sum(p[0] for p in pairs) <= 0:
        return 1.0
    r = sum(p[1] for p in pairs) / sum(p[0] for p in pairs)
    return float(np.clip((n * r + CFG["cal_c_n0"]) / (n + CFG["cal_c_n0"]), 0.85, 1.15))


def calib(D):
    """w per market: how far to move off the market toward the model. 0 trusts the market, 1 trusts the model.
    v3.52: restricted to post-v1.3 market-checked rows (ver present, nb >= min_books, mm present) and fitted by
    regularized binary log-loss at the posted line (with prior pull toward cal_w0), preventing outlier box scores
    and pre-v1.3 unanchored rows from distorting w."""
    if _CAL:
        return _CAL
    A = json.load(open(O + "audit.json")) if os.path.exists(O + "audit.json") else {}
    pairs, acc = {}, {}
    for k, r in A.items():
        pairs.setdefault(k.rsplit("|", 1)[0], {})[r["side"]] = r
    for pr in pairs.values():
        o = pr.get("Over")
        if not o or o["mkt"] not in D[o["lg"]]["model"]["disp"]:
            continue
        if not o.get("ver") or o.get("nb", 0) < CFG["min_books"] or o.get("mm") is None:
            continue
        acc.setdefault((o["lg"] + "|" + o["mkt"], o["date"]), []).append((o["mu"], o["mm"], o["line"], o["win"], o["result"]))
    for lg in MK:
        L = D[lg]
        for mkt in sorted(set(MK[lg].values())):
            if mkt not in L["model"]["disp"]:
                _CAL[lg + "|" + mkt] = dict(w=round(CFG["cal_w0"], 4), n=0)
                continue
            pts = []
            for (key, date), rows in acc.items():
                if key != lg + "|" + mkt:
                    continue
                c = centre([(r[0], r[1]) for r in rows])
                for mu, mm, line, win, res in rows:
                    pts.append((c * mu, mm, line, win, res))
            n = len(pts)
            if n < 10:
                _CAL[lg + "|" + mkt] = dict(w=round(CFG["cal_w0"], 4), n=n)
                continue
            if CFG.get("use_logloss_calib", True):
                a, b = L["model"]["disp"][mkt]
                cmu = np.array([x[0] for x in pts], float)
                mmv = np.array([x[1] for x in pts], float)
                lnv = np.array([x[2] for x in pts], float)
                yov = np.array([x[3] for x in pts], float)
                is_int = np.isclose(lnv, np.round(lnv))
                ceil_m1 = np.ceil(lnv) - 1
                ln_int = np.round(lnv).astype(int)

                def obj(w):
                    m = np.maximum(mmv + w * (cmu - mmv), 1e-4)
                    k = nb_k(m, a, b)
                    p = k / (k + m)
                    un = stats.nbinom.cdf(ceil_m1, k, p)
                    push = np.where(is_int, stats.nbinom.pmf(ln_int, k, p), 0.0)
                    ov = np.maximum(1.0 - un - push, 0.0)
                    pov = np.clip(ov / np.maximum(ov + un, 1e-9), 1e-4, 1 - 1e-4)
                    nll = -(yov * np.log(pov) + (1 - yov) * np.log(1 - pov)).sum()
                    # quadratic prior pull equivalent to cal_w_n0 pseudo-observations centered at cal_w0
                    prior = 0.5 * CFG["cal_w_n0"] * 0.25 * (w - CFG["cal_w0"]) ** 2
                    return float(nll + prior)

                res = optimize.minimize_scalar(obj, bounds=(0.0, CFG["cal_w_max"]), method="bounded")
                w = float(np.clip(res.x, 0.0, CFG["cal_w_max"]))
            else:
                d = np.array([x[0] - x[1] for x in pts], float)
                e = np.array([x[4] - x[1] for x in pts], float)
                wh = float((d * e).sum() / (d * d).sum()) if (d * d).sum() > 0 else CFG["cal_w0"]
                w = float(np.clip((n * wh + CFG["cal_w_n0"] * CFG["cal_w0"]) / (n + CFG["cal_w_n0"]), 0.0, CFG["cal_w_max"]))
            _CAL[lg + "|" + mkt] = dict(w=round(w, 4), n=n)
    json.dump(_CAL, open(O + "calib.json", "w"))
    return _CAL


def cv5(a):
    x = a[-5:]
    if len(x) < 3 or not np.mean(x):
        return 0.0
    return float(np.std(x) / np.mean(x))


def confidence(lg, p, mkt, mu, edge, game, side=None):
    c, flags = 1.0, []
    if p["n"] < 5: c *= .7; flags.append("thin history")
    elif p["n"] < 10: c *= .85; flags.append("short history")
    if lg == "NBA" and cv5(p["logs"]["min"]) > .22: c *= .88; flags.append("minutes swing")
    if lg == "NFL" and mkt.startswith("rec") and cv5(p["logs"]["tgt"]) > .5: c *= .9; flags.append("uneven targets")
    if lg == "NFL" and mkt.startswith("rush") and cv5(p["logs"]["car"]) > .5: c *= .9; flags.append("uneven carries")
    if p.get("missed"): c *= .8; flags.append("missed last game")
    if p.get("q"): c *= .8; flags.append("questionable")
    if lg == "NFL" and side and side.get("qbnew") and mkt.startswith(("pass", "rec")): c *= .85; flags.append("QB change")
    if lg == "NFL" and game.get("spread") is not None and abs(game["spread"]) >= 9.5: c *= .92; flags.append("blowout risk")
    if mkt != "any_td" and mu < 2: c *= .92; flags.append("low count")
    if edge >= .10: c *= .85; flags.append("large edge, check news")
    return c, flags


def parse(path, ref=False):
    rows = []
    for ln in open(path):
        t = ln.strip()
        c = [x.strip() for x in (t.strip("|") if t.startswith("|") else t).split("|")]
        if len(c) < 6 or c[0] in ("bookmaker_key", "") or set(c[0]) <= set("-: "):
            continue
        num = lambda s: (float(s.replace("+", "")) if re.fullmatch(r"[+-]?\d+(\.\d+)?", s) else None)
        if (c[0] in CFG["ref_books"]) != ref:
            continue
        rows.append(dict(book=c[0], market=c[1], player=c[2], line=num(c[3]), o=num(c[4]), u=num(c[5])))
    return rows


def cmd_news(date, lg, files):
    out, q, inn, qb_game, by_team, firm, coarse, strong, gbooks, pgame = set(), set(), set(), {}, {}, set(), set(), {}, {}, {}
    late = os.environ.get("FL_NEWS") == "late"
    if files and files[0] != "-":
        for ln in open(files[0]):
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(c) < 5 or c[0].lower() in ("team", "") or set(c[0]) <= set("-: "):
                continue
            st = c[4].lower(); code = TEAM[lg].get(c[0].lower().split()[-1]) if c[0].split() else None
            if any(k in st for k in ("out", "injured reserve", "doubtful", "suspen", "unable to perform", "non-football")):
                out.add(norm(c[1]))
                if "out" in st: firm.add(norm(c[1]))
                elif "doubtful" not in st: coarse.add(norm(c[1]))
                if code: by_team.setdefault(code, []).append([c[1], c[2]])
            elif any(k in st for k in ("day-to-day", "questionable", "game-time", "gtd")): q.add(norm(c[1]))
    num = lambda x: bool(re.fullmatch(r"[+-]?\d+(\.\d+)?", x))
    for fi, f in enumerate(files[1:]):
        game = None
        for ln in open(f):
            if ln.startswith("# game:"):
                game = ln.split(":", 1)[1].strip().replace(" ", ""); continue
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(c) < 6 or c[0] in ("bookmaker_key", "") or set(c[0]) <= set("-: ") or c[0] in CFG["ref_books"]:
                continue
            inn.add(norm(c[2]))
            if c[0] in CFG["bet_books"] and c[1] in MK[lg] and num(c[4]) and (c[1] == "player_anytime_td" or num(c[5])):
                strong.setdefault(norm(c[2]), set()).add(c[0])
                gk = (fi, game); gbooks.setdefault(gk, set()).add(c[0]); pgame.setdefault(norm(c[2]), set()).add(gk)
            if lg == "NFL" and c[1] == "player_pass_yds" and game and norm(c[2]) not in qb_game.setdefault(game, []):
                qb_game[game].append(norm(c[2]))
    cur = json.load(open(NEWS)) if os.path.exists(NEWS) else {}
    both = out & inn

    def enough(n):
        ng = max((len(gbooks[g]) for g in pgame.get(n, ())), default=0)
        return ng > 0 and len(strong.get(n, ())) >= max(min(CFG["news_min"], ng), math.ceil(CFG["news_share"] * ng))

    quoted_out = sorted(n for n in both if enough(n) and (not late or n in coarse))
    stays = sorted(both - set(quoted_out))
    out -= set(quoted_out); inn -= out
    by_team = {t: [x for x in v if norm(x[0]) in out] for t, v in by_team.items()}
    from zoneinfo import ZoneInfo
    cur[lg] = {"date": date, "out": sorted(out), "q": sorted(q), "in": sorted(inn), "qb_game": qb_game, "listed_out_but_quoted": quoted_out,
               "out_despite_quote": stays, "out_firm": sorted(out & firm), "out_team": by_team,
               "t": datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")}
    json.dump(cur, open(NEWS, "w"), indent=1)
    print(f"{lg} {date} news: {len(out)} out, {len(q)} questionable, {len(inn)} quoted by a book" + (f", book QBs {qb_game}" if qb_game else "")
          + (f", listed out but still posted by at least half the books on his game (treated as playing): {[(n, len(strong.get(n, ()))) for n in quoted_out]}" if quoted_out else "")
          + (f", listed out and kept out despite a leftover quote: {[(n, sorted(strong.get(n, ()))) for n in stays]}" if stays else ""))


def market_view(L, lg, mkt, side, bet, impd, impw=None):
    if mkt == "any_td":
        return None
    def at(bk, r, imps):
        odds = r["o"] if side != "Under" else r["u"]
        oth = [(v, CFG["mk_w"].get(k, 1.0)) for k, v in imps.items() if k != bk]
        if odds is None or len(oth) < CFG["min_books"]:
            return None
        mean = sum(v * w for v, w in oth) / sum(w for _, w in oth)
        ov, un, _ = probs(L, lg, mkt, mean, r["line"])
        p = (un if side == "Under" else ov) / (ov + un)
        return dict(book=bk, line=r["line"], odds=int(odds), p=round(p, 4), edge=round(p - 1 / dec(odds), 4), n=len(oth))
    top = tpw = None
    for bk, r in bet.items():
        a = at(bk, r, impd); w = at(bk, r, impw) if impw else None
        if a is None:
            continue
        if w: a["edge_pw"] = w["edge"]
        if top is None or a["edge"] > top["edge"]: top = a
        if w and (tpw is None or w["edge"] > tpw["edge"]): tpw = dict(w, edge_pw=w["edge"], edge=a["edge"], p=a["p"])
    if top and tpw and top["edge"] < CFG["mk_min_edge"] <= tpw["edge_pw"]:
        top["pw"] = {k: tpw[k] for k in ("book", "line", "odds", "p", "edge", "edge_pw", "n")}
    return top


def market_ticket(mk):
    if not mk:
        return None
    t = mk if mk["edge"] >= CFG["mk_min_edge"] else mk.get("pw")
    return t if t and CFG["min_odds"] <= t["odds"] <= CFG["max_odds"] else None


def market_est(L, b):
    if b["mkt"] == "any_td" or b.get("mm") is None or b.get("nb", 0) < CFG["min_books"] or b["mkt"] not in L["model"]["disp"]:
        return None
    ov, un, _ = probs(L, b["lg"], b["mkt"], b["mm"], b["line"])
    p = (un if b["side"] == "Under" else ov) / (ov + un)
    return dict(book=b.get("book"), line=b["line"], odds=b["odds"], p=round(p, 4), edge=round(p - 1 / dec(b["odds"]), 4), n=b["nb"], est=1)


def price_all(date, lg, files):
    D, chk = load(); L = D[lg]; CAL = calib(D)
    games = {g["id"]: g for g in L["games"]}
    byname = {}
    for p in L["players"]:
        byname.setdefault(norm(p["name"]), []).append(p)
    side_of = {}
    for s in L["sides"]:
        g = games[s["game"]]
        if lg == "NBA" and g["day"] != date:
            continue
        side_of[s["team"]] = s
    quotes = {}
    for f in files:
        for r in parse(f):
            quotes.setdefault((norm(r["player"]), r["market"]), {})[r["book"]] = r
    out, feed, miss, rows = [], {}, [], []

    def sane(x, mkt):
        if mkt == "any_td":
            return x["o"] is not None
        if x["line"] is None or x["o"] is None or x["u"] is None:
            return False
        return CFG["sane"][0] <= 1 / dec(x["o"]) + 1 / dec(x["u"]) <= CFG["sane"][1]

    for (nm, market), books in quotes.items():
        mkt = MK[lg].get(market)
        if not mkt:
            continue
        good = {bk: x for bk, x in books.items() if sane(x, mkt)}
        bet = {bk: x for bk, x in good.items() if bk in CFG["bet_books"]}
        if not bet:
            continue
        r0 = next(iter(bet.values()))
        cands = [p for p in byname.get(nm, []) if p["team"] in side_of]
        if len(cands) != 1:
            miss.append(f'{r0["player"]} ({r0["market"]})'); continue
        p = cands[0]; s = side_of[p["team"]]; g = games[s["game"]]
        m = chk[lg].get(f'{s["game"]}|{p["id"]}' if lg == "NBA" else p["id"])
        if not m or not p["active"]:
            miss.append(f'{r0["player"]} not in projected lineup'); continue
        mu = m["td"] if mkt == "any_td" else m[mkt]
        if mu <= 0:
            continue

        def imp_prop(x):
            if mkt == "any_td":
                return None
            po, pu = 1 / dec(x["o"]), 1 / dec(x["u"])
            return implied_mean(L, lg, mkt, x["line"], po / (po + pu))

        impd_prop = {bk: v for bk, v in ((bk, imp_prop(x)) for bk, x in good.items()) if v is not None}
        impw = {} if mkt == "any_td" else {bk: implied_mean(L, lg, mkt, x["line"], power_fair(x["o"], x["u"])) for bk, x in good.items() if bk in impd_prop}
        imp_live = impw if CFG.get("use_power_devig", True) else impd_prop
        mm = weighted_cons(imp_live, exclude=None) if imp_live else None
        rows.append(dict(bet=bet, mkt=mkt, p=p, s=s, g=g, m=m, mu=mu, mm=mm, nb=max(len(imp_live) - 1, 0),
                         q=good, impd=impd_prop, impw=impw, imp_live=imp_live))

    cen = {}
    for mkt in {x["mkt"] for x in rows}:
        z = [x for x in rows if x["mkt"] == mkt and x["mm"] is not None]
        good_z = [x for x in z if x["nb"] >= CFG["min_books"]]
        cen[mkt] = centre([(x["mu"], x["mm"]) for x in (good_z or z)])

    for x in rows:
        mkt, p, s, g, m, mu, mm, nb = (x[k] for k in ("mkt", "p", "s", "g", "m", "mu", "mm", "nb"))
        w = CAL.get(lg + "|" + mkt, {}).get("w", CFG["cal_w0"]); c0 = cen[mkt]
        hold_at = CFG["hold_edge"].get(lg, CFG["max_edge"])
        best, hr_rec = {}, {}
        for bk, r in x["bet"].items():
            line = .5 if mkt == "any_td" else r["line"]
            o = int(r["o"]) if r["o"] is not None else None
            u = int(r["u"]) if (r["u"] is not None and mkt != "any_td") else None
            # v3.52: leave-one-out sharp-weighted consensus (excludes bk itself so a stale soft book doesn't pull fair value)
            mm_bk = weighted_cons(x["imp_live"], exclude=bk) if x["imp_live"] else None
            nb_bk = sum(1 for k in x["imp_live"] if k != bk)
            muf = mu if mm_bk is None else mm_bk + w * (c0 * mu - mm_bk)
            pov, pun, _ = probs(L, lg, mkt, muf, line)
            pov0, pun0, _ = probs(L, lg, mkt, mu, line)
            povc, punc, _ = probs(L, lg, mkt, c0 * mu, line)
            for side, pw, pl, pw0, pl0, pwc, plc, odds in (("Over" if mkt != "any_td" else "Yes", pov, pun, pov0, pun0, povc, punc, o),
                                                           ("Under", pun, pov, pun0, pov0, punc, povc, u)):
                if odds is None:
                    continue
                pn = pw / (pw + pl); be = 1 / dec(odds); edge = pn - be; ev = pw * (dec(odds) - 1) - pl
                c, flags = confidence(lg, p, mkt, mu, edge, g, s)
                if nb_bk < CFG["min_books"]: flags.append("no market check")
                edgec = pwc / (pwc + plc) - be
                if edgec > hold_at: flags.append("model far from market, check news")
                adj = ev * (c if ev > 0 else 1)
                rec = dict(id=f"{date}|{lg}|{p['id']}|{mkt}", date=date, lg=lg, game=s["game"], gl=f'{g["away"]} @ {g["home"]}',
                           pid=p["id"], name=p["name"], team=p["team"], opp=s["opp"], mkt=mkt, side=side, line=line, odds=odds,
                           book=bk, mu=round(mu, 2), p=round(pn, 4), be=round(be, 4), edge=round(edge, 4), ev=round(ev, 4),
                           conf=round(c, 3), adj=round(adj, 4), rating=next(t[1] for t in TIERS if adj >= t[0]), flags=flags,
                           n=p["n"], mn=m.get("mn"), tag=(date[5:] if lg == "NBA" else "26W" + re.sub(r"\D", "", L["label"])),
                           ver=VER, nb=nb_bk, nbet=len(x["bet"]), muf=round(muf, 2), mm=(None if mm_bk is None else round(mm_bk, 2)),
                           cen=round(c0, 3), p0=round(pw0 / (pw0 + pl0), 4), edge0=round(pw0 / (pw0 + pl0) - be, 4), edgec=round(edgec, 4))
                if bk == CFG["book"]:
                    hr_rec[side] = dict(line=line, odds=odds, p=rec["p"], edge=rec["edge"], adj=rec["adj"], elig=eligible(rec))
                k = (adj, ev, bk == CFG["book"])
                if side not in best or k > best[side][0]:
                    best[side] = (k, rec)
        for side, v in best.items():
            mk = market_view(L, lg, mkt, side, x["bet"], x["impd"], x["impw"])
            if mk: v[1]["mk"] = mk
            if side in hr_rec:
                v[1]["hr"] = hr_rec[side]
        out += [v[1] for v in best.values()]
        top = max(best.values(), key=lambda v: v[0])[1]
        tb = x["bet"][top["book"]]
        hold = next((sd for sd, v in best.items() if v[1]["edgec"] > hold_at), None)
        feed[f'{lg}|{s["game"]}|{p["id"]}|{mkt}'] = {"line": top["line"], "o": int(tb["o"]) if tb["o"] is not None else None,
                                                    "u": int(tb["u"]) if (tb["u"] is not None and mkt != "any_td") else None,
                                                    "book": top["book"], "nb": top["nb"],
                                                    **({} if top["mm"] is None else {"m": round(top["muf"], 3), "mm": round(top["mm"], 3)}),
                                                    **({"hold": hold} if hold else {})}
    _CEN[lg] = cen
    return out, feed, miss


RELAY = "https://raw.githubusercontent.com/ManddoMundo/Props-app/main/"


def cmd_relay(date):
    import subprocess
    base = os.environ.get("RELAY_BASE", RELAY)

    def fetch(path):
        r = subprocess.run(["curl", "-sfL", "-m", "60", base + path], capture_output=True)
        return r.stdout if r.returncode == 0 and r.stdout else None
    raw = fetch("status.json")
    if raw is None:
        print("RELAY: no status file. The job has not run yet, or the repository is not public."); return 3
    st = json.loads(raw); q = st.get("quota") or {}
    print(f"RELAY: last run {st.get('et')} ET ({st.get('kind')}, plan tier {st.get('tier')}), spent {st.get('spent')} credits, {q.get('remaining')} left, {q.get('used')} used this month")
    for e in st.get("errors") or []: print("  relay error:", e)
    for e in st.get("notes") or []: print("  relay note:", e)
    files = [f for f in st.get("files") or [] if f.get("date") == date]
    if not files:
        print(f"RELAY: nothing saved for {date}"); return 3
    if not os.environ.get("RELAY_PASS"):
        print("RELAY: RELAY_PASS is not set, cannot decrypt"); return 3
    got = 0
    for f in files:
        d = O + f["what"] + "/"; name = os.path.basename(f["path"])[:-4]; os.makedirs(d, exist_ok=True)
        blob = fetch(f["path"])
        if blob is None:
            print("  missing in the repo:", f["path"]); continue
        open(d + name + ".enc", "wb").write(blob)
        r = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-pass", "env:RELAY_PASS",
                            "-in", d + name + ".enc", "-out", d + name + ".tmp"], capture_output=True)
        os.remove(d + name + ".enc")
        ok = r.returncode == 0 and open(d + name + ".tmp", errors="replace").readline().startswith(("# relay", "Source: ESPN", "Source: nba.com"))
        if not ok:
            print("  could not decrypt (wrong RELAY_PASS?):", f["path"])
            if os.path.exists(d + name + ".tmp"): os.remove(d + name + ".tmp")
            continue
        os.replace(d + name + ".tmp", d + name)
        if f["what"] == "lines":
            hr = sum(v for k, v in (f.get("books") or {}).items() if k in CFG["bet_books"])
            print(f"  saved {d + name}: {f.get('kind')} pull {f.get('et')} ET, {f.get('games')} games, {f.get('rows')} rows from {len(f.get('books') or {})} books, "
                  f"{f.get('markets')} markets, rows at books the desk bets {hr}" + ("" if hr else "  <-- no book the desk bets had posted: use the WebFetch fallback for this league"))
            got += f.get("kind") == "midday" and hr > 0
        else:
            print(f"  saved {d + name}: injury report pulled {f.get('et')} ET, {f.get('rows')} players")
    return 0 if got else 3


def cmd_today(date, src, dst):
    out, keep, hold, n = [], True, None, 0
    for ln in open(src):
        if ln.startswith("# game:"):
            hold, keep = ln, None; continue
        if keep is None:
            if ln.startswith("# tip:"):
                keep = ln.split(":", 1)[1].strip().startswith(date)
                if keep: out += [hold, ln]
                continue
            keep = True; out.append(hold)
        if keep:
            out.append(ln); n += ("|" in ln and not ln.startswith(("#", "bookmaker_key")))
    open(dst, "w").writelines(out)
    print(f"today: {n} quotes for games on {date}")
    return 0 if n else 3


def cmd_mirror():
    import subprocess
    r = subprocess.run(f"curl -sfL -m 120 {RELAY}state/state.tar.gz.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -pass env:RELAY_PASS | tar -C /home/claude/props -xzf -",
                       shell=True, capture_output=True, text=True, executable="/bin/bash")
    print("MIRROR:", "books unpacked into /home/claude/props/out" if r.returncode == 0 else "FAILED " + r.stderr[-200:])
    return 0 if r.returncode == 0 else 3


def cmd_summary(date, kind, note):
    h = history(); B = h["bets"]
    print(json.dumps({"date": date, "kind": kind, "ok": True, "version": open(os.path.dirname(os.path.abspath(__file__)) + "/VERSION").read().strip(), "note": note.strip(),
                      "bets": len(B), "open": sum(b["status"] == "open" for b in B), "picks_today": sum(b["date"] == date and not b.get("superseded") and not scratched(b) for b in B),
                      "scratched_today": sum(b["date"] == date and scratched(b) for b in B)}))


def cmd_lines(date, lg, files):
    priced, feed, miss = price_all(date, lg, files)
    fp = O + "feed.json"
    cur = json.load(open(fp)) if os.path.exists(fp) else {}
    cur = {k: v for k, v in cur.items() if not k.startswith(lg + "|")} if not any(k in cur for k in feed) else cur
    cur.update(feed)
    json.dump(cur, open(fp, "w"))
    os.makedirs(O + "priced", exist_ok=True)
    sfx = {"pm": "_pm", "late": "_late"}.get(os.environ.get("FL_RUN"), "")
    for b in priced:
        if sfx: b["run"] = sfx[1:]
    json.dump(priced, open(O + f"priced/{lg}_{date}{sfx}.json", "w"))
    chk2 = sum(1 for v in feed.values() if v["nb"] >= CFG["min_books"])
    print(f"{lg} {date}: {len(feed)} lines matched, {chk2} with a market check from {CFG['min_books']}+ other books, {len(priced)} sides priced, {len(miss)} unmatched")
    cal = calib(None)
    print("  model weight vs market (w, graded lines behind it):", {k.split("|")[1]: (v["w"], v["n"]) for k, v in cal.items() if k.startswith(lg) and v["n"]})
    print("  slate centring (market average / model average):", {k: round(v, 3) for k, v in _CEN.get(lg, {}).items()})
    if miss:
        print("  unmatched:", "; ".join(sorted(set(miss))[:25]))


def eligible(b):
    if b["mkt"] not in CFG["pick_markets"].get(b["lg"], []): return False
    if not (CFG["min_odds"] <= b["odds"] <= CFG["max_odds"]): return False
    if b["n"] < CFG["min_games"]: return False
    if b["lg"] == "NBA" and (b["mn"] or 0) < CFG["nba_min_minutes"]: return False
    if "missed last game" in b["flags"] or "questionable" in b["flags"]: return False
    if b.get("nb", 0) < CFG["min_books"]: return False
    if b.get("edgec", 0) > CFG["hold_edge"].get(b["lg"], CFG["max_edge"]): return False
    return CFG["min_edge"] <= b["edge"] <= CFG["max_edge"] and b["adj"] >= CFG["min_adj_ev"]


def cmd_pick(date, lg):
    h = history()
    if any(b["date"] == date and b["lg"] == lg and not b.get("superseded") and b.get("lane") != "confident" for b in h["bets"]):
        print("already picked for", lg, date); return
    priced = json.load(open(O + f"priced/{lg}_{date}.json"))
    pool = sorted([b for b in priced if eligible(b)], key=lambda b: -b["adj"])
    big = sum(1 for b in priced if b["edge"] > CFG["max_edge"] or b.get("edgec", 0) > CFG["hold_edge"].get(b["lg"], CFG["max_edge"]))
    picks, per_game, seen = [], {}, set()
    for b in pool:
        if b["pid"] in seen or per_game.get(b["game"], 0) >= CFG["max_per_game"]:
            continue
        seen.add(b["pid"]); per_game[b["game"]] = per_game.get(b["game"], 0) + 1
        picks.append(b)
        if len(picks) == CFG["max_picks"]:
            break
    logged = 0
    for i, b in enumerate(picks):
        b = dict(b); b.update(best=(logged == 0), status="open", result=None, lane="edge")
        for k in ("be", "conf", "adj", "n"):
            b.pop(k, None)
        if not put_stake(h, b):
            print("  day is full at", CFG["day_units"], "units:", b["name"]); continue
        h["bets"].append(b); logged += 1
        print(f'  {"BEST" if i == 0 else "pick"}: {b["name"]} {b["side"]} {b["line"]} {b["mkt"]} {b["odds"]:+d}  prob {b["p"]:.1%}  edge {b["edge"]*100:+.1f}  {b["rating"]}  | model {b["mu"]} market {b["mm"]} ({b["nb"]} books) blended {b["muf"]}  {b["flags"]}')
    h["days"] = [d for d in h["days"] if not (d["date"] == date and d["lg"] == lg)]
    h["days"].append(dict(date=date, lg=lg, sides_priced=len(priced), cleared_bar=len(pool), picks=logged, skipped_large_edge=big))
    save_history(h)
    print(f"{lg} {date}: {len(priced)} sides priced, {len(pool)} cleared the bar, {logged} logged, {big} skipped for an edge too large to trust")
    cmd_explain(date, lg)


def retest(h, date, lg, pm, run):
    X = {(x["id"], x["side"]): x for x in pm}; n = 0
    from zoneinfo import ZoneInfo
    t = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p")
    D, _ = load(); L = D[lg]
    for b in h["bets"]:
        if b["date"] != date or b["lg"] != lg or b.get("superseded") or b["status"] != "open" or b.get("lane") == "confident" or b.get("alt") or b["mkt"] == "any_td":
            continue
        x = X.get((b["id"], b["side"])); first = (b.get("retest") or {}).get("first") or ({k: b["retest"][k] for k in ("t", "run", "ok", "code")} if b.get("retest") else None)
        if x is None:
            r = dict(t=t, run=run, ok=None, code="NO LINE", why="No book had this side at this pull, so it could not be retested.")
        else:
            if b.get("lean"):
                soft = dict(x, edge=max(x["edge"], CFG["min_edge"]), adj=max(x["adj"], CFG["min_adj_ev"]))
                ok = eligible(soft) and CFG["lean_edge"] <= x["edge"] <= CFG["max_edge"] and x["adj"] > 0
            else:
                ok = eligible(x)
            code, why = ("CLEARS", "It clears every test again at the line and price on the board now.") if ok else pass_reason(x)
            if not ok and b.get("lean") and code in ("THIN EDGE", "HAIRCUT"):
                code, why = "THIN EDGE", f"Edge {x['edge'] * 100:+.1f} points. A lean needs {CFG['lean_edge'] * 100:.0f}."
            if not ok and code == "CAP":
                code, why = ("EDGE TOO WIDE", f"Edge {x['edge'] * 100:+.1f} points is past the {CFG['max_edge'] * 100:.0f} point ceiling. A gap that wide is usually news.") if x["edge"] > CFG["max_edge"] else ("THIN EDGE", f"Edge {x['edge'] * 100:+.1f} points. A lean needs {CFG['lean_edge'] * 100:.0f}.")
            r = dict(t=t, run=run, book=x.get("book"), line=x["line"], odds=x["odds"], p=x["p"], edge=x["edge"], muf=x.get("muf"), ok=bool(ok), code=code, why=why)
            try:
                ov, un, _ = probs(L, lg, b["mkt"], x.get("muf", x["mu"]), b["line"]); ph = (ov if b["side"] == "Over" else un) / (ov + un)
                r.update(held=round(float(ph), 4), hedge=round(float(ph) - 1 / dec(b["odds"]), 4))
            except Exception:
                pass
        if first: r["first"] = first
        b["retest"] = r; n += 1
        print(f'  retest {b["name"]} {b["side"]} {b["line"]} {b["mkt"]}: {r["code"]}' + (f' (now {r["line"]} at {r["odds"]:+d}, edge {r["edge"] * 100:+.1f}; the ticket as held {r.get("hedge", 0) * 100:+.1f})' if x is not None else ""))
    return n


def retest_note(h):
    R = [b for b in h["bets"] if b.get("retest") and not b.get("superseded") and b["status"] in ("won", "lost")]
    if not R: return
    pl = lambda b: (dec(b["odds"]) - 1) * b["units"] if b["status"] == "won" else -b["units"]
    for lab, m in (("still cleared", lambda b: b["retest"]["ok"] is True), ("no longer cleared", lambda b: b["retest"]["ok"] is False), ("no line to retest", lambda b: b["retest"]["ok"] is None)):
        z = [b for b in R if m(b)]
        if not z: continue
        cl = [b["close"]["clv"] for b in z if b.get("close")]
        print(f"  retest, {lab:<18} {sum(b['status'] == 'won' for b in z)}-{sum(b['status'] == 'lost' for b in z)}  units {sum(pl(b) for b in z):+.2f}" + (f"  later line {np.mean(cl) * 100:+.1f}% on {len(cl)}" if cl else ""))


def cmd_evening(date, lg, sfx="_pm"):
    late = sfx == "_late"
    fp = O + f"priced/{lg}_{date}{sfx}.json"
    if not os.path.exists(fp):
        print(f"{lg} {date}: no {'late' if late else 'evening'} lines priced"); return
    h = history(); pm = json.load(open(fp))
    am_fp = O + f"priced/{lg}_{date}.json"; am = json.load(open(am_fp)) if os.path.exists(am_fp) else []
    A = {(x["id"], x["side"]): x for x in am}
    moves, n_moved, n_both = [], 0, 0
    for x in pm:
        if x["side"] not in ("Over", "Yes"): continue
        a = A.get((x["id"], x["side"]))
        if not a: continue
        n_both += 1
        dl = (x["line"] or 0) - (a["line"] or 0); dp = x["p"] - a["p"]
        if dl or x["odds"] != a["odds"]: n_moved += 1
        elif abs(dp) < .05: continue
        moves.append(dict(name=x["name"], team=x["team"], mkt=x["mkt"], l0=a["line"], l1=x["line"], o0=a["odds"], o1=x["odds"],
                          p0=round(a["p"], 4), p1=round(x["p"], 4), m0=a.get("muf"), m1=x.get("muf"), dl=dl, dp=round(dp, 4)))
    moves.sort(key=lambda m: (-abs(m["dl"]), -abs(m["dp"])))
    try: retest(h, date, lg, pm, sfx[1:])
    except Exception as e: print("  retest skipped:", e)
    today = [b for b in h["bets"] if b["date"] == date and b["lg"] == lg and not b.get("superseded")]
    taken = {b["pid"] for b in today}; per_game = {}
    live = [b for b in today if not scratched(b)]
    gone = [b for b in today if scratched(b) and b.get("lane") != "confident" and not b.get("lean") and not b["scratch"].get("replaced_by")]
    for b in live:
        per_game[b["game"]] = per_game.get(b["game"], 0) + 1
    room = CFG["max_picks"] - sum(1 for b in live if b.get("lane") != "confident" and not b.get("lean"))
    if late: room = min(room, len(gone))
    pool = sorted([b for b in pm if eligible(b)], key=lambda b: -b["adj"]); picks = []
    for b in pool:
        if room <= 0: break
        if b["pid"] in taken or per_game.get(b["game"], 0) >= CFG["max_per_game"]: continue
        b = dict(b); b.update(best=False, status="open", result=None, lane="edge", run=sfx[1:])
        for k in ("be", "conf", "adj", "n"):
            b.pop(k, None)
        if not put_stake(h, b):
            print("  day is full at", CFG["day_units"], "units:", b["name"]); break
        if gone:
            g = gone.pop(0); b["replaces"] = g["name"]; g["scratch"]["replaced_by"] = b["name"]
        h["bets"].append(b); picks.append(b); taken.add(b["pid"]); per_game[b["game"]] = per_game.get(b["game"], 0) + 1; room -= 1
        print(f'  {"late" if late else "evening"} pick: {b["name"]} {b["side"]} {b["line"]} {b["mkt"]} {b["odds"]:+d}  prob {b["p"]:.1%}  edge {b["edge"]*100:+.1f}  {b["rating"]}  | model {b["mu"]} market {b["mm"]} blended {b["muf"]}')
    from zoneinfo import ZoneInfo
    t = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p")
    rec = next((d for d in h["days"] if d["date"] == date and d["lg"] == lg), None)
    if rec is None:
        rec = dict(date=date, lg=lg, sides_priced=0, cleared_bar=0, picks=0); h["days"].append(rec)
    if late:
        rec["late"] = dict(t=t, sides_priced=len(pm), cleared_bar=len(pool), picks=len(picks))
    else:
        rec["pm"] = dict(t=t, sides_priced=len(pm), cleared_bar=len(pool), picks=len(picks), moved=n_moved, compared=n_both, moves=moves[:12])
    save_history(h)
    print(f"{lg} {date} {'late' if late else 'evening'}: {len(pm)} sides priced, {len(pool)} cleared the bar, {len(picks)} new" + ("" if late else f", {n_moved} of {n_both} props moved since midday"))
    if picks:
        cmd_explain(date, lg, sfx)
        h = history()
        for b in h["bets"]:
            if b["date"] == date and b["lg"] == lg and b.get("replaces") and b.get("why") and not b["why"].get("repl"):
                g = next((x for x in h["bets"] if x["date"] == date and x["lg"] == lg and x["name"] == b["replaces"] and x.get("scratch")), None)
                b["why"]["repl"] = True
                b["why"]["head"] = f'Takes the slot of {b["replaces"]}, scratched{" at " + g["scratch"]["t"] if g else ""}. ' + b["why"]["head"]
        save_history(h)


def cmd_scratch(date, lg):
    news = (json.load(open(NEWS)) if os.path.exists(NEWS) else {}).get(lg, {})
    firm = set(news.get("out_firm", [])) if news.get("date") == date else set()
    LU = load_lineups(lg, date) if lg == "NBA" else {}
    from zoneinfo import ZoneInfo
    t = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
    h = history(); n = 0
    for b in h["bets"]:
        if b["date"] != date or b["lg"] != lg or b["status"] != "open" or b.get("superseded"):
            continue
        nm = norm(b["name"])
        why = "listed out on the injury report" if nm in firm else "on the league's inactive list" if nm in LU.get(b["team"], {}).get("inactive", ()) else None
        if not why:
            continue
        b["status"] = "void"; b["scratch"] = dict(t=t, why=why); n += 1
        if b.get("why") and not b["why"].get("scr"):
            b["why"]["scr"] = True
            b["why"]["head"] = f"Scratched at {t}: {b['name']} is {why}. The ticket is void, as a book would void it. " + b["why"]["head"]
        print(f"  scratched: {b['name']} {b['side']} {b['line']} {b['mkt']} {b['odds']:+d} ({why})")
    if n:
        rec = next((d for d in h["days"] if d["date"] == date and d["lg"] == lg), None)
        if rec is not None:
            rec["scratched"] = [dict(name=b["name"], mkt=b["mkt"], side=b["side"], line=b["line"], t=b["scratch"]["t"], why=b["scratch"]["why"])
                                for b in h["bets"] if b["date"] == date and b["lg"] == lg and b.get("scratch")]
        save_history(h)
    print(f"{lg} {date}: {n} tickets scratched")


def _last(name):
    t = [x for x in name.split() if x.strip(".").lower() not in ("jr", "sr", "ii", "iii", "iv", "v")]
    return t[-1] if t else name


def _logs(lg, p, mkt):
    l = p["logs"]
    if lg == "NBA":
        v = [sum(l[k][i] for k in COMBO.get(mkt, [mkt])) for i in range(len(l["d"]))]
        return v, list(l["d"]), list(l["opp"]), list(l["min"])
    key = NFL_LOG.get(mkt)
    v = [1 if (l["rtd"][i] + l["rectd"][i]) > 0 else 0 for i in range(len(l["wk"]))] if mkt == "any_td" else list(l[key])
    return v, [w.split("W")[-1] and "W" + w.split("W")[-1] for w in l["wk"]], list(l["opp"]), None


def _quotes(files):
    q = {}
    for f in files:
        if os.path.exists(f):
            for r in parse(f):
                q.setdefault((norm(r["player"]), r["market"]), {})[r["book"]] = r
    return q


def explain(b, D, quotes, news, mn=None):
    lg, mkt = b["lg"], b["mkt"]; L = D[lg]
    p = next((x for x in L["players"] if x["id"] == b["pid"]), None)
    s = next((x for x in L["sides"] if x["game"] == b["game"] and x["team"] == b["team"]), {})
    g = next((x for x in L["games"] if x["id"] == b["game"]), {})
    over = b["side"] in ("Over", "Yes"); line, odds = b["line"], b["odds"]; be = 1 / dec(odds)
    unit, last, sw = UNIT.get(mkt, mkt), _last(b["name"]), ("Over" if b["side"] in ("Over", "Yes") else "Under")
    pc = lambda x: f"{x * 100:.1f}%"

    def sidep(mean):
        ov, un, _ = probs(L, lg, mkt, mean, line)
        return (ov if over else un) / (ov + un)

    books = []
    for bk, r in quotes.get((norm(b["name"]), INV[lg].get(mkt)), {}).items():
        imp = None
        if mkt != "any_td" and r["line"] is not None and r["o"] is not None and r["u"] is not None:
            imp = implied_mean(L, lg, mkt, r["line"], devig_over(r["o"], r["u"]))
        books.append(dict(k=bk, n=BOOKN.get(bk, bk), line=r["line"], o=None if r["o"] is None else int(r["o"]), u=None if r["u"] is None else int(r["u"]),
                          imp=None if imp is None else round(imp, 2), fair=None if imp is None else round(sidep(imp), 4)))
    BB = b.get("book") or CFG["book"]; BN = BOOKN.get(BB, BB)
    books.sort(key=lambda x: (x["k"] != BB, x["n"]))
    others = [x for x in books if x["k"] != BB and x["imp"] is not None]
    hr = next((x for x in books if x["k"] == BB), None)
    mm, cen, mu, muf = b.get("mm"), b.get("cen", 1.0), b["mu"], b.get("muf", b["mu"])
    p_desk = b["p"]; p_mkt = sidep(mm) if mm else None; p_model = sidep(cen * mu)
    hr_nv = hr["fair"] if hr and hr["fair"] is not None else None
    gap = (p_mkt - hr_nv) if (p_mkt is not None and hr_nv is not None) else 0.0
    tilt = (p_desk - p_mkt) if p_mkt is not None else 0.0
    kind = "both" if (gap >= .02 and tilt >= .015) else "price" if gap >= .02 else "model" if tilt >= .015 else "thin"
    head = {"price": f"A price play. {BN}'s number on {last} is out of line with the other {len(others)} books, and the {sw} is the side they lean to.",
            "model": f"A model play. {BN} is priced like the other books. The edge is the model seeing {'more' if over else 'fewer'} {unit} for {last} than any of them.",
            "both": f"Price and model agree. {BN} is softer than the other books on the {sw}, and the model leans the same way.",
            "thin": "A thin one. A small price gap and a small model lean add up to just enough."}[kind]
    pts = []
    oq = "; ".join(f"{x['n']} {x['line']:g} ({x['o']:+d}/{x['u']:+d})" for x in others)
    t = f"{BN} has the {sw} {line:g} at {odds:+d}, which needs {pc(be)} to break even."
    if others and p_mkt is not None:
        t += f" The others: {oq}. With the house cut taken out, those books make the {sw} {line:g} a {pc(p_mkt)} shot."
        if hr_nv is not None:
            t += f" {BN}'s own prices say {pc(hr_nv)}."
            t += (f" That {gap * 100:.1f} point gap is the price edge." if gap >= .02 else f" {BN} is the worst of the prices on this side, so the model has to carry the bet." if gap <= -.02
                  else f" No real gap: {BN} is in line with the market.")
    pts.append(["Price", t])
    t = f"The model projects {mu:.1f} {unit}" + (f" on {mn:.0f} minutes" if (lg == "NBA" and mn) else "") + "."
    if lg == "NBA" and p and mkt in p.get("r", {}):
        t += f" That is {p['r'][mkt] * 36:.1f} per 36 minutes by its blend of this season and last" + (", built from the shots he takes and a steadied shooting percentage." if mkt in ("pts", "fg3") and p.get("sh") else ".")
    if lg == "NFL" and p:
        if mkt.startswith("rec"): t += f" He has drawn about {p['ts'] * 100:.0f}% of the team's targets."
        if mkt.startswith("rush"): t += f" He has taken about {p['cs'] * 100:.0f}% of the carries."
    if mm:
        if abs(cen - 1) >= .01:
            t += (f" Across tonight's slate the model ran {abs(cen - 1) * 100:.0f}% {'under' if cen > 1 else 'over'} the books, so its number is "
                  f"{'lifted' if cen > 1 else 'trimmed'} to {cen * mu:.1f} before the two are compared.")
        den = cen * mu - mm
        w = (muf - mm) / den if abs(den) > 1e-6 else 0
        t += f" The other books imply {mm:.1f}. The desk number is {muf:.1f}: the market, moved {max(0, min(1, w)) * 100:.0f}% of the way toward the model."
    pts.append(["Model", t])
    l10 = None
    if p:
        v, tags, opp, mins = _logs(lg, p, mkt); n = len(v)
        if n:
            hit = sum(1 for z in v if (z > line if over else z < line)); push = sum(1 for z in v if z == line)
            a5 = float(np.mean(v[-5:]))
            t = f"Last {n}: {', '.join(str(z) for z in v)}. " + (f"{'Cleared' if over else 'Stayed under'} {line:g} in {hit} of {n}" + (f" with {push} landing on the number" if push else "") + ".")
            t += f" Last five average {a5:.1f}" + (f" on {np.mean(mins[-5:]):.0f} minutes a night." if mins else ".")
            r = hit / n
            t += (" Recent form backs the bet." if r >= .6 else " Recent form argues against it. This bet rests on the price and the projection, not on a streak." if r <= .4 else " Recent form is close to a coin flip.")
            pts.append(["Form", t]); l10 = dict(v=v, t=tags, o=opp, hit=hit, n=n)

    def outs(team):
        inm = {norm(x["name"]): x for x in L["players"] if x["team"] == team}
        z = [x for x in news.get("out_team", {}).get(team, []) if lg == "NBA" or x[1] in ("QB", "RB", "WR", "TE", "FB")]
        z.sort(key=lambda x: -(inm.get(norm(x[0]), {}).get("m", 0) if lg == "NBA" else 0))
        return [x[0] + (f" ({inm[norm(x[0])]['m']:.0f} min)" if lg == "NBA" and norm(x[0]) in inm else f" ({x[1]})" if lg == "NFL" else "") for x in z[:5]]

    if news.get("date") == b["date"]:
        a, o2 = outs(b["team"]), outs(b["opp"])
        t = (f"Out for {b['team']}: {', '.join(a)}. " if a else f"Nobody is listed out for {b['team']}. ") + (f"Out for {b['opp']}: {', '.join(o2)}." if o2 else f"Nobody is listed out for {b['opp']}.")
        qs = [x["name"] for x in L["players"] if x["team"] in (b["team"], b["opp"]) and x.get("q") and x.get("active")]
        if qs: t += f" Questionable: {', '.join(qs[:4])}."
        if lg == "NBA" and p and mn: t += f" The model has {last} at {mn:.0f} minutes against a recent average of {p['m']:.0f}."
        if lg == "NFL" and s.get("qbnew"): t += f" {b['team']} start a quarterback who did not play their last game."
        pts.append(["Lineup", t])
    t = ""
    if lg == "NBA":
        ks = COMBO.get(mkt, [mkt]); f = float(np.mean([s.get("oppf", {}).get(k, 1.0) for k in ks])) if s.get("oppf") else None
        if f is not None:
            t = (f"{b['opp']} allow {abs(f - 1) * 100:.0f}% {'more' if f > 1 else 'fewer'} {unit} than the league average." if abs(f - 1) >= .015 else f"{b['opp']} are a league average matchup for {unit}.")
        t += f" {b['team']} are {'at home' if s.get('home') else 'on the road'}."
    else:
        adj = s.get("padj") if mkt.startswith(("rec", "pass")) else s.get("radj") if mkt.startswith("rush") else None
        if adj: t = f"{b['opp']} have allowed {abs(adj - 1) * 100:.0f}% {'more' if adj > 1 else 'less'} {'through the air' if mkt.startswith(('rec', 'pass')) else 'on the ground'} than an average defense."
        if g.get("spread") is not None: t += f" The {'home' if g['spread'] > 0 else 'road'} side is favored by {abs(g['spread']):g} with a total of {g.get('total', 0):g}."
    if t.strip(): pts.append(["Matchup", t.strip()])
    pts.append(["Math", f"At {odds:+d} the bet needs {pc(be)}. The desk makes it {pc(p_desk)}. Edge {b['edge'] * 100:+.1f} points, worth {b['ev'] * 100:+.1f} cents per dollar staked. Rated {b['rating']}."])
    risks = []
    ec = b.get("edgec", 0)
    if ec >= .08: risks.append(f"The model on its own is {ec * 100:.0f} points from the book. The hold starts at {CFG['hold_edge'].get(lg, CFG['max_edge']) * 100:.0f}. If something changed today that box scores do not show, this is the kind of bet it burns.")
    if odds <= -140: risks.append(f"You lay {abs(odds) / 100:.2f} to win 1. A loss costs more than a win pays.")
    if mkt != "any_td" and line <= 3.5: risks.append("A low line. One play either way decides it.")
    if l10 and l10["n"] >= 5 and l10["hit"] / l10["n"] <= .4: risks.append(f"He has {'cleared' if over else 'stayed under'} this number in only {l10['hit']} of his last {l10['n']}.")
    if lg == "NBA" and over and mn and mn < 26: risks.append(f"An Over needs minutes and he is projected for {mn:.0f}.")
    FL = {"minutes swing": "His minutes have swung a lot over the last five games.", "uneven targets": "His targets have been uneven.", "uneven carries": "His carries have been uneven.",
          "short history": "Short history on file.", "thin history": "Very little history on file.", "blowout risk": "A lopsided spread can cut or pad volume.",
          "QB change": "New quarterback: the passing game is harder to read.", "low count": "A low count stat. One play swings it."}
    risks += [FL[f] for f in b.get("flags", []) if f in FL and FL[f] not in risks]
    risks.append("Anything that broke after the lines were pulled is not in this number.")
    return dict(kind=kind, head=head, pts=pts, risks=risks, books=books, l10=l10, mn=mn,
                ruler=dict(be=round(be, 4), hr=hr_nv, mkt=None if p_mkt is None else round(p_mkt, 4), model=round(p_model, 4), desk=round(p_desk, 4)))


def pass_reason(b):
    if b["mkt"] not in CFG["pick_markets"].get(b["lg"], []):
        return "ON TRIAL", "A market on trial: priced and graded in the audit, not picked until it has 200 graded sides and the weekly review adds it."
    if b.get("nb", 0) < CFG["min_books"]:
        return "NO SECOND BOOK", f"Only {b.get('nb', 0)} other book{'s' if b.get('nb', 0) != 1 else ''} quoting it. No market check, no bet."
    if "questionable" in b["flags"]:
        return "QUESTIONABLE", "Listed questionable. The desk does not bet a player whose status is open."
    if "missed last game" in b["flags"]:
        return "ROLE UNKNOWN", "He has been out. His role on return is a guess."
    if b.get("edgec", 0) > CFG["hold_edge"].get(b["lg"], CFG["max_edge"]):
        return "HOLD: NEWS?", f"The model alone is {b['edgec'] * 100:.0f} points from the book. A gap that wide is usually news the model has not seen, so it is held."
    if not (CFG["min_odds"] <= b["odds"] <= CFG["max_odds"]):
        return "PRICE", f"{b['odds']:+d} is outside the prices the desk plays ({CFG['min_odds']} to +{CFG['max_odds']})."
    if b["n"] < CFG["min_games"]:
        return "THIN FILE", f"Only {b['n']} games on file. The desk wants {CFG['min_games']}."
    if b["lg"] == "NBA" and (b.get("mn") or 0) < CFG["nba_min_minutes"]:
        return "MINUTES", f"Projected for {b.get('mn') or 0:.0f} minutes. The desk wants {CFG['nba_min_minutes']:.0f}."
    if b["edge"] < CFG["min_edge"]:
        return "THIN EDGE", f"Edge {b['edge'] * 100:+.1f} points. The bar is {CFG['min_edge'] * 100:.0f}."
    if b["adj"] < CFG["min_adj_ev"]:
        return "HAIRCUT", "The edge clears, but after the confidence haircut the expected value falls short."
    return "CAP", "It cleared every test. The desk already had this player, two bets in this game, or three for the day."


def cmd_explain(date, lg, sfx=""):
    fp = O + f"priced/{lg}_{date}{sfx}.json"
    if not os.path.exists(fp):
        return
    D, _ = load(); h = history(); priced = json.load(open(fp))
    quotes = _quotes([O + f"lines/{lg}_{date}{sfx}.txt"])
    news = (json.load(open(NEWS)) if os.path.exists(NEWS) else {}).get(lg, {})
    row = {(x["id"], x["side"]): x for x in priced}
    mine = [b for b in h["bets"] if b["date"] == date and b["lg"] == lg and not b.get("superseded") and b.get("lane") != "confident"]
    if sfx:
        mine = [b for b in mine if b.get("run") == sfx[1:]]
    for b in mine:
        mn = b.get("mn") or (row.get((b["id"], b["side"])) or {}).get("mn")
        b["why"] = explain(b, D, quotes, news, mn)
    if sfx:
        save_history(h); print(f"{lg} {date}: evening case files written for {len(mine)} bets"); return
    took = {(b["id"], b["side"]) for b in mine}; seen, passed = set(), []
    for x in sorted(priced, key=lambda x: -x["adj"]):
        if (x["id"], x["side"]) in took or x["id"] in seen or not (x["edge"] >= .015 or x.get("edgec", 0) > CFG["hold_edge"].get(x["lg"], CFG["max_edge"])) or x["edge"] < 0:
            continue
        seen.add(x["id"]); stamp, why = pass_reason(x)
        passed.append(dict(name=x["name"], team=x["team"], opp=x["opp"], side=x["side"], line=x["line"], mkt=x["mkt"], odds=x["odds"], p=x["p"], edge=x["edge"],
                           mu=x["mu"], mm=x.get("mm"), muf=x.get("muf"), stamp=stamp, why=why))
        if len(passed) == 6:
            break
    for d in h["days"]:
        if d["date"] == date and d["lg"] == lg:
            d["passed"] = passed
            if _CEN.get(lg): d["cen"] = {k: round(v, 3) for k, v in _CEN[lg].items()}
            elif priced and "cen" not in d: d["cen"] = {m: x["cen"] for x in priced for m in [x["mkt"]] if x.get("cen")}
    save_history(h)
    print(f"{lg} {date}: case files written for {len(mine)} bets, {len(passed)} on the pass list")


def cmd_close(date, lg, label, files):
    D, _ = load(); L = D[lg]; h = history(); quotes = _quotes(files); n = 0
    for b in h["bets"]:
        if b["date"] != date or b["lg"] != lg or b["status"] != "open" or b["mkt"] == "any_td":
            continue
        books = quotes.get((norm(b["name"]), INV[lg].get(b["mkt"])), {}); imps = {}
        for bk, r in books.items():
            if r["line"] is not None and r["o"] is not None and r["u"] is not None:
                imps[bk] = implied_mean(L, lg, b["mkt"], r["line"], devig_over(r["o"], r["u"]))
        if not imps:
            continue
        over = b["side"] == "Over"
        def sidep(mean):
            ov, un, _ = probs(L, lg, b["mkt"], mean, b["line"]); return (ov if over else un) / (ov + un)
        mc = weighted_cons(imps, exclude=None); fair = sidep(mc); hr = books.get(b.get("book") or CFG["book"]) or {}
        opened = sidep(b["mm"]) if b.get("mm") else None
        b["close"] = dict(t=label, line=hr.get("line"), o=None if hr.get("o") is None else int(hr["o"]), u=None if hr.get("u") is None else int(hr["u"]),
                          nb=len(imps), mm=round(mc, 2), fair=round(fair, 4), clv=round(dec(b["odds"]) * fair - 1, 4),
                          move=None if opened is None else round(fair - opened, 4))
        n += 1
        print(f"  {b['name']} {b['side']} {b['line']} {b['mkt']} {b['odds']:+d}: closed {hr.get('line')} {hr.get('o')}/{hr.get('u')}, fair {fair:.1%}, CLV {b['close']['clv'] * 100:+.1f}%, market moved {0 if opened is None else (fair - opened) * 100:+.1f} pts")
    save_history(h); print(f"{lg} {date}: closing lines recorded for {n} bets")
    try: wide_close(date, lg, label, quotes, L, files)
    except Exception as e: print("  wide close not recorded:", e)


def wide_close(date, lg, label, quotes, L, files=()):
    f = O + f"priced/{lg}_{date}.json"
    if not os.path.exists(f):
        return
    cp = O + "closes.json"; C = json.load(open(cp)) if os.path.exists(cp) else {}; n = 0
    refq = {}
    for fl in files:
        if os.path.exists(fl):
            for r in parse(fl, ref=True):
                if r["line"] is not None and r["o"] is not None and r["u"] is not None:
                    refq[(norm(r["player"]), r["market"])] = r
    for b in json.load(open(f)):
        if b["mkt"] == "any_td":
            continue
        mk = market_ticket(b.get("mk")); mkok = mk is not None
        try: cleared = eligible(b)
        except (KeyError, TypeError): cleared = False
        if not (cleared or mkok):
            continue
        imps = {}
        for bk, r in quotes.get((norm(b["name"]), INV[lg].get(b["mkt"])), {}).items():
            if r["line"] is not None and r["o"] is not None and r["u"] is not None:
                imps[bk] = implied_mean(L, lg, b["mkt"], r["line"], devig_over(r["o"], r["u"]))
        if len(imps) < 2:
            continue
        mc = weighted_cons(imps, exclude=None)
        def fair(line):
            ov, un, _ = probs(L, lg, b["mkt"], mc, line); return (un if b["side"] == "Under" else ov) / (ov + un)
        C[b["id"] + "|" + b["side"]] = dict(date=date, t=label, nb=len(imps), clv=round(dec(b["odds"]) * fair(b["line"]) - 1, 4),
                                            mclv=round(dec(mk["odds"]) * fair(mk["line"]) - 1, 4) if mkok else None)
        rq = refq.get((norm(b["name"]), INV[lg].get(b["mkt"])))
        if rq:
            mc = implied_mean(L, lg, b["mkt"], rq["line"], devig_over(rq["o"], rq["u"]))
            C[b["id"] + "|" + b["side"]].update(pclv=round(dec(b["odds"]) * fair(b["line"]) - 1, 4),
                                                mpclv=round(dec(mk["odds"]) * fair(mk["line"]) - 1, 4) if mkok else None)
        n += 1
    old = (datetime.date.fromisoformat(date) - datetime.timedelta(days=45)).isoformat()
    C = {k: v for k, v in C.items() if v.get("date", date) >= old}
    json.dump(C, open(cp, "w")); print(f"{lg} {date}: closing number recorded for {n} shadow sides")


def actual(lg, p, mkt, tag):
    l = p["logs"]; tags = l["d"] if lg == "NBA" else l["wk"]
    if tag not in tags:
        return None
    i = len(tags) - 1 - tags[::-1].index(tag)
    if lg == "NBA":
        return sum(l[k][i] for k in COMBO.get(mkt, [mkt]))
    if mkt == "any_td":
        return 1 if (l["rtd"][i] + l["rectd"][i]) > 0 else 0
    return l[NFL_LOG[mkt]][i]


def nfl_box():
    if not _NFL_BOX:
        rows, games = {}, set()
        try:
            import pandas as pd
            cols = ["player_id", "season", "week", "game_id", "rushing_tds", "receiving_tds"] + list(NFL_RAW.values())
            d = pd.read_csv(DATA + "nfl_pw_2026.csv", usecols=cols, low_memory=False)
            games = set(d.game_id.dropna().astype(str))
            num = [c for c in cols if c not in ("player_id", "season", "week", "game_id")]
            for (pid, se, wk), r in d.groupby(["player_id", "season", "week"])[num].sum().iterrows():
                rows[(pid, f"{int(se) % 100}W{int(wk)}")] = r
            _NFL_BOX.update(ok=True, rows=rows, games=games, snaps=None, snap_games=set())
            try:
                sc = pd.read_csv(DATA + "nfl_snaps_2026.csv", usecols=["game_id", "player", "offense_snaps", "defense_snaps", "st_snaps"])
                on = sc[(sc.offense_snaps.fillna(0) + sc.defense_snaps.fillna(0) + sc.st_snaps.fillna(0)) > 0]
                _NFL_BOX.update(snaps={(g, norm(n)) for g, n in zip(on.game_id.astype(str), on.player.astype(str))},
                                snap_games=set(sc.game_id.dropna().astype(str)))
            except Exception as e:
                print("NFL snap counts not readable, a player with no stat line is treated as did not play:", e)
        except Exception as e:
            print("NFL stats file not readable, grading NFL from page logs:", e)
            _NFL_BOX.update(ok=False)
    return _NFL_BOX if _NFL_BOX["ok"] else None


def nfl_actual(box, b):
    pid, mkt, tag = b["pid"], b["mkt"], b["tag"]
    r = box["rows"].get((pid, tag))
    if r is None:
        if box["snaps"] is not None and (b["game"], norm(b["name"])) in box["snaps"]:
            return 0
        return None
    if mkt == "any_td":
        return 1 if (r["rushing_tds"] + r["receiving_tds"]) > 0 else 0
    return int(r[NFL_RAW[mkt]])


def nba_box():
    """v3.52: NBA box scores straight from nba_pb_2027.parquet, mirroring nfl_box() so a 4+ day schedule lull
    (All-Star break, NBA Cup) never drops a team from grading or mis-voids an open ticket."""
    if not _NBA_BOX:
        rows, games = {}, set()
        try:
            import pandas as pd
            cols = ["game_id", "game_date", "athlete_id", "minutes", "points", "rebounds", "assists", "three_point_field_goals_made"]
            d = pd.read_parquet(DATA + "nba_pb_2027.parquet", columns=cols)
            d = d[d.minutes.notna() & (d.minutes > 0)]
            games = set(d.game_id.dropna().astype(int).astype(str)) | set(d.game_id.dropna().astype(str))
            for r in d.itertuples():
                v = dict(pts=int(r.points or 0), reb=int(r.rebounds or 0), ast=int(r.assists or 0), fg3=int(r.three_point_field_goals_made or 0))
                for c, parts in COMBO.items():
                    v[c] = sum(v[q] for q in parts)
                gid = str(int(r.game_id)) if str(r.game_id).replace(".", "", 1).isdigit() else str(r.game_id)
                pid = pid_str(r.athlete_id)
                rows[(gid, pid)] = v
                rows[(str(r.game_date)[5:10], pid)] = v
            _NBA_BOX.update(ok=True, rows=rows, games=games)
        except Exception as e:
            print("NBA box parquet not readable, grading NBA from page logs:", e)
            _NBA_BOX.update(ok=False)
    return _NBA_BOX if _NBA_BOX["ok"] else None


def nba_actual(box, b):
    pid = pid_str(b["pid"])
    r = box["rows"].get((str(b["game"]), pid)) or box["rows"].get((b["tag"], pid))
    return None if r is None else r.get(b["mkt"])


def cmd_grade():
    D, _ = load(); h = history(); n = 0
    by = {lg: {p["id"]: p for p in D[lg]["players"]} for lg in ("NBA", "NFL")}
    for b in h["bets"]:
        back = scratched(b) and not b["scratch"].get("final")
        if b["status"] != "open" and not back:
            continue
        p = by[b["lg"]].get(b["pid"])
        box = nfl_box() if b["lg"] == "NFL" else nba_box()
        if b["lg"] == "NFL":
            v = nfl_actual(box, b) if box else (actual(b["lg"], p, b["mkt"], b["tag"]) if p else None)
        else:
            v = nba_actual(box, b) if box else (actual(b["lg"], p, b["mkt"], b["tag"]) if p else None)
        if v is None:
            thru = D[b["lg"]]["data_through"]
            if b["lg"] == "NFL" and box:
                past = (b["game"] in box["snap_games"]) if box["snaps"] is not None else (b["game"] in box["games"])
            elif b["lg"] == "NBA" and box:
                past = str(b["game"]) in box["games"]
            else:
                past = (thru > b["date"]) if b["lg"] == "NBA" else (int(re.sub(r"\D", "", thru.split("Week")[-1])) >= int(b["tag"].split("W")[1]))
                if not past and b["lg"] == "NBA" and p and thru >= b["date"]:
                    mates = sum(1 for q in D["NBA"]["players"] if q.get("team") == p.get("team") and q["id"] != p["id"] and b["tag"] in q["logs"]["d"])
                    past = mates >= 5
            if past and back:
                b["scratch"]["final"] = True
            elif past:
                b["status"] = "void"; n += 1
            continue
        if back:
            b["scratch"].update(final=True, played=True)
            if b.get("why"): b["why"]["head"] = "He played after being listed out, so the ticket stands and is graded. " + b["why"]["head"]
        b["result"] = v
        if b["mkt"] == "any_td": win = (v > 0) == (b["side"] == "Yes")
        elif v == b["line"]: win = None
        else: win = (v > b["line"]) == (b["side"] == "Over")
        b["status"] = "push" if win is None else ("won" if win else "lost"); n += 1
    save_history(h)
    print("graded", n); cmd_report(h)


def cmd_report(h=None):
    h = h or history()
    def line(bs, label):
        w = sum(b["status"] == "won" for b in bs); l = sum(b["status"] == "lost" for b in bs)
        pl = lambda b: (dec(b["odds"]) - 1) * b["units"] if b["status"] == "won" else -b["units"] if b["status"] == "lost" else 0
        u = sum(pl(b) for b in bs); usd = sum(pl(b) * b.get("unit", h.get("legacy_unit", 0.5)) for b in bs)
        if w + l:
            print(f"  {label:<14} {w}-{l}  hit {w/(w+l):.1%}  units {u:+.2f}  dollars {usd:+.2f}  avg model prob {np.mean([b['p'] for b in bs if b['status'] in ('won','lost')]):.1%}")
    done = [b for b in h["bets"] if b["status"] != "open"]
    print(f"bets {len(h['bets'])}, open {len(h['bets']) - len(done)}")
    line(done, "all"); line([b for b in done if b.get("best")], "best bets")
    line([b for b in done if b.get("lane") != "confident"], "edge lane"); line([b for b in done if b.get("lane") == "confident"], "confident")
    for lg in ("NBA", "NFL"): line([b for b in done if b["lg"] == lg], lg)
    for m in sorted({b["mkt"] for b in done}): line([b for b in done if b["mkt"] == m], m)
    for r in ("AAA", "AA", "A", "BBB"): line([b for b in done if b["rating"] == r], r)
    cl = [b["close"]["clv"] for b in h["bets"] if b.get("close") and not b.get("superseded")]
    if cl:
        print(f"  closing line value: {len(cl)} bets tracked, average {np.mean(cl) * 100:+.1f}%, beat the close on {sum(c > 0 for c in cl)}")
    try: retest_note(h)
    except Exception as e: print("  retest note not readable:", e)
    try: calib_report()
    except Exception as e: print("  calibration not readable:", e)
    try: shadow_report()
    except Exception as e: print("  shadow book not readable:", e)


def calib_report():
    if not os.path.exists(O + "audit.json"):
        return
    A = json.load(open(O + "audit.json"))
    R = [(k, r) for k, r in A.items() if r.get("win") in (0, 1) and r.get("mkt") != "any_td" and r.get("p") is not None]
    if not R:
        return
    def block(rows, label):
        p = np.array([r["p"] for _, r in rows]); w = np.array([r["win"] for _, r in rows]); bk = []
        for k, r in rows:
            o = A.get(k.rsplit("|", 1)[0] + "|" + ("Under" if r["side"] == "Over" else "Over"))
            if o and o.get("odds") is not None and o.get("line") == r.get("line"):
                a, b = 1 / dec(r["odds"]), 1 / dec(o["odds"]); bk.append(((a / (a + b)), r["win"], r["p"]))
        s = f"  {label}: {len(rows)} sides, Brier {np.mean((p - w) ** 2):.4f}"
        if bk:
            q = np.array(bk); s += f" (desk {np.mean((q[:, 2] - q[:, 1]) ** 2):.4f} against the books' {np.mean((q[:, 0] - q[:, 1]) ** 2):.4f} on the {len(bk)} with both prices)"
        gap = 0.0; out = []
        for lo, hi in ((0, .35), (.35, .42), (.42, .46), (.46, .5), (.5, .54), (.54, .58), (.58, .65), (.65, 1.01)):
            m = (p >= lo) & (p < hi)
            if m.sum():
                gap += m.sum() * abs(w[m].mean() - p[m].mean())
                out.append(f"    said {p[m].mean():.0%} ({m.sum()}): happened {w[m].mean():.0%}, {'+' if w[m].mean() >= p[m].mean() else ''}{(w[m].mean() - p[m].mean()) * 100:.1f}")
        print(s + f", average gap {gap / len(rows) * 100:.1f} points"); print("\n".join(out))
    print("calibration (every graded side; said -> happened):")
    block(R, "all days")
    last = max(r["date"] for _, r in R); cut = (datetime.date.fromisoformat(last) - datetime.timedelta(days=13)).isoformat()
    if min(r["date"] for _, r in R) < cut: block([x for x in R if x[1]["date"] >= cut], "last 14 days")
    cl = [x for x in R if CFG["min_edge"] <= x[1].get("edge", 0) <= CFG["max_edge"]]
    if cl: block(cl, f"edge inside the playable window ({CFG['min_edge'] * 100:.0f} to {CFG['max_edge'] * 100:.0f} points)")


def cmd_audit():
    """Grade EVERY midday side priced against a book line.
    v3.52: restricts glob to midday files only (no _pm/_late leakage) and reads NBA parquet directly."""
    import glob
    D, _ = load(); by = {lg: {p["id"]: p for p in D[lg]["players"]} for lg in ("NBA", "NFL")}
    ap = O + "audit.json"; A = json.load(open(ap)) if os.path.exists(ap) else {}
    for f in sorted(glob.glob(O + "priced/*.json")):
        if not re.search(r"/(NBA|NFL)_\d{4}-\d\d-\d\d\.json$", f):
            continue
        for b in json.load(open(f)):
            k = b["id"] + "|" + b["side"]
            if k in A:
                continue
            p = by[b["lg"]].get(b["pid"])
            if b["lg"] == "NFL":
                box = nfl_box(); v = nfl_actual(box, b) if box else (actual(b["lg"], p, b["mkt"], b["tag"]) if p else None)
            else:
                box = nba_box(); v = nba_actual(box, b) if box else (actual(b["lg"], p, b["mkt"], b["tag"]) if p else None)
            if v is None:
                continue
            if b["mkt"] == "any_td": win = (v > 0) == (b["side"] == "Yes")
            elif v == b["line"]: continue
            else: win = (v > b["line"]) == (b["side"] == "Over")
            A[k] = dict(lg=b["lg"], mkt=b["mkt"], side=b["side"], date=b["date"], odds=b["odds"], p=b["p"], edge=b["edge"], mu=b["mu"], line=b["line"], result=v, win=int(win),
                        **{f: b[f] for f in ("ver", "nb", "mm", "muf", "cen", "p0", "edge0", "edgec") if b.get(f) is not None})
    json.dump(A, open(ap, "w"))
    rows = list(A.values()); print("audited sides:", len(rows))
    def tab(title, keyf):
        print(title)
        for k in sorted({keyf(r) for r in rows}, key=str):
            z = [r for r in rows if keyf(r) == k]
            u = sum((dec(r["odds"]) - 1) if r["win"] else -1 for r in z)
            print(f"  {str(k):<16} n {len(z):<5} hit {np.mean([r['win'] for r in z]):.1%}  model said {np.mean([r['p'] for r in z]):.1%}  break-even {np.mean([1/dec(r['odds']) for r in z]):.1%}  roi {u/len(z):+.1%}")
    if rows:
        eb = lambda r: "edge <0" if r["edge"] < 0 else "edge 0-3" if r["edge"] < .03 else "edge 3-6" if r["edge"] < .06 else "edge 6-12" if r["edge"] < .12 else "edge 12+"
        tab("by model edge (the key table: hit rate should climb with edge)", eb)
        tab("by market", lambda r: r["lg"] + " " + r["mkt"]); tab("by side", lambda r: r["side"])
        tab("by version (1.3 on: probabilities anchored to the market)", lambda r: "v" + str(r.get("ver", "1.2")))
        v13 = [r for r in rows if r.get("ver") and r.get("nb", 0) >= CFG["min_books"]]
        if v13:
            rows = v13; print("v1.3+ sides with a market check only:"); tab("  by edge", eb); tab("  by side", lambda r: r["side"])
            rows = list(A.values())
        ov = [r for r in rows if r["side"] in ("Over", "Yes") and r["mkt"] != "any_td"]
        for m in sorted({r["lg"] + " " + r["mkt"] for r in ov}):
            z = [r for r in ov if r["lg"] + " " + r["mkt"] == m]
            print(f"  {m:<14} mean(proj - line) {np.mean([r['mu'] - r['line'] for r in z]):+.2f}   mean(actual - line) {np.mean([r['result'] - r['line'] for r in z]):+.2f}   MAE proj {np.mean([abs(r['result'] - r['mu']) for r in z]):.2f}  MAE line {np.mean([abs(r['result'] - r['line']) for r in z]):.2f}")


def cmd_shadow():
    import glob
    sp = O + "shadow.json"; S = json.load(open(sp)) if os.path.exists(sp) else {"rows": {}}
    R = S.setdefault("rows", {})
    HR = S.setdefault("hr_only", {})     # v3.52: Florida-executable Hard Rock-only shadow lane
    A = json.load(open(O + "audit.json")) if os.path.exists(O + "audit.json") else {}
    h = history()
    took = {b["id"] + "|" + b["side"] for b in h["bets"] if not b.get("superseded") and b.get("lane") != "confident"}
    for f in sorted(glob.glob(O + "priced/*.json")):
        if not re.search(r"/(NBA|NFL)_\d{4}-\d\d-\d\d\.json$", f):
            continue
        try:
            priced = json.load(open(f))
            pool = sorted([b for b in priced if eligible(b)], key=lambda b: -b["adj"])
        except (KeyError, TypeError):
            continue
        rank = {b["id"] + "|" + b["side"]: i + 1 for i, b in enumerate(pool)}
        for b in priced:
            k = b["id"] + "|" + b["side"]
            if not b.get("ver"):
                continue
            # Hard Rock-only shadow lane
            hr = b.get("hr")
            if hr and hr.get("elig") and k not in HR:
                HR[k] = dict(date=b["date"], lg=b["lg"], name=b["name"], team=b.get("team"), mkt=b["mkt"], side=b["side"],
                             line=hr["line"], odds=hr["odds"], p=hr["p"], edge=hr["edge"], adj=hr["adj"])
            if k in R:
                continue
            if k in rank:
                grp, stamp = ("picked" if k in took else "passed"), "CAP"
            elif CFG["min_edge"] <= b["edge"] <= CFG["max_edge"]:
                grp, stamp = "near", pass_reason(b)[0]
            else:
                continue
            R[k] = dict(date=b["date"], lg=b["lg"], name=b["name"], team=b.get("team"), mkt=b["mkt"], side=b["side"], line=b["line"], odds=b["odds"],
                        book=b.get("book"), p=b["p"], edge=b["edge"], adj=b.get("adj"), grp=grp, stamp=stamp, rank=rank.get(k),
                        home=(int(b["team"] == b["gl"].split(" @ ")[-1]) if b.get("gl") and b.get("team") else None),
                        ver=open(os.path.dirname(os.path.abspath(__file__)) + "/VERSION").read().strip() if os.path.exists(os.path.dirname(os.path.abspath(__file__)) + "/VERSION") else VER)
    n = 0
    for k, r in R.items():
        if r.get("win") is None and k in A:
            r.update(win=A[k]["win"], result=A[k]["result"]); n += 1
    for k, r in HR.items():
        if r.get("win") is None and k in A and A[k].get("result") is not None:
            v = A[k]["result"]
            if v == r["line"]: r.update(win=-1, result=v)
            else: r.update(win=int((v > r["line"]) == (r["side"] != "Under")), result=v)
    # Grade shadow leans if present
    for k, r in S.setdefault("leans", {}).items():
        if r.get("win") is None and k in A and A[k].get("result") is not None:
            v = A[k]["result"]
            if v == r["line"]: r.update(win=-1, result=v)
            else: r.update(win=int((v > r["line"]) == (r["side"] != "Under")), result=v)

    M = S.setdefault("market", {}); D = None
    for f in sorted(glob.glob(O + "priced/*.json")):
        if not re.search(r"/(NBA|NFL)_\d{4}-\d\d-\d\d\.json$", f):
            continue
        try: priced = json.load(open(f))
        except ValueError: continue
        for b in priced:
            k = b.get("id", "") + "|" + b.get("side", "")
            if k in M or not b.get("ver"):
                continue
            mk = b.get("mk")
            if mk is None:
                if D is None: D = load()[0]
                try: mk = market_est(D[b["lg"]], b)
                except (KeyError, TypeError): mk = None
            mk = market_ticket(mk)
            if not mk:
                continue
            try: desk = "picked" if k in took else "cleared" if eligible(b) else "no"
            except (KeyError, TypeError): desk = "no"
            M[k] = dict(date=b["date"], lg=b["lg"], name=b["name"], team=b.get("team"), mkt=b["mkt"], side=b["side"], line=mk["line"], odds=mk["odds"],
                        book=mk["book"], p=mk["p"], edge=mk["edge"], edge_pw=mk.get("edge_pw"), n=mk["n"], est=mk.get("est", 0), desk=desk, model_edge=b.get("edge"),
                        q=int("questionable" in b.get("flags", [])))
    C = json.load(open(O + "closes.json")) if os.path.exists(O + "closes.json") else {}
    for k, c in C.items():
        if k in R and c.get("clv") is not None: R[k]["clv"] = c["clv"]
        if k in M and c.get("mclv") is not None: M[k]["clv"] = c["mclv"]
        if k in R and c.get("pclv") is not None: R[k]["pclv"] = c["pclv"]
        if k in M and c.get("mpclv") is not None: M[k]["pclv"] = c["mpclv"]
    for k, r in M.items():
        if r.get("win") is None and k in A and A[k].get("result") is not None:
            v = A[k]["result"]
            if v == r["line"]: r.update(win=-1, result=v)
            else: r.update(win=int((v > r["line"]) == (r["side"] != "Under")), result=v)
    for k, r in R.items():
        if "kind" not in r and r["grp"] != "near":
            m = M.get(k)
            r["kind"] = "price" if (m and m["book"] == r.get("book") and m["line"] == r["line"]) else "model"
    S["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    json.dump(S, open(sp, "w"))
    print(f"shadow book: {len(R)} sides on file, {n} newly graded")
    shadow_report(S)


def clv_note(z):
    c = [r["clv"] for r in z if r.get("clv") is not None]
    s = f"  vs close {np.mean(c):+.1%}, beat it {sum(v > 0 for v in c)} of {len(c)}" if c else ""
    pc = [r["pclv"] for r in z if r.get("pclv") is not None]
    return s + (f"  vs Pinnacle {np.mean(pc):+.1%}, beat it {sum(v > 0 for v in pc)} of {len(pc)}" if pc else "")


def shadow_report(S=None):
    if S is None:
        if not os.path.exists(O + "shadow.json"):
            return
        S = json.load(open(O + "shadow.json"))
    rows = [r for r in S.get("rows", {}).values() if r.get("win") is not None]
    if not rows:
        return
    def line(z, label, said="model said"):
        if not z:
            return
        u = sum((dec(r["odds"]) - 1) if r["win"] else -1 for r in z); w = sum(r["win"] for r in z)
        print(f"  {label:<26} {w}-{len(z) - w}  hit {w / len(z):.1%}  {said} {np.mean([r['p'] for r in z]):.1%}  break-even {np.mean([1 / dec(r['odds']) for r in z]):.1%}  flat units {u:+.2f}  per bet {u / len(z):+.1%}" + clv_note(z))
    last = max(r["date"] for r in rows)
    print(f"shadow book (flat 1 unit a side, {min(r['date'] for r in rows)[5:]} to {last[5:]}):")
    line([r for r in rows if r["grp"] == "picked"], "picked")
    line([r for r in rows if r["grp"] == "passed"], "cleared, not picked")
    line([r for r in rows if r["grp"] == "picked" and r["date"] == last], f"picked, {last[5:]}")
    line([r for r in rows if r["grp"] == "passed" and r["date"] == last], f"cleared, not picked, {last[5:]}")
    hr_g = [r for r in S.get("hr_only", {}).values() if r.get("win") in (0, 1)]
    if hr_g:
        line(hr_g, "Hard Rock-only cleared")
    ln_g = [r for r in S.get("leans", {}).values() if r.get("win") in (0, 1)]
    if ln_g:
        line(ln_g, "shadow leans (1-3% edge)")
    for m in sorted({r["lg"] + " " + r["mkt"] for r in rows if r["grp"] != "near"}):
        line([r for r in rows if r["grp"] != "near" and r["lg"] + " " + r["mkt"] == m], "all cleared: " + m)
    for lo, hi in ((.03, .04), (.04, .06), (.06, .13)):
        line([r for r in rows if r["grp"] != "near" and lo <= r["edge"] < hi], f"all cleared: edge {lo * 100:.0f} to {min(hi, .12) * 100:.0f}")
    for st in sorted({r["stamp"] for r in rows if r["grp"] == "near"}):
        line([r for r in rows if r["grp"] == "near" and r["stamp"] == st], "near miss: " + st.lower())
    for kd, lab in (("price", "cleared: price plays"), ("model", "cleared: model plays")):
        line([r for r in rows if r["grp"] != "near" and r.get("kind") == kd], lab)
    cl = [r for r in rows if r["grp"] != "near"]
    for sd in ("Over", "Under"): line([r for r in cl if r["side"] == sd], "all cleared: " + sd.lower() + "s")
    line([r for r in cl if r.get("home") == 1], "all cleared: at home"); line([r for r in cl if r.get("home") == 0], "all cleared: on the road")
    tm = {}
    for r in cl: tm.setdefault(r.get("team") or "?", []).append(r)
    tu = sorted(((sum((dec(r["odds"]) - 1) if r["win"] else -1 for r in z), t) for t, z in tm.items() if len(z) >= 5))
    for u, t in tu[:3] + [x for x in tu[-3:] if x not in tu[:3]]: line(tm[t], "all cleared: team " + t)
    line([r for r in cl if r.get("clv") is not None and r["clv"] > 0], "cleared: beat the close")
    line([r for r in cl if r.get("clv") is not None and r["clv"] <= 0], "cleared: lost to the close")
    market_report(S, lambda z, label: line(z, label, "books said"))


def market_report(S, line):
    mk = [r for r in S.get("market", {}).values() if r.get("win") in (0, 1)]
    if not mk:
        return
    now, est = [r for r in mk if not r["est"]], [r for r in mk if r["est"]]
    print(f"market lane (books only, no model; {len(now)} sides priced the v3.45 way, {len(est)} rebuilt from older files):")
    for zall, tag in ((now, ""), (est, " (older, rebuilt)")):
        z = [r for r in zall if r["edge"] >= CFG["mk_min_edge"]]
        pw = [r for r in zall if (r.get("edge_pw") or -1) >= CFG["mk_min_edge"]]
        if pw:
            line(z, "de-vig: plain split files" + tag); line(pw, "de-vig: power method files" + tag)
            line([r for r in z if (r.get("edge_pw") or -1) < CFG["mk_min_edge"]], "  only the plain split" + tag)
            line([r for r in pw if r["edge"] < CFG["mk_min_edge"]], "  only the power method" + tag)
        if not z:
            continue
        line(z, "all filed" + tag)
        for lo, hi in ((.01, .02), (.02, .03), (.03, 1)):
            line([r for r in z if lo <= r["edge"] < hi], f"  beat fair by {lo * 100:.0f}{' to ' + str(int(hi * 100)) if hi < 1 else ' and up'}{tag}")
        day = {}
        for r in sorted(z, key=lambda r: -r["edge"]):
            day.setdefault(r["date"], []).append(r)
        line([r for v in day.values() for r in v[:CFG["max_picks"]]], f"  top {CFG['max_picks']} a day{tag}")
        line([r for r in z if not r["q"]], "  not questionable" + tag)
        line([r for r in z if r["desk"] != "no"], "  the model cleared it too" + tag)
        line([r for r in z if r["desk"] == "no"], "  the model passed" + tag)
        line([r for r in z if r.get("clv") is not None and r["clv"] > 0], "  beat the close" + tag)
        line([r for r in z if r.get("clv") is not None and r["clv"] <= 0], "  lost to the close" + tag)
        for m in sorted({r["lg"] + " " + r["mkt"] for r in z}):
            line([r for r in z if r["lg"] + " " + r["mkt"] == m], "  " + m + tag)


ALTK = {"NBA": {"player_points_alternate": "pts", "player_rebounds_alternate": "reb", "player_assists_alternate": "ast", "player_threes_alternate": "fg3",
                "player_points_rebounds_assists_alternate": "pra"},
        "NFL": {"player_pass_yds_alternate": "pass_yds", "player_rush_yds_alternate": "rush_yds", "player_reception_yds_alternate": "rec_yds",
                "player_receptions_alternate": "rec"}}


def cmd_confident(date, lg, files):
    """v3.52: when >= conf_books other books quote the exact same alternate rung with both prices, devig that rung
    directly via power_fair() instead of extrapolating into the 72%-93% tail from the main-line NB mean."""
    h = history()
    if any(b["date"] == date and b["lg"] == lg and b.get("lane") == "confident" for b in h["bets"]):
        print("confident lane already ran for", lg, date); return
    fp = O + f"priced/{lg}_{date}.json"
    if not os.path.exists(fp):
        print("confident: no priced file for", lg, date); return
    D, _ = load(); L = D[lg]
    base = {}
    for x in json.load(open(fp)):
        base.setdefault((x["pid"], x["mkt"]), x)
    taken = {b["pid"] for b in h["bets"] if b["date"] == date and b["lg"] == lg and not b.get("superseded")}
    byname = {}
    for (pid, mkt), x in base.items():
        byname.setdefault(norm(x["name"]), set()).add(pid)
    all_rows = []
    for f in files:
        all_rows += parse(f)
    # Build direct two-sided rung map across ALL books (excluding ref_books already dropped by parse())
    rung_fair = {}
    for r in all_rows:
        mkt = ALTK[lg].get(r["market"]) or MK[lg].get(r["market"])
        if not mkt or mkt == "any_td" or r["line"] is None or r["o"] is None or r["u"] is None:
            continue
        if not (CFG["sane"][0] <= 1 / dec(r["o"]) + 1 / dec(r["u"]) <= CFG["sane"][1]):
            continue
        rung_fair.setdefault((norm(r["player"]), mkt, r["line"]), {})[r["book"]] = power_fair(r["o"], r["u"])

    rows = [r for r in all_rows if r["book"] in CFG["bet_books"] and (r["u"] is None or r["o"] is None or CFG["sane"][0] <= 1 / dec(r["o"]) + 1 / dec(r["u"]) <= CFG["sane"][1])]
    cands = []
    for r in rows:
        alt = r["market"] in ALTK[lg]
        mkt = ALTK[lg].get(r["market"]) or MK[lg].get(r["market"])
        if not mkt or mkt == "any_td" or r["line"] is None:
            continue
        ids = byname.get(norm(r["player"]), set())
        x = next((base[(i, mkt)] for i in ids if (i, mkt) in base), None)
        if x is None or x.get("mm") is None:
            continue
        oth_rung = [p for bk, p in rung_fair.get((norm(r["player"]), mkt, r["line"]), {}).items() if bk != r["book"]]
        for side, odds in (("Over", r["o"]), ("Under", r["u"])):
            if odds is None or not (CFG["conf_min_odds"] <= odds <= CFG["conf_max_odds"]):
                continue
            def chance(mean):
                ov, un, _ = probs(L, lg, mkt, mean, r["line"])
                return (ov if side == "Over" else un) / (ov + un)
            cut = (1 - CFG["conf_exit"]) if side == "Over" else 1.0
            cap = lambda q: min(q, CFG["conf_cap"])
            direct_alt = alt and len(oth_rung) >= CFG["conf_books"]
            if direct_alt:
                raw_fair = float(np.median(oth_rung)) if side == "Over" else float(1.0 - np.median(oth_rung))
                fair = cap(raw_fair)     # direct market rung already prices injury/early-exit risk
            else:
                fair = cap(chance(x["mm"]) * cut)
            model, desk = cap(chance(x["mu"] * x.get("cen", 1.0)) * cut), cap(chance(x.get("muf", x["mm"])) * cut)
            be = 1 / dec(odds)
            why_not = []
            if fair < CFG["conf_fair"]: why_not.append("books not sure enough")
            if model < CFG["conf_model"]: why_not.append("model does not agree")
            if fair - be < CFG["conf_edge"]: why_not.append("price worse than fair")
            if x.get("nb", 0) < CFG["conf_books"]: why_not.append("too few books")
            if x["n"] < CFG["min_games"]: why_not.append("thin history")
            if lg == "NBA" and (x.get("mn") or 0) < CFG["conf_nba_min"]: why_not.append("minutes too low")
            if any(f in x["flags"] for f in ("missed last game", "questionable", "model far from market, check news", "minutes swing")): why_not.append("lineup or role question")
            if x["pid"] in taken: why_not.append("already bet today")
            cands.append(dict(x=x, r=r, alt=alt, direct_alt=direct_alt, mkt=mkt, side=side, odds=int(odds), fair=fair, model=model, desk=desk, be=be, edge=fair - be, ok=not why_not, why_not=why_not))
    os.makedirs(O + "conf", exist_ok=True)
    json.dump([dict(name=c["x"]["name"], pid=c["x"]["pid"], game=c["x"]["game"], mkt=c["mkt"], alt=c["alt"], direct_alt=c["direct_alt"], side=c["side"], line=c["r"]["line"], odds=c["odds"],
                    fair=round(c["fair"], 4), model=round(c["model"], 4), desk=round(c["desk"], 4), edge=round(c["edge"], 4), ok=c["ok"], why_not=c["why_not"], tag=c["x"]["tag"])
               for c in cands], open(O + f"conf/{lg}_{date}.json", "w"))
    pool = sorted([c for c in cands if c["ok"]], key=lambda c: (-c["edge"], -c["fair"]))
    picks, games, players = [], set(), set()
    for c in pool:
        if c["x"]["game"] in games or c["x"]["pid"] in players:
            continue
        games.add(c["x"]["game"]); players.add(c["x"]["pid"]); picks.append(c)
        if len(picks) == CFG["conf_max"]:
            break
    Pl = {p["id"]: p for p in L["players"]}
    for c in picks:
        x, r = c["x"], c["r"]
        v, tags, opps, _ = _logs(lg, Pl[x["pid"]], c["mkt"]) if x["pid"] in Pl else ([], [], [], None)
        v, tags, opps = v[-10:], tags[-10:], opps[-10:]
        hit = sum((y > r["line"]) if c["side"] == "Over" else (y < r["line"]) for y in v)
        unit = UNIT.get(c["mkt"], c["mkt"]); pc = lambda q: f"{q * 100:.1f}%"
        b = dict(id=f'{date}|{lg}|{x["pid"]}|{c["mkt"]}|{"alt" if c["alt"] else "main"}{r["line"]}', date=date, lg=lg, game=x["game"], gl=x["gl"], pid=x["pid"], name=x["name"],
                 team=x["team"], opp=x["opp"], mkt=c["mkt"], side=c["side"], line=r["line"], odds=c["odds"], book=r["book"], mu=x["mu"], p=round(c["fair"], 4),
                 edge=round(c["edge"], 4), ev=round(c["fair"] * (dec(c["odds"]) - 1) - (1 - c["fair"]), 4), rating="CONF", flags=[], tag=x["tag"], ver=VER, nb=x.get("nb"),
                 muf=x.get("muf"), mm=x.get("mm"), cen=x.get("cen"), p0=round(c["model"], 4), pd=round(c["desk"], 4), lane="confident", alt=c["alt"],
                 direct_alt=c["direct_alt"], best=False, status="open", result=None, mn=x.get("mn"))
        if not put_stake(h, b):
            print("  day is full at", CFG["day_units"], "units:", b["name"]); continue
        src_note = (f'Other books quoting this exact alternate rung power-devig to {pc(c["fair"])}.' if c["direct_alt"]
                    else f'{x.get("nb")} other books on the main line imply {x["mm"]:.1f} {unit}. On that number the {c["side"].lower()} {r["line"]} lands {pc(c["fair"])} of the time{", after 2 points off for an early exit" if c["side"] == "Over" else ""}.')
        b["why"] = dict(kind="confident",
            head=f'A confident play: the books rate {c["side"].lower()} {r["line"]} {unit} a {pc(c["fair"])} shot, the model agrees, and {BOOKN.get(r["book"], r["book"])} charges no more than that.',
            pts=[["Price", f'{BOOKN.get(r["book"], r["book"])} has the {c["side"]} {r["line"]}{" (alternate line)" if c["alt"] else ""} at {c["odds"]:+d}, which needs {pc(c["be"])} to break even: you risk 1 to win {dec(c["odds"]) - 1:.2f}.'],
                 ["Books", src_note],
                 ["Model", f'The model on its own projects {x["mu"] * x.get("cen", 1.0):.1f} after centring, which makes it {pc(c["model"])}. It agrees.'],
                 ["Form", f'Last {len(v)}: {", ".join(str(int(y)) for y in v)}. {"Cleared" if c["side"] == "Over" else "Stayed under"} {r["line"]} in {hit} of {len(v)}.' if v else "No recent games on file."],
                 ["Math", f'Fair chance {pc(c["fair"])} against {pc(c["be"])} needed: {c["edge"] * 100:+.1f} points, worth {b["ev"] * 100:+.1f} cents a dollar on the books\' own numbers.']],
            risks=["A heavy price: one loss costs more than one win pays, so the record has to stay high to break even.",
                   "Confident is not certain. An early exit, foul trouble or a blowout sinks a play like this.",
                   "The chance comes from the other books. If they are all wrong the same way, so is this."],
            l10=dict(v=[int(y) for y in v], t=list(tags), o=list(opps), hit=hit, n=len(v)) if v else None)
        h["bets"].append(b)
        print(f'  confident: {b["name"]} {b["side"]} {b["line"]} {b["mkt"]}{" alt" if c["alt"] else ""}{" (direct)" if c["direct_alt"] else ""} {b["odds"]:+d}  books {c["fair"]:.1%}  model {c["model"]:.1%}  needs {c["be"]:.1%}  {b["units"]}u ${b["usd"]:.2f}')
    day = next((d for d in h["days"] if d["date"] == date and d["lg"] == lg), None)
    if day is None:
        day = dict(date=date, lg=lg, sides_priced=0, cleared_bar=0, picks=0); h["days"].append(day)
    day["conf"] = dict(quotes=len(cands), cleared=len(pool), picks=len(picks), alt=sum(c["alt"] for c in cands))
    save_history(h)
    print(f"{lg} {date} confident lane: {len(cands)} quotes in the band ({sum(c['alt'] for c in cands)} alternate), {len(pool)} cleared, {len(picks)} logged")


def cmd_fill(date):
    """v3.52: when CFG['fill_live'] is False (default), leans (1%-3% edge) are recorded into shadow.json['leans']
    instead of live history.json so thin edges don't dilute the desk record before 200+ graded sides prove +EV."""
    h = history()
    today = [b for b in h["bets"] if b["date"] == date and not b.get("superseded")]
    need = CFG["min_daily"] - len(today)
    if need <= 0:
        print(f"fill: {len(today)} bets already on {date}"); return
    pool = []
    for lg in ("NBA", "NFL"):
        fp = O + f"priced/{lg}_{date}.json"
        if os.path.exists(fp):
            pool += json.load(open(fp))
    def ok(b):
        if not (CFG["min_odds"] <= b["odds"] <= CFG["max_odds"]) or b["n"] < CFG["min_games"]: return False
        if b["lg"] == "NBA" and (b["mn"] or 0) < CFG["nba_min_minutes"]: return False
        if any(f in b["flags"] for f in ("missed last game", "questionable")): return False
        if b.get("nb", 0) < CFG["min_books"] or b.get("edgec", 0) > CFG["hold_edge"].get(b["lg"], CFG["max_edge"]): return False
        if b["mkt"] not in CFG["pick_markets"].get(b["lg"], []): return False
        return CFG["lean_edge"] <= b["edge"] <= CFG["max_edge"] and b["adj"] > 0
    taken_p = {b["pid"] for b in today}; taken_g = {}
    for b in today: taken_g[b["game"]] = taken_g.get(b["game"], 0) + 1
    cands = []
    for b in sorted([x for x in pool if ok(x)], key=lambda x: -x["adj"]):
        if b["pid"] in taken_p or taken_g.get(b["game"], 0) >= CFG["max_per_game"]:
            continue
        cands.append(b); taken_p.add(b["pid"]); taken_g[b["game"]] = taken_g.get(b["game"], 0) + 1
        if len(cands) == need:
            break
    if not CFG.get("fill_live", False):
        sp = O + "shadow.json"; S = json.load(open(sp)) if os.path.exists(sp) else {"rows": {}}
        L = S.setdefault("leans", {})
        for b in cands:
            k = b["id"] + "|" + b["side"]
            if k not in L:
                L[k] = dict(date=b["date"], lg=b["lg"], name=b["name"], team=b.get("team"), mkt=b["mkt"], side=b["side"],
                            line=b["line"], odds=b["odds"], book=b.get("book"), p=b["p"], edge=b["edge"], adj=b["adj"])
        json.dump(S, open(sp, "w"))
        print(f"fill {date}: fill_live=False; logged {len(cands)} leans to shadow.json instead of live history")
        return
    added = []
    for b in cands:
        b = dict(b); b.update(best=False, status="open", result=None, lane="edge", lean=True)
        for k in ("be", "conf", "adj", "n"):
            b.pop(k, None)
        if not put_stake(h, b):
            break
        h["bets"].append(b); added.append(b)
        print(f'  lean: {b["name"]} {b["side"]} {b["line"]} {b["mkt"]} {b["odds"]:+d}  desk {b["p"]:.1%}  edge {b["edge"]*100:+.1f}  {b["units"]}u ${b["usd"]:.2f}')
    save_history(h)
    for lg in {b["lg"] for b in added}:
        cmd_explain(date, lg)
    if added:
        h = history()
        for b in h["bets"]:
            if b.get("lean") and b["date"] == date and b.get("why") and not b["why"].get("lean"):
                b["why"]["lean"] = True
                b["why"]["head"] = "A lean at a quarter unit, logged so the day has a bet. " + b["why"]["head"]
                b["why"]["risks"] = ["Smaller edge than a full play: the desk sized it down for that reason."] + b["why"]["risks"]
        save_history(h)
    print(f"fill {date}: needed {need}, added {len(added)} leans")


def cmd_gpicks(date, mode="grade"):
    gp = O + "gpicks.json"; P = json.load(open(gp)) if os.path.exists(gp) else []
    have = {(x["lg"], x["id"]) for x in P}
    G = json.load(open(O + "games.json")) if os.path.exists(O + "games.json") else {}
    if mode == "log":
        end = (datetime.date.fromisoformat(date) + datetime.timedelta(days=7)).isoformat()
        for lg in ("NBA", "NFL"):
            for g in (G.get(lg) or {}).get("games", []):
                if (lg, g["id"]) in have or g.get("spread") is None: continue
                if (lg == "NBA" and g["day"] != date) or (lg == "NFL" and not (date <= g["day"] < end)): continue
                P.append(dict(lg=lg, id=g["id"], date=date, day=g["day"], away=g["away"], home=g["home"], winner=g["winner"], p_win=g["p_win"], pm=g["pm"],
                              spread=g["spread"], ats=g["ats"], gap=g["gap"], tier=g.get("tier"), p_mkt=g.get("p_mkt"), status="open",
                              pt=g.get("pt"), total=g.get("total"), ou=g.get("ou"), tgap=g.get("tgap"),
                              ml_px=(g.get("ml") or {}).get("px"), ml_bk=(g.get("ml") or {}).get("bk"), s_px=(g.get("sbest") or {}).get("px"),
                              open=(g.get("mv") or {}).get("open"), nf=(g.get("nf") or {}).get("side"), wind=(g.get("venue") or {}).get("wind"),
                              itilt=(g.get("inj") or {}).get("tilt"), idm=(g.get("inj") or {}).get("dm")))
                have.add((lg, g["id"]))
    res = {}
    try:
        import pandas as pd
        s = pd.read_csv(D + "nfl_games.csv", low_memory=False); s = s[s.result.notna()]
        res.update({("NFL", r.game_id): (float(r.result), float(r.home_score + r.away_score)) for r in s.itertuples()})
        b = pd.read_parquet(D + "nba_pb_2027.parquet", columns=["game_id", "home_away", "team_score", "opponent_team_score"]).drop_duplicates(["game_id", "home_away"])
        b = b[b.home_away == "home"]
        res.update({("NBA", str(r.game_id)): (float(r.team_score - r.opponent_team_score), float(r.team_score + r.opponent_team_score)) for r in b.itertuples() if not pd.isna(r.team_score)})
    except Exception as e:
        print("gpicks: results not read:", e)
    n = 0
    for x in P:
        if x["status"] != "open" or (x["lg"], x["id"]) not in res: continue
        m, tot = res[(x["lg"], x["id"])]; x["margin"] = m; x["tot"] = tot
        x["su"] = None if m == 0 else int((m > 0) == (x["winner"] == x["home"]))
        c = m - x["spread"]
        x["cover"] = None if c == 0 else int((c > 0) == (x["ats"] == x["home"]))
        if x.get("ou") and x.get("total") is not None and tot != x["total"]:
            x["ou_hit"] = int((tot > x["total"]) == (x["ou"] == "Over"))
        if x.get("nf") and c != 0:
            x["nf_cover"] = int((c > 0) == (x["nf"] == x["home"]))
        if x.get("wind") is not None and x["wind"] >= 10 and x.get("total") is not None and tot != x["total"]:
            x["wind_under"] = int(tot < x["total"])
        if x.get("itilt") and c != 0:
            x["inj_cover"] = int((c > 0) == (x["itilt"] == x["home"]))
        x["status"] = "done"; n += 1
    json.dump(P, open(gp, "w"))
    done = [x for x in P if x["status"] == "done"]
    w = sum(x["su"] == 1 for x in done); l = sum(x["su"] == 0 for x in done); cw = sum(x["cover"] == 1 for x in done); cl = sum(x["cover"] == 0 for x in done)
    print(f"game picks: {len(P)} on file, {n} graded now; straight up {w}-{l}, against the spread {cw}-{cl}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "lines": cmd_lines(a[1], a[2], a[3:])
    elif a[0] == "news": cmd_news(a[1], a[2], a[3:])
    elif a[0] == "explain": cmd_explain(a[1], a[2])
    elif a[0] == "close": cmd_close(a[1], a[2], a[3], a[4:])
    elif a[0] == "pick": cmd_pick(a[1], a[2])
    elif a[0] == "evening": cmd_evening(a[1], a[2], "_late" if len(a) > 3 and a[3] == "late" else "_pm")
    elif a[0] == "scratch": cmd_scratch(a[1], a[2])
    elif a[0] == "confident": cmd_confident(a[1], a[2], a[3:])
    elif a[0] == "fill": cmd_fill(a[1])
    elif a[0] == "gpicks": cmd_gpicks(a[1], a[2] if len(a) > 2 else "grade")
    elif a[0] == "relay": sys.exit(cmd_relay(a[1]))
    elif a[0] == "today": sys.exit(cmd_today(a[1], a[2], a[3]))
    elif a[0] == "mirror": sys.exit(cmd_mirror())
    elif a[0] == "summary": cmd_summary(a[1], a[2], a[3] if len(a) > 3 else "")
    elif a[0] == "grade": cmd_grade()
    elif a[0] == "report": cmd_report()
    elif a[0] == "audit": cmd_audit()
    elif a[0] == "shadow": cmd_shadow()

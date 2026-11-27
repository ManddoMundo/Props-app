"""Polymarket for the game price lane (v4.2). TRACKING ONLY: nothing here prices a prop, stakes a bet or logs into anything.
It reads Polymarket's public data (no key, no account) and does three jobs:
  pull <date>   1. Prices. Today's NBA games and the NFL week: the moneyline and the single most balanced main total of
                   each game, written to out/poly/{LG}_{date}.txt in the relay's row format (with # tip: so B2B games
                   never collide). Tight spread cap (<= 4c) keeps thin books out of consensus.
                2. Wallets. Pre-tip taker trades on each game's moneyline kept as one running position per wallet
                   (out/sharps/m/*.json), deduplicated by trade id across descending pages and same-second Polygon blocks.
                   Even after a game starts, pre-tip trades (end = t_tip) are still backfilled so late sharp flow isn't lost.
                3. Flow. Open directional dollar exposure of tracked wallets (using net open shares N, never cumulative cash C),
                   filtering out flat scalpers and both-side arb bots (directional_ratio < 0.70).
  score         After a game is final: each directional wallet's position is scored against Pinnacle's closing no-vig line
                (falling back to Polymarket's pre-tip mid) and against the result. Tracks unit-normalized CLV, effective
                sample size N_eff, and clustered t-stat so multiple-testing noise doesn't flood the tracked cohort.
  report        The wallet board: wallets passing directional and statistical skill screens.

Every step is strictly bounded by a wall-clock deadline (CFG deadline_sec = 150s) so a stalled API can never kill the
GitHub Actions job or jeopardize the daily prop build."""
import json, math, os, sys, time, datetime, re, glob, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

O = os.environ.get("FL_OUT", "/home/claude/props/out/")
S = O + "sharps/"
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
ET = ZoneInfo("America/New_York")
CFG = dict(
    min_usd=200.0,         # a wallet's gross dollars in one game before that game counts
    min_dir_ratio=0.70,    # |net shares| / total shares traded: filters out both-side arb bots & market-making scalpers
    max_trades_game=50,    # high-frequency bot filter per game
    min_games=60,          # v4.2: scored directional games before own-board eligibility
    min_neff=40.0,         # effective sample size (prevents 1 lucky whale bet from qualifying a wallet)
    min_t_clv=2.0,         # one-sided t-stat on per-game CLV% (cuts FDR from ~85% to <2%)
    min_cohort=3,          # minimum qualified wallets before replacing leaderboard fallback
    max_spread=0.04,       # v4.2: tightened from 0.08 to keep wide thin books out of gline consensus
    pages=8,               # max pages of 1,000 trades per game per run
    board=150,             # wallets taken from Polymarket's sports leaderboard while our own board is young (paginated by 50)
    nfl_days=8,
    calls=400,
    deadline_sec=150,      # hard wall-clock budget per invocation
)
SPORT = {"NBA": "nba", "NFL": "nfl"}
CODE = {
    "NBA": {
        "hawks": "ATL", "atl": "ATL", "celtics": "BOS", "bos": "BOS", "nets": "BKN", "bkn": "BKN",
        "hornets": "CHA", "cha": "CHA", "bulls": "CHI", "chi": "CHI", "cavaliers": "CLE", "cavs": "CLE", "cle": "CLE",
        "mavericks": "DAL", "mavs": "DAL", "dal": "DAL", "nuggets": "DEN", "den": "DEN", "pistons": "DET", "det": "DET",
        "warriors": "GS", "gsw": "GS", "gs": "GS", "rockets": "HOU", "hou": "HOU", "pacers": "IND", "ind": "IND",
        "clippers": "LAC", "lac": "LAC", "lakers": "LAL", "lal": "LAL", "grizzlies": "MEM", "mem": "MEM",
        "heat": "MIA", "mia": "MIA", "bucks": "MIL", "mil": "MIL", "timberwolves": "MIN", "wolves": "MIN", "min": "MIN",
        "pelicans": "NO", "nop": "NO", "no": "NO", "knicks": "NY", "nyk": "NY", "ny": "NY",
        "thunder": "OKC", "okc": "OKC", "magic": "ORL", "orl": "ORL", "76ers": "PHI", "sixers": "PHI", "phi": "PHI",
        "suns": "PHX", "phx": "PHX", "blazers": "POR", "por": "POR", "kings": "SAC", "sac": "SAC",
        "spurs": "SA", "sas": "SA", "sa": "SA", "raptors": "TOR", "tor": "TOR",
        "jazz": "UTAH", "uta": "UTAH", "utah": "UTAH", "wizards": "WSH", "was": "WSH", "wsh": "WSH",
    },
    "NFL": {
        "cardinals": "ARI", "ari": "ARI", "falcons": "ATL", "atl": "ATL", "ravens": "BAL", "bal": "BAL",
        "bills": "BUF", "buf": "BUF", "panthers": "CAR", "car": "CAR", "bears": "CHI", "chi": "CHI",
        "bengals": "CIN", "cin": "CIN", "browns": "CLE", "cle": "CLE", "cowboys": "DAL", "dal": "DAL",
        "broncos": "DEN", "den": "DEN", "lions": "DET", "det": "DET", "packers": "GB", "gb": "GB",
        "texans": "HOU", "hou": "HOU", "colts": "IND", "ind": "IND", "jaguars": "JAX", "jags": "JAX", "jax": "JAX",
        "chiefs": "KC", "kc": "KC", "rams": "LA", "lar": "LA", "la": "LA", "chargers": "LAC", "lac": "LAC",
        "raiders": "LV", "lv": "LV", "dolphins": "MIA", "mia": "MIA", "vikings": "MIN", "min": "MIN",
        "patriots": "NE", "pats": "NE", "ne": "NE", "saints": "NO", "no": "NO",
        "giants": "NYG", "nyg": "NYG", "jets": "NYJ", "nyj": "NYJ", "eagles": "PHI", "phi": "PHI",
        "steelers": "PIT", "pit": "PIT", "seahawks": "SEA", "sea": "SEA", "49ers": "SF", "niners": "SF", "sf": "SF",
        "buccaneers": "TB", "bucs": "TB", "tb": "TB", "titans": "TEN", "ten": "TEN",
        "commanders": "WAS", "was": "WAS", "wsh": "WAS",
    },
}
ST = dict(calls=0, errors=[], notes=[], shapes={})
DEADLINE = None


def _reset_st():
    global DEADLINE
    ST.clear()
    ST.update(calls=0, errors=[], notes=[], shapes={})
    DEADLINE = time.monotonic() + CFG["deadline_sec"]


def _check_budget():
    if ST["calls"] >= CFG["calls"]:
        raise RuntimeError("call budget used")
    if DEADLINE is not None and time.monotonic() >= DEADLINE:
        raise RuntimeError("wall-clock deadline reached")


def get(url, params=None):
    _check_budget()
    ST["calls"] += 1
    q = url + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    for attempt in (0, 1):
        rem = 20.0 if DEADLINE is None else max(2.0, min(20.0, DEADLINE - time.monotonic()))
        try:
            with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "fair-line-research", "Accept": "application/json"}), timeout=rem) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt == 0:
                wait = min(float(e.headers.get("Retry-After") or 3), 8.0)
                if DEADLINE is not None and time.monotonic() + wait >= DEADLINE:
                    raise RuntimeError("wall-clock deadline reached") from None
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}") from None
        except Exception as e:
            raise RuntimeError(type(e).__name__) from None


def rows(j):
    """The list inside a response, whatever the envelope: a bare list, or the first list under data / events / items."""
    if isinstance(j, list):
        return j, None
    if isinstance(j, dict):
        pag = j.get("pagination")
        nxt = j.get("next_cursor") or (pag.get("next_cursor") if isinstance(pag, dict) else None)
        for k in ("data", "events", "markets", "items", "results"):
            if isinstance(j.get(k), list):
                return j[k], nxt
    return [], None


def arr(v):
    """outcomes, outcomePrices and clobTokenIds arrive as a list or as a list written inside a string."""
    if isinstance(v, list):
        return v
    if not isinstance(v, str):
        return []
    try:
        x = json.loads(v)
        return x if isinstance(x, list) else []
    except Exception:
        return []


def code(lg, name):
    if name is None:
        return None
    s = re.sub(r"\([^)]*\)", " ", str(name).lower())
    if lg == "NBA" and "new orleans" in s and "hornets" in s:
        return "NO"
    w = re.sub(r"[^a-z0-9 ]", "", s).split()
    if not w:
        return None
    return CODE[lg].get(w[-1]) or (CODE[lg].get(w[0]) if len(w) == 1 else None)


def american(p):
    p = min(max(float(p), 0.005), 0.995)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


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


def shape(name, row):
    if name not in ST["shapes"] and isinstance(row, dict):
        ST["shapes"][name] = sorted(row.keys())[:60]


def our_games(date):
    """Games from games.json, grouped by frozenset({A, B}) -> [game, ...] so B2B rematches never overwrite each other."""
    G = jl(O + "games.json", {})
    out = {}
    end = (datetime.date.fromisoformat(date) + datetime.timedelta(days=CFG["nfl_days"])).isoformat()
    for lg in ("NBA", "NFL"):
        for g in (G.get(lg) or {}).get("games", []):
            if (lg == "NBA" and g.get("day") == date) or (lg == "NFL" and date <= g.get("day", "") < end):
                out.setdefault(lg, {}).setdefault(frozenset((g["away"], g["home"])), []).append(g)
    return out


def _iso_ts(val):
    if not val:
        return None
    try:
        s = str(val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def tip(g, ev=None, ml=None):
    """Exact pre-tip Unix timestamp. Fail-closed: NEVER defaults missing time to 23:59 (prevents in-play CLV leaks)."""
    tm = g.get("time")
    if isinstance(tm, str) and tm.strip() and tm.strip().lower() != "nan":
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(f"{g['day']} {tm.strip()}", fmt).replace(tzinfo=ET).timestamp()
            except ValueError:
                continue
    # Fallback to Gamma's ISO start timestamp if schedule time was TBD/missing
    for src in (ml, ev):
        if not isinstance(src, dict):
            continue
        for k in ("gameStartTime", "startTime", "eventDate", "startDate"):
            ts = _iso_ts(src.get(k))
            if ts is not None:
                return ts
    return None


def events(lg):
    sp = next((s for s in rows(get(GAMMA + "/sports"))[0] if str(s.get("sport", "")).lower() == SPORT[lg]), None)
    if not sp:
        raise RuntimeError("league not in /sports")
    shape("sport", sp)
    sid = str(sp.get("series") or "").split(",")[0].strip()
    out, cur = [], None
    for _ in range(6):
        p = {"series_id": sid, "closed": "false", "active": "true", "limit": 100}
        if cur:
            p["after_cursor"] = cur
        r, cur = rows(get(GAMMA + "/events/keyset", p))
        out += r
        if not cur or not r:
            break
    if out:
        shape("event", out[0])
    return out


def _ev_day(ev, ml=None):
    for src in (ml, ev):
        if not isinstance(src, dict):
            continue
        for k in ("gameStartTime", "startTime", "eventDate", "startDate", "endDate"):
            ts = _iso_ts(src.get(k))
            if ts is not None:
                return datetime.datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d")
    return None


def match(lg, ev, ours):
    """Match a Polymarket event to our scheduled game by teams AND date (within <=1 day), avoiding future-rematch collisions."""
    for m in ev.get("markets") or []:
        if str(m.get("sportsMarketType", "")).lower() != "moneyline":
            continue
        o = arr(m.get("outcomes"))
        c = [code(lg, x) for x in o]
        if len(c) != 2 or not all(c) or c[0] == c[1]:
            continue
        cands = ours.get(frozenset(c))
        if not cands:
            continue
        evd = _ev_day(ev, m)
        if evd:
            ev_dt = datetime.date.fromisoformat(evd)
            scored = []
            for g in cands:
                dd = abs((datetime.date.fromisoformat(g["day"]) - ev_dt).days)
                if dd <= 1:
                    # Prefer exact date match, then matching away/home order if outcome order matches
                    scored.append((dd, 0 if (c[0] == g["away"] and c[1] == g["home"]) else 1, g))
            if not scored:
                continue
            scored.sort(key=lambda z: (z[0], z[1]))
            return scored[0][2], m, c
        # When event carries no date metadata, only match unambiguous single-game slates
        if len(cands) == 1:
            return cands[0], m, c
    return None, None, None


def asks(m):
    """Price to buy each of the two outcomes now: [0] at bestAsk, [1] at 1 - bestBid, plus midpoint."""
    if m.get("closed") is True or m.get("active") is False:
        return None
    try:
        b, a = float(m.get("bestBid")), float(m.get("bestAsk"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(b) and math.isfinite(a)):
        return None
    if not (0.01 < b < a < 0.99) or (a - b) > CFG["max_spread"]:
        return None
    return a, 1.0 - b, 0.5 * (a + b)


def _select_main_total(ev):
    """Pick ONLY the single most balanced active totals market (prevents alt totals from overwriting main total)."""
    best = None
    for m in ev.get("markets") or []:
        smt = str(m.get("sportsMarketType", "")).lower()
        if smt not in ("totals", "total") or m.get("line") is None:
            continue
        try:
            line = float(m["line"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(line) or line <= 0:
            continue
        o = [str(x).strip().lower() for x in arr(m.get("outcomes"))]
        if o != ["over", "under"]:
            continue
        a2 = asks(m)
        if not a2:
            continue
        try:
            liq = float(m.get("liquidityNum") or m.get("liquidity") or m.get("volumeNum") or m.get("volume") or 0.0)
        except (TypeError, ValueError):
            liq = 0.0
        key = (abs(a2[2] - 0.5), -liq)
        if best is None or key < best[0]:
            best = (key, line, a2)
    return None if best is None else (best[1], best[2])


def arr_first(t, home_first, hi=None, tokens=None):
    """True when the trade is in the home team's token. Matches outcome_index -> token_id/asset -> outcome string."""
    oi = t.get("outcome_index")
    if oi is None:
        oi = t.get("outcomeIndex")
    if oi is not None and hi is not None:
        try:
            idx = int(oi)
            if idx in (0, 1):
                return idx == hi
        except (TypeError, ValueError):
            pass
    tok = t.get("asset") or t.get("token_id") or t.get("tokenId")
    if tok and tokens and len(tokens) == 2 and hi is not None:
        tok_s = str(tok)
        if tok_s == str(tokens[hi]):
            return True
        if tok_s == str(tokens[1 - hi]):
            return False
    o = str(t.get("outcome") or "").strip().lower()
    if o == home_first[0].lower():
        return True
    if o == home_first[1].lower():
        return False
    return None


def _trade_id(t, ts, w, side, first, sz, px):
    tid = t.get("id") or t.get("transaction_hash") or t.get("transactionHash")
    if tid:
        return f"{tid}:{w}:{int(first)}:{side}:{sz}:{px}"
    return f"{ts}:{w}:{int(first)}:{side}:{sz}:{px}"


def pull_trades(key, cond, home_first, t_tip, hi=None, tokens=None):
    """Add new pre-tip trades on one moneyline to wallet positions [N, C, gross, n, tot_sz].
    Handles descending pagination, same-second Polygon blocks, dedup by trade id, and strict input validation."""
    if t_tip is None:
        return 0, None                                     # fail closed when tipoff is unknown
    f = S + "m/" + key + ".json"
    M = jl(f, dict(cond=cond, last=0, n=0, w={}, seen=[]))
    seen = set(M.get("seen") or [])
    cur, new, top = None, 0, int(M.get("last") or 0)
    prev_last = top
    exhausted = False
    for _ in range(CFG["pages"]):
        p = {"condition": cond, "limit": 1000, "end": int(t_tip)}
        if prev_last:
            p["start"] = prev_last                         # inclusive start so same-second Polygon fills are never dropped
        if cur:
            p["cursor"] = cur
        r, cur = rows(get(DATA + "/v2/trades", p))
        if r:
            shape("trade", r[0])
        hit_old = False
        for t in r:
            if not isinstance(t, dict):
                continue
            raw_w = t.get("proxy_wallet") or t.get("proxyWallet")
            if not isinstance(raw_w, str) or not raw_w.strip():
                continue
            w = raw_w.strip().lower()
            side_s = str(t.get("side") or "").strip().upper()
            if side_s not in ("BUY", "SELL"):
                continue
            try:
                ts = int(float(t["timestamp"]))
                if ts > 10**12:
                    ts //= 1000
                px = float(t["price"])
                sz = float(t["size"])
            except Exception:
                continue
            if not (math.isfinite(px) and math.isfinite(sz) and 0.0 < px < 1.0 and sz > 0.0):
                continue
            if ts >= t_tip:
                continue
            if ts < prev_last:
                hit_old = True
                continue
            first = arr_first(t, home_first, hi=hi, tokens=tokens)
            if first is None:
                continue
            tid = _trade_id(t, ts, w, side_s, first, sz, px)
            if tid in seen:
                continue
            seen.add(tid)
            buy = side_s == "BUY"
            sgn = 1.0 if (first == buy) else -1.0          # buying home or selling away adds home shares
            ph = px if first else 1.0 - px
            risk = sz * (px if buy else (1.0 - px))        # actual USD risked on this fill
            x = M["w"].setdefault(w, [0.0, 0.0, 0.0, 0, 0.0])
            if len(x) == 4:
                x.append(0.0)
            x[0] += sgn * sz
            x[1] += sgn * sz * ph
            x[2] += risk
            x[3] += 1
            x[4] += sz
            top = max(top, ts)
            new += 1
        if not cur or not r or hit_old:
            exhausted = True
            break
    # Only advance M["last"] when we actually connected cleanly back to prev_last or exhausted history
    if exhausted or prev_last == 0:
        M["last"] = top
    M["n"] = int(M.get("n") or 0) + new
    M["seen"] = list(seen)[-500:]
    for x in M["w"].values():
        x[0], x[1], x[2] = round(x[0], 2), round(x[1], 2), round(x[2], 2)
        if len(x) >= 5:
            x[4] = round(x[4], 2)
    jd(f, M)
    return new, M


def _wallet_stats(x):
    """Compute effective sample size N_eff and one-sided CLV t-stat for a wallet record."""
    n = int(x.get("n") or 0)
    if n < 2:
        return 0.0, 0.0, 0.0
    sw = float(x.get("sw") or 0.0)
    sw2 = float(x.get("sw2") or 0.0)
    neff = (sw * sw / sw2) if sw2 > 0 else float(n)
    # Unit-normalized per-game CLV% stats
    sp = float(x.get("clv_p_sum") or 0.0)
    sp2 = float(x.get("clv_p_sq") or 0.0)
    mean_p = sp / n
    var_p = max(0.0, (sp2 - n * mean_p * mean_p) / max(n - 1, 1))
    se_p = math.sqrt(var_p / max(neff, 1.0)) if var_p > 0 else 0.0
    t_clv = (mean_p / se_p) if se_p > 1e-12 else (99.0 if mean_p > 0 else 0.0)
    # Empirical Bayes shrinkage toward -0.5% taker-drag prior
    shrink = neff / (neff + 25.0)
    post = shrink * mean_p + (1.0 - shrink) * (-0.005)
    return neff, t_clv, post


def tracked():
    """Tracked wallets: our own board once >= min_cohort wallets pass N, N_eff and t_CLV gates; else paginated leaderboard."""
    W = jl(S + "wallets.json", {})
    own = set()
    for w, x in W.items():
        if int(x.get("n") or 0) < CFG["min_games"]:
            continue
        neff, t_clv, post = _wallet_stats(x)
        if neff >= CFG["min_neff"] and t_clv >= CFG["min_t_clv"] and post > 0:
            own.add(w)
    if len(own) >= CFG["min_cohort"]:
        return own, "own board"
    for cat in ("sports", "SPORTS"):
        try:
            found, cur = set(), None
            for _ in range(max(1, (CFG["board"] + 49) // 50)):
                p = {"category": cat, "time_period": "all", "sort_by": "PNL", "limit": min(50, CFG["board"] - len(found))}
                if cur:
                    p["cursor"] = cur
                r, cur = rows(get(DATA + "/v2/leaderboard", p))
                if not r:
                    break
                shape("leader", r[0])
                for x in r:
                    uid = str(x.get("user_id") or x.get("proxy_wallet") or x.get("proxyWallet") or "").strip().lower()
                    if uid:
                        found.add(uid)
                if not cur or len(found) >= CFG["board"]:
                    break
            if found:
                return found, "Polymarket sports leaderboard"
        except RuntimeError as e:
            ST["errors"].append(f"leaderboard {cat}: {e}")
    return set(), "none"


def _open_flow(M, T, mid_home):
    """Directional mark-to-market USD exposure from open shares N (NOT cumulative cost C), excluding flat/arb wallets."""
    net = 0.0
    nh = na = 0
    for w, x in M["w"].items():
        if w not in T:
            continue
        N = float(x[0])
        tot_sz = float(x[4]) if len(x) >= 5 else abs(N)
        if tot_sz <= 0 or (abs(N) / tot_sz) < CFG["min_dir_ratio"]:
            continue
        usd = N * mid_home if N > 0 else N * (1.0 - mid_home)   # signed open risk USD (+ Home, - Away)
        if abs(usd) < 50.0:
            continue
        net += usd
        if N > 0:
            nh += 1
        else:
            na += 1
    return net, nh, na


def cmd_pull(date):
    _reset_st()
    ours = our_games(date)
    now = datetime.datetime.now(ET)
    flow = {}
    T, src = set(), "none"
    try:
        T, src = tracked()
    except Exception as e:
        ST["errors"].append(f"tracked wallets: {e}")
    for lg in ("NBA", "NFL"):
        if not ours.get(lg):
            continue
        try:
            evs = events(lg)
        except Exception as e:
            ST["errors"].append(f"{lg} events: {e}")
            continue
        body, n = [], 0
        seen_games = set()
        for ev in evs:
            try:
                g, ml, c = match(lg, ev, ours[lg])
                if not g:
                    continue
                gid = str(g["id"])
                if gid in seen_games:
                    continue
                t_tip = tip(g, ev=ev, ml=ml)
                if t_tip is None:
                    continue                                   # fail closed when tipoff is unknown
                seen_games.add(gid)
                shape("market", ml)
                key = g["away"] + "@" + g["home"]
                names = arr(ml.get("outcomes"))
                tokens = arr(ml.get("clobTokenIds"))
                hi = c.index(g["home"])
                tip_dt = datetime.datetime.fromtimestamp(t_tip, ET)
                out = []
                mid_home = None
                # Pricing only pre-tip (>10 min before start)
                if now.timestamp() < t_tip - 600:
                    a = asks(ml)
                    if a:
                        ph_ask, pa_ask = (a[0], a[1]) if hi == 0 else (a[1], a[0])
                        mid_home = a[2] if hi == 0 else 1.0 - a[2]
                        out += [f"polymarket|h2h|{g['home']}||{american(ph_ask)}", f"polymarket|h2h|{g['away']}||{american(pa_ask)}"]
                        jd(S + "px/" + lg + "_" + gid + ".json", dict(
                            p_home=round(mid_home, 4), at=now.strftime("%Y-%m-%d %H:%M"), tip=t_tip,
                            lg=lg, id=gid, key=key, home=g["home"], away=g["away"], day=g["day"],
                        ))
                    tot_pick = _select_main_total(ev)
                    if tot_pick:
                        line, a2 = tot_pick
                        out += [f"polymarket|totals|Over|{line}|{american(a2[0])}", f"polymarket|totals|Under|{line}|{american(a2[1])}"]
                    if out:
                        body += [f"# game: {g['away']} @ {g['home']}", f"# tip: {tip_dt:%Y-%m-%d %H:%M} ET"] + out
                        n += 1
                else:
                    old_px = jl(S + "px/" + lg + "_" + gid + ".json", None)
                    if isinstance(old_px, dict):
                        mid_home = old_px.get("p_home")
                # Pre-tip trades still backfilled (end=t_tip) even after kickoff/tipoff for today's games
                if ml.get("conditionId") and (now.timestamp() < t_tip + 6 * 3600):
                    try:
                        _, M = pull_trades(lg + "_" + gid, ml["conditionId"], [names[hi], names[1 - hi]], t_tip, hi=hi, tokens=tokens)
                        if M and mid_home is not None and now.timestamp() < t_tip - 600:
                            net, nh, na = _open_flow(M, T, mid_home)
                            if nh + na:
                                flow.setdefault(lg, {})[key] = {
                                    "h2h": {
                                        g["home"]: dict(usd=round(net), n=nh + na, nh=nh, na=na, src=src),
                                        g["away"]: dict(usd=round(-net), n=nh + na, nh=na, na=nh, src=src),
                                    }
                                }
                    except Exception as e:
                        ST["errors"].append(f"{lg} {key} trades: {e}")
            except Exception as e:
                ST["errors"].append(f"{lg} event: {type(e).__name__}: {e}")
                continue
        if body:
            os.makedirs(O + "poly", exist_ok=True)
            with open(O + f"poly/{lg}_{date}.txt", "w", encoding="utf-8") as f:
                f.write(f"# polymarket pulled {now:%Y-%m-%d %H:%M} ET\nbookmaker_key|market_key|team|point|price\n" + "\n".join(body) + "\n")
        total_games = sum(len(v) for v in ours[lg].values())
        ST["notes"].append(f"{lg}: {len(evs)} events, {n} of {total_games} games priced")
    jd(S + f"{date}.json", flow)
    status(date, src, len(T))
    print("polymarket:", "; ".join(ST["notes"]) or "no games", "| tracked wallets:", len(T), f"({src})", "| calls", ST["calls"], "| errors", len(ST["errors"]))


def status(date, src=None, nt=None):
    old = jl(S + "status.json", {})
    jd(S + "status.json", dict(
        date=date, at=datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        calls=ST["calls"], notes=ST["notes"], errors=ST["errors"][:12],
        tracked=nt, tracked_src=src, shapes=dict(old.get("shapes") or {}, **ST["shapes"]),
        wallets=len(jl(S + "wallets.json", {})),
    ))


def _pin_close_home(lg, day, away, home, gline_mod):
    """Look up Pinnacle's closing no-vig home win probability for this game if saved in out/games/."""
    main, _ = gline_mod.files(lg, day)
    if not main:
        return None
    Q = gline_mod.parse(main)
    for k, v in Q.items():
        if k == "_asof" or not isinstance(v, dict):
            continue
        if v.get("away") == away and v.get("home") == home:
            pm = (v.get("q") or {}).get("pinnacle", {}).get("h2h", {})
            pr = gline_mod.pair(pm, home, away, bk="pinnacle", mk="h2h")
            if pr:
                return pr[2]
    return None


def cmd_score():
    """Fold every finished game's directional wallet positions into wallets.json using Pinnacle close when available."""
    import gline
    try:
        R = gline.results()
    except Exception as e:
        print("polymarket: results not read:", e)
        return
    W = jl(S + "wallets.json", {})
    done = 0
    pin_cache = {}
    for f in sorted(glob.glob(S + "px/*.json")):
        P = jl(f, None)
        if not isinstance(P, dict) or not all(k in P for k in ("lg", "id", "p_home", "day")):
            continue
        if (P["lg"], P["id"]) not in R:
            continue
        mf = S + "m/" + P["lg"] + "_" + P["id"] + ".json"
        M = jl(mf, None)
        m = R[(P["lg"], P["id"])][0]
        if isinstance(M, dict) and isinstance(M.get("w"), dict) and m != 0:
            won = 1.0 if m > 0 else 0.0
            ck = (P["lg"], P["day"], P.get("away"), P.get("home"))
            if ck not in pin_cache and P.get("away") and P.get("home"):
                pin_cache[ck] = _pin_close_home(P["lg"], P["day"], P["away"], P["home"], gline)
            p_close = pin_cache.get(ck) if pin_cache.get(ck) is not None else float(P["p_home"])
            for w, tup in M["w"].items():
                if not isinstance(tup, (list, tuple)) or len(tup) < 4:
                    continue
                N, C, gross, nt = float(tup[0]), float(tup[1]), float(tup[2]), int(tup[3])
                tot_sz = float(tup[4]) if len(tup) >= 5 else abs(N)
                if not (math.isfinite(N) and math.isfinite(C) and math.isfinite(gross)):
                    continue
                if gross < CFG["min_usd"] or nt > CFG["max_trades_game"]:
                    continue
                # v4.2: drop both-side arbers and flat market-making scalpers
                if tot_sz <= 0 or (abs(N) / tot_sz) < CFG["min_dir_ratio"]:
                    continue
                clv_usd = N * p_close - C
                pnl_usd = N * won - C
                clv_pct = clv_usd / max(gross, 1.0)
                w_cap = min(gross, 5000.0)                     # cap single-bet weight for N_eff so 1 whale bet can't dominate
                x = W.setdefault(w, dict(n=0, usd=0.0, clv=0.0, pnl=0.0, clv_p_sum=0.0, clv_p_sq=0.0, sw=0.0, sw2=0.0, NBA=0, NFL=0, last=""))
                x["n"] = int(x.get("n") or 0) + 1
                x[P["lg"]] = int(x.get(P["lg"]) or 0) + 1
                x["usd"] = round(float(x.get("usd") or 0.0) + gross, 2)
                x["clv"] = round(float(x.get("clv") or 0.0) + clv_usd, 2)
                x["pnl"] = round(float(x.get("pnl") or 0.0) + pnl_usd, 2)
                x["clv_p_sum"] = round(float(x.get("clv_p_sum") or 0.0) + clv_pct, 6)
                x["clv_p_sq"] = round(float(x.get("clv_p_sq") or 0.0) + clv_pct * clv_pct, 6)
                x["sw"] = round(float(x.get("sw") or 0.0) + w_cap, 2)
                x["sw2"] = round(float(x.get("sw2") or 0.0) + w_cap * w_cap, 2)
                x["last"] = P["day"]
            done += 1
        for z in (f, mf):
            if os.path.exists(z):
                os.remove(z)
    for z in glob.glob(S + "m/*.json") + glob.glob(S + "px/*.json"):
        if time.time() - os.path.getmtime(z) > 10 * 86400:
            os.remove(z)
    cut = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
    W = {w: x for w, x in W.items() if int(x.get("n") or 0) >= 3 or x.get("last", "") >= cut}
    jd(S + "wallets.json", W)
    print(f"polymarket: {done} games folded into the wallet board, {len(W)} wallets on it")


def board(W=None):
    W = jl(S + "wallets.json", {}) if W is None else W
    q = []
    for w, x in W.items():
        if int(x.get("n") or 0) >= CFG["min_games"]:
            neff, t_clv, post = _wallet_stats(x)
            q.append((w, x, neff, t_clv, post))
    return sorted(q, key=lambda z: -z[4])


def cmd_report():
    W = jl(S + "wallets.json", {})
    q = board(W)
    st = jl(S + "status.json", {})
    print(f"POLYMARKET WALLET BOARD (v4.2 tracking only). {len(W)} wallets seen, {len(q)} with {CFG['min_games']}+ directional NFL/NBA games.")
    print(f"  last pull: {st.get('at')}, tracked list: {st.get('tracked')} wallets from {st.get('tracked_src')}; errors: {st.get('errors') or 'none'}")
    for w, x, neff, t_clv, post in q[:15]:
        print(
            f"  {w[:6]}..{w[-4:]}  games {x['n']} (Neff {neff:.0f}, NBA {x['NBA']}, NFL {x['NFL']})  "
            f"dollars {x['usd']:,.0f}  CLV {x['clv'] / max(x['usd'], 1) * 100:+.2f}% (t={t_clv:+.2f}, post {post * 100:+.2f}%)  "
            f"result {x['pnl'] / max(x['usd'], 1) * 100:+.2f}%"
        )
    if not q:
        print("  no wallet has enough directional scored games yet. The board fills as games are played.")


if __name__ == "__main__":
    a = sys.argv[1:]
    try:
        if not a:
            print(__doc__)
        elif a[0] == "pull":
            cmd_pull(a[1])
        elif a[0] == "score":
            cmd_score()
        elif a[0] == "report":
            cmd_report()
    except Exception as e:
        ST["errors"].append(f"{a[0] if a else ''}: {type(e).__name__}: {e}")
        try:
            status(a[1] if len(a) > 1 else "")
        except Exception:
            pass
        print("POLYMARKET STEP FAILED:", type(e).__name__, e)

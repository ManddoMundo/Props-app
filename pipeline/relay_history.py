# Fair Line history pull (v3.22). Runs inside GitHub Actions, by hand only (Actions, "Fair Line history", Run workflow).
# Pulls the closing player prop lines for games already played from The Odds API's historical endpoint, one snapshot
# per game taken ten minutes before the start, and saves one encrypted file per league and day in data/history.
# It keeps to a credit cap and leaves a reserve for the daily job, and it picks up where it stopped: a day already
# saved is never pulled again. Secrets ODDS_API_KEY and RELAY_PASS come from the repository's Actions secrets.
# Neither is printed or written. history_status.json holds counts and dates only.
import os, sys, json, time, datetime, subprocess, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

KEY = os.environ.get("ODDS_API_KEY", "").strip()
PASS = os.environ.get("RELAY_PASS", "").strip()
CAP = int(float(os.environ.get("CAP") or 14000))            # most credits this run may spend
RESERVE = int(float(os.environ.get("RESERVE") or 4000))     # stop when the account has this many left (the daily job needs them)
LEAGUES = [x for x in (os.environ.get("LEAGUES") or "NFL,NBA").upper().replace(" ", "").split(",") if x in ("NFL", "NBA")]
SINCE = {"NFL": os.environ.get("SINCE_NFL") or "2026-09-09", "NBA": os.environ.get("SINCE_NBA") or "2026-10-20"}
ET = ZoneInfo("America/New_York")
UTC = datetime.timezone.utc
NOW = datetime.datetime.now(UTC)
API = "https://api.the-odds-api.com/v4/historical/sports/"
SPORT = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl"}
BOOKS = ["hardrockbet", "draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "fanatics", "polymarket", "novig", "kalshi"]      # ten books cost the same as one
# the markets the desk picks from, plus the two the simulator most needs checked (receptions, threes): 10 credits each a game
MARKETS = {"NFL": ["player_pass_yds", "player_rush_yds", "player_reception_yds", "player_receptions"],
           "NBA": ["player_points", "player_rebounds", "player_assists", "player_threes"]}
CODE = {"NBA": {"hawks": "ATL", "celtics": "BOS", "nets": "BKN", "hornets": "CHA", "bulls": "CHI", "cavaliers": "CLE", "mavericks": "DAL",
                "nuggets": "DEN", "pistons": "DET", "warriors": "GS", "rockets": "HOU", "pacers": "IND", "clippers": "LAC", "lakers": "LAL",
                "grizzlies": "MEM", "heat": "MIA", "bucks": "MIL", "timberwolves": "MIN", "pelicans": "NO", "knicks": "NY", "thunder": "OKC",
                "magic": "ORL", "76ers": "PHI", "suns": "PHX", "blazers": "POR", "kings": "SAC", "spurs": "SA", "raptors": "TOR",
                "jazz": "UTAH", "wizards": "WSH"},
        "NFL": {"cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF", "panthers": "CAR", "bears": "CHI", "bengals": "CIN",
                "browns": "CLE", "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB", "texans": "HOU", "colts": "IND",
                "jaguars": "JAX", "chiefs": "KC", "rams": "LA", "chargers": "LAC", "raiders": "LV", "dolphins": "MIA", "vikings": "MIN",
                "patriots": "NE", "saints": "NO", "giants": "NYG", "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "seahawks": "SEA",
                "49ers": "SF", "buccaneers": "TB", "titans": "TEN", "commanders": "WAS"}}

try:
    ST = json.load(open("history_status.json"))
except Exception:
    ST = {}
ST.setdefault("days", {})          # "NFL_2026-11-15": {games, rows, credits}; a day with no games is recorded with games 0
errors, notes, spent = [], [], 0
remaining = None


def finish(code=0):
    ST.update(updated_utc=datetime.datetime.now(UTC).strftime("%Y-%m-%d %H:%M"), last_spent=spent, remaining=remaining, errors=errors[-20:], notes=notes[-20:])
    json.dump(ST, open("history_status.json", "w"), indent=1)
    done = [k for k, v in ST["days"].items() if v.get("games")]
    print(f"history: credits spent {spent}, remaining {remaining}, days with lines saved so far {len(done)}, games {sum(ST['days'][k]['games'] for k in done)}, errors {len(errors)}")
    for x in errors[-20:] + notes[-20:]:
        print(" -", x)
    sys.exit(code)


def get(url, params):
    """JSON and headers. Errors carry the status and the API's own message, never the request URL."""
    global remaining, spent
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "fair-line-history"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            j, h = json.load(r), r.headers
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.read().decode('utf8', 'replace')[:200]}") from None
    except Exception as e:
        raise RuntimeError(type(e).__name__) from None
    try:
        remaining = int(float(h.get("x-requests-remaining")))
        spent += int(float(h.get("x-requests-last") or 0))
    except Exception:
        pass
    return j


def code(lg, team):
    w = str(team).lower().split()
    return CODE[lg].get(w[-1], str(team)) if w else str(team)


def fmt(x, price=False):
    if x is None:
        return ""
    return str(int(round(x))) if price else str(x)


def rows_for(ev):
    """One row per book, market and player: bookmaker|market|player|line|over|under. The same shape the daily relay saves.
    If a book lists more than one line for a player, the one priced closest to even is kept."""
    out = []
    for bk in ev.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            by = {}
            for o in m.get("outcomes") or []:
                nm = " ".join(str(o.get("description") or "").replace("|", "/").split())
                if nm:
                    by.setdefault((nm, o.get("point")), {})[str(o.get("name") or "").lower()] = o.get("price")
            best = {}
            for (nm, pt), d in by.items():
                ov, un = d.get("over"), d.get("under")
                bal = abs(ov - un) if ov is not None and un is not None else 1e9
                if nm not in best or bal < best[nm][0]:
                    best[nm] = (bal, pt, ov, un)
            for nm, (_, pt, ov, un) in sorted(best.items()):
                out.append("|".join([bk.get("key", ""), m.get("key", ""), nm, fmt(pt), fmt(ov, True), fmt(un, True)]))
    return out


def save(lg, day, body):
    os.makedirs("data/history", exist_ok=True)
    p = f"data/history/{lg}_{day}.txt"
    with open(p, "w") as f:
        f.write(f"# history pulled {NOW:%Y-%m-%d %H:%M} UTC, closing snapshot ten minutes before the start, books: {','.join(BOOKS)}\n"
                "bookmaker_key|market_key|player|line|over_price|under_price\n" + "\n".join(body) + "\n")
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-salt", "-pass", "env:RELAY_PASS",
                    "-in", p, "-out", p + ".enc"], check=True)
    os.remove(p)


def z(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def budget_left():
    return min(CAP - spent, (remaining - RESERVE) if remaining is not None else CAP - spent)


def pull_day(lg, day):
    """True if the day was finished (saved, or no games), False if the run should stop."""
    global BOOKS
    d0 = datetime.datetime.fromisoformat(day + "T10:00:00+00:00")       # 5 or 6 AM Eastern: before any game of that day
    if d0 + datetime.timedelta(hours=30) > NOW:                         # not all played yet
        return True
    try:
        j = get(API + SPORT[lg] + "/events", {"apiKey": KEY, "date": z(d0), "dateFormat": "iso",
                                              "commenceTimeFrom": z(d0), "commenceTimeTo": z(d0 + datetime.timedelta(hours=24) - datetime.timedelta(seconds=1))})
    except RuntimeError as x:
        errors.append(f"{lg} {day} events: {x}")
        return "HTTP 401" not in str(x) and "HTTP 429" not in str(x) and "quota" not in str(x).lower()
    evs = sorted(j.get("data") or [], key=lambda e: e.get("commence_time", ""))
    if not evs:
        ST["days"][f"{lg}_{day}"] = dict(games=0, rows=0, credits=0)
        return True
    need = len(evs) * len(MARKETS[lg]) * 10
    if need > budget_left():
        notes.append(f"{lg} {day}: stopped before this day, it needs about {need} credits and {max(budget_left(), 0)} are left under the cap and reserve")
        return False
    body, rows_n, before = [], 0, spent
    for e in evs:
        t = datetime.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        label = f"{code(lg, e.get('away_team'))} @ {code(lg, e.get('home_team'))}"
        ev = None
        for attempt in (1, 2):
            try:
                ev = (get(API + SPORT[lg] + "/events/" + e["id"] + "/odds", {"apiKey": KEY, "date": z(t - datetime.timedelta(minutes=10)), "bookmakers": ",".join(BOOKS),
                                                                            "markets": ",".join(MARKETS[lg]), "oddsFormat": "american", "dateFormat": "iso"}) or {}).get("data") or {}
                break
            except RuntimeError as x:
                if attempt == 1 and "bookmaker" in str(x).lower() and len(BOOKS) > 7:
                    BOOKS = BOOKS[:7]
                    continue
                errors.append(f"{lg} {day} {label}: {x}")
                if "HTTP 401" in str(x) or "HTTP 429" in str(x) or "quota" in str(x).lower():
                    return False
                break
        time.sleep(0.25)
        rows = rows_for(ev) if ev else []
        if rows:
            body += [f"# game: {label}", f"# tip: {t.astimezone(ET):%Y-%m-%d %H:%M} ET"] + rows
            rows_n += len(rows)
    games = sum(1 for b in body if b.startswith("# game:"))
    if body:
        save(lg, day, body)
    ST["days"][f"{lg}_{day}"] = dict(games=games, rows=rows_n, credits=spent - before, listed=len(evs))
    return True


if not KEY or not PASS:
    errors.append("Missing secret: add ODDS_API_KEY and RELAY_PASS under Settings, Secrets and variables, Actions")
    finish(1)
today = NOW.astimezone(ET).date()
stop = False
for lg in LEAGUES:
    d = today - datetime.timedelta(days=1)
    first = datetime.date.fromisoformat(SINCE[lg])
    while d >= first and not stop:
        k = f"{lg}_{d.isoformat()}"
        # football is played Thursday to Monday; skipping the other days saves the one credit a look costs
        if k not in ST["days"] and not (lg == "NFL" and d.weekday() in (1, 2)):
            if budget_left() < 50:
                notes.append(f"{lg}: stopped at {d}, the cap of {CAP} or the reserve of {RESERVE} was reached")
                stop = True
                break
            if not pull_day(lg, d.isoformat()):
                stop = True
                break
            if len(errors) >= 6:
                notes.append("Stopped after six errors. Nothing was lost: run it again once the cause is fixed.")
                stop = True
                break
        d -= datetime.timedelta(days=1)
    if stop:
        break
if not stop:
    notes.append("Every day back to the start dates is saved. Nothing left to pull.")
finish(0)

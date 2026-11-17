# Lines relay for Prop Underwriter. Runs inside GitHub Actions on a schedule.
# Pulls player prop lines from The Odds API and injury reports from ESPN, saves them as small text files,
# encrypts every data file with RELAY_PASS, and leaves a plain status.json (counts and timestamps only).
# Secrets ODDS_API_KEY and RELAY_PASS come from the repository's Actions secrets. Neither is printed or written.
import os, sys, json, datetime, subprocess, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

KEY = os.environ.get("ODDS_API_KEY", "").strip()
PASS = os.environ.get("RELAY_PASS", "").strip()
MODE = (os.environ.get("MODE") or "auto").strip().lower()
ET = ZoneInfo("America/New_York")
NOW = datetime.datetime.now(ET)
TODAY = NOW.strftime("%Y-%m-%d")
API = "https://api.the-odds-api.com/v4/sports/"
SPORT = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl"}
ESPN = {"NBA": "basketball/nba", "NFL": "football/nfl"}
# Hard Rock is the book the desk bets at. The rest are the market check. Up to ten books cost the same as one.
BOOKS = ["hardrockbet", "draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "fanatics"]
MARKETS = {"NBA": ["player_points", "player_rebounds", "player_assists", "player_threes", "player_points_rebounds_assists",
                   "player_points_rebounds", "player_points_assists", "player_rebounds_assists"],
           "NFL": ["player_pass_yds", "player_pass_attempts", "player_pass_completions", "player_pass_tds", "player_rush_yds",
                   "player_rush_attempts", "player_receptions", "player_reception_yds", "player_anytime_td"]}
# Alternate lines (the 15+, 20+, 25+ ladder) for the confident-plays lane. Midday pull only, full plan only: about 5 credits a game.
ALT = {"NBA": ["player_points_alternate", "player_rebounds_alternate", "player_assists_alternate", "player_threes_alternate",
               "player_points_rebounds_assists_alternate"],
       "NFL": ["player_pass_yds_alternate", "player_rush_yds_alternate", "player_reception_yds_alternate", "player_receptions_alternate"]}
LITE = {"NBA": ["player_points", "player_rebounds", "player_assists"], "NFL": ["player_reception_yds", "player_rush_yds", "player_pass_yds"]}
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
    ST = json.load(open("status.json"))
except Exception:
    ST = {}
ST.setdefault("files", [])
ST.setdefault("done", {})
errors, notes, spent = [], [], 0


def finish(code=0):
    ST.update(updated_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"), et=NOW.strftime("%Y-%m-%d %H:%M"),
              kind=KIND, tier=TIER, spent=spent, errors=errors, notes=notes)
    ST["files"] = ST["files"][-90:]
    json.dump(ST, open("status.json", "w"), indent=1)
    print(f"relay {KIND}: tier {TIER}, credits spent {spent}, remaining {ST.get('quota', {}).get('remaining')}, errors {len(errors)}")
    for x in errors + notes:
        print(" -", x)
    sys.exit(code)


def get(url, params):
    """JSON and headers. Errors carry the status and the API's own message, never the request URL."""
    req = urllib.request.Request(url + ("?" + urllib.parse.urlencode(params) if params else ""), headers={"User-Agent": "lines-relay"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r), r.headers
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.read().decode('utf8', 'replace')[:200]}") from None
    except Exception as e:
        raise RuntimeError(type(e).__name__) from None


def quota(h):
    try:
        ST["quota"] = {"remaining": int(float(h.get("x-requests-remaining"))), "used": int(float(h.get("x-requests-used")))}
    except Exception:
        pass


def code(lg, team):
    w = str(team).lower().split()
    return CODE[lg].get(w[-1], str(team)) if w else str(team)


def fmt(x, price=False):
    if x is None:
        return ""
    return str(int(round(x))) if price else str(x)


def rows_for(ev):
    """One row per book, market and player: bookmaker|market|player|line|over|under (anytime TD: line empty, yes|no)."""
    out = []
    for bk in ev.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            by = {}
            for o in m.get("outcomes") or []:
                nm = " ".join(str(o.get("description") or "").replace("|", "/").split())
                if nm:
                    by.setdefault((nm, o.get("point")), {})[str(o.get("name") or "").lower()] = o.get("price")
            if m.get("key", "").endswith("_alternate"):      # a ladder: keep every rung
                for (nm, pt), d in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1] if kv[0][1] is not None else 0)):
                    out.append("|".join([bk.get("key", ""), m.get("key", ""), nm, fmt(pt), fmt(d.get("over", d.get("yes")), True), fmt(d.get("under", d.get("no")), True)]))
                continue
            best = {}
            for (nm, pt), d in by.items():      # if a book lists more than one line, keep the one priced closest to even
                ov, un = d.get("over", d.get("yes")), d.get("under", d.get("no"))
                bal = abs(ov - un) if ov is not None and un is not None else 1e9
                if nm not in best or bal < best[nm][0]:
                    best[nm] = (bal, pt, ov, un)
            for nm, (_, pt, ov, un) in best.items():
                out.append("|".join([bk.get("key", ""), m.get("key", ""), nm, fmt(pt), fmt(ov, True), fmt(un, True)]))
    return out


def chosen(lg, evs):
    out = []
    for e in sorted(evs, key=lambda e: e.get("commence_time", "")):
        t = datetime.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(ET)
        mins = (t - NOW).total_seconds() / 60
        if mins < 10:
            continue
        same_day = t.strftime("%Y-%m-%d") == TODAY
        if KIND == "test":
            ok = True
        elif KIND == "close":
            ok = mins <= 270
        elif lg == "NBA" or TIER == "lite":
            ok = same_day
        else:                                   # NFL: the next 30 hours, and the whole week on Wednesday for the research room
            ok = mins <= (6 * 1440 if NOW.weekday() == 2 else 30 * 60)
        if ok:
            out.append((e, t))
    return out[:1] if KIND == "test" else out[:4] if TIER == "lite" else out


def save(what, lg, name, head, body, **meta):
    os.makedirs("data/" + what, exist_ok=True)
    p = f"data/{what}/{name}.txt"
    with open(p, "w") as f:
        f.write(head + "\n" + "\n".join(body) + "\n")
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-salt", "-pass", "env:RELAY_PASS",
                    "-in", p, "-out", p + ".enc"], check=True)
    plain = os.environ.get("RELAY_PLAIN")       # the daily build in this same job reads the plain copy; it is never committed
    if plain:
        os.makedirs(f"{plain}/{what}", exist_ok=True)
        with open(f"{plain}/{what}/{name}.txt", "w") as f:
            f.write(open(p).read())
    os.remove(p)
    ST["files"] = [f for f in ST["files"] if f.get("path") != p + ".enc"] + [dict(path=p + ".enc", what=what, lg=lg, date=TODAY, kind=KIND,
                                                                                et=NOW.strftime("%Y-%m-%d %H:%M"), **meta)]


def pull_lines(lg):
    global spent, BOOKS
    try:
        evs, h = get(API + SPORT[lg] + "/events", {"apiKey": KEY, "dateFormat": "iso"})
    except RuntimeError as x:
        errors.append(f"{lg} events: {x}")
        return
    quota(h)
    mk = (LITE if TIER == "lite" else MARKETS)[lg] + (ALT[lg] if TIER == "full" and KIND == "midday" else [])
    body, books, games = [], {}, 0
    picked = chosen(lg, evs)
    for e, t in picked:
        if spent + len(mk) > CAP:
            notes.append(f"{lg}: stopped at the credit cap of {CAP} after {games} of {len(picked)} games")
            break
        label = f"{code(lg, e.get('away_team'))} @ {code(lg, e.get('home_team'))}"
        j = None
        for attempt in (1, 2):
            try:
                j, h = get(API + SPORT[lg] + "/events/" + e["id"] + "/odds", {"apiKey": KEY, "bookmakers": ",".join(BOOKS),
                                                                             "markets": ",".join(mk), "oddsFormat": "american"})
                break
            except RuntimeError as x:
                if attempt == 1 and "bookmaker" in str(x).lower() and len(BOOKS) > 4:
                    BOOKS = BOOKS[:4]           # a book key the API no longer knows: fall back to the four it is known to carry
                    continue
                errors.append(f"{lg} {label}: {x}")
                break
        if j is None:
            continue
        quota(h)
        try:
            spent += int(float(h.get("x-requests-last")))
        except Exception:
            spent += len(mk)
        rows = rows_for(j)
        if rows:
            games += 1
            body += [f"# game: {label}", f"# tip: {t:%Y-%m-%d %H:%M} ET"] + rows
            for r in rows:
                b = r.split("|", 1)[0]
                books[b] = books.get(b, 0) + 1
    if not body:
        notes.append(f"{lg}: no lines to save ({len(picked)} games in the window)")
        return
    name = f"{lg}_test" if KIND == "test" else f"{lg}_{TODAY}" + (f"_close{NOW:%H}" if KIND == "close" else "")
    save("lines", lg, name, f"# relay pulled {NOW:%Y-%m-%d %H:%M} ET, {KIND}, books: {','.join(BOOKS)}\nbookmaker_key|market_key|player|line|over_price|under_price",
         body, rows=sum(books.values()), games=games, books=books, markets=len(mk))


def pull_news(lg):
    try:
        j, _ = get(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[lg]}/injuries", {})
    except RuntimeError as x:
        errors.append(f"{lg} injuries: {x}")
        return
    cell = lambda s: " ".join(str(s if s is not None else "").replace("|", "/").split())
    body = []
    for t in j.get("injuries") or []:
        for i in t.get("injuries") or []:
            a, d = i.get("athlete") or {}, i.get("details") or {}
            if not a.get("displayName"):
                continue
            body.append("| " + " | ".join(cell(x) for x in (t.get("displayName"), a.get("displayName"), (a.get("position") or {}).get("abbreviation"),
                                                          d.get("returnDate"), i.get("status"), i.get("shortComment") or i.get("longComment"))) + " |")
    if not body:
        notes.append(f"{lg}: injury report came back empty")
        return
    name = f"{lg}_test" if KIND == "test" else f"{lg}_{TODAY}"
    save("news", lg, name, f"Source: ESPN injuries feed, pulled {NOW:%Y-%m-%d %H:%M} ET by the relay, all teams.\n| team | player | pos | est_return | status | comment |\n|---|---|---|---|---|---|",
         body, rows=len(body))


def due():
    h = NOW.hour + NOW.minute / 60
    # GitHub starts scheduled runs late on busy days, sometimes by an hour or more, so each window is wide enough to catch
    # a late start. The midday pull must still land before the first game: weekends have 1 PM kickoffs, so it closes earlier then.
    if 6.5 <= h < 10.75 and ST["done"].get("early") != TODAY:      # morning refresh: grade last night, new projections, injuries. No credits.
        return "early"
    if 11 <= h < (12.75 if NOW.weekday() >= 5 else 15.5) and ST["done"].get("midday") != TODAY:
        return "midday"
    slot = "close_early" if h < 15 else "close_late"
    if ((18 <= h < 19.75) or (NOW.weekday() == 6 and 12 <= h < 13.75)) and ST["done"].get(slot) != TODAY:
        return "close"
    return None


KIND = MODE if MODE in ("early", "midday", "close", "test") else None if MODE == "none" else due()
with open("/tmp/relay_kind", "w") as f:
    f.write(KIND or "none")
TIER, CAP = "unknown", 0
if not KIND:
    print("Nothing due at", NOW.strftime("%a %H:%M ET"))
    sys.exit(0)
if not KEY or not PASS:
    errors.append("Missing secret: add ODDS_API_KEY and RELAY_PASS under Settings, Secrets and variables, Actions")
    finish(1)
try:                                            # a free call: proves the key and reads how many credits are left
    _, h0 = get(API + SPORT["NBA"] + "/events", {"apiKey": KEY, "dateFormat": "iso"})
    quota(h0)
except RuntimeError as x:
    errors.append(f"The Odds API did not accept the request: {x}")
    finish(1)
rem = ST.get("quota", {}).get("remaining")
TIER = "full" if rem is not None and rem >= 3000 else "lite" if rem is not None and rem >= 150 else "none"
CAP = {"full": 450, "lite": 24, "none": 0}[TIER]
if KIND == "test":
    CAP = min(CAP, 20)
if TIER == "none":
    notes.append("Credits are nearly gone, so no lines were pulled")
elif KIND == "early":
    notes.append("Morning refresh: no lines pulled, they post later in the morning")
elif KIND == "close" and TIER == "lite":
    notes.append("Closing lines are skipped on a small plan")
else:
    for lg in ("NBA", "NFL"):
        pull_lines(lg)
if KIND in ("early", "midday", "test"):
    for lg in ("NBA", "NFL"):
        pull_news(lg)
if KIND in ("early", "midday"):
    ST["done"][KIND] = TODAY
elif KIND == "close":
    ST["done"]["close_early" if NOW.hour < 15 else "close_late"] = TODAY
finish(0)

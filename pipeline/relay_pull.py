# Lines relay for Prop Underwriter (v4.2). Runs inside GitHub Actions on a schedule.
# Pulls player prop lines and game odds from The Odds API and injury reports from ESPN, saves them as small text files,
# encrypts every data file with RELAY_PASS, and leaves a plain status.json (counts and timestamps only).
# Secrets ODDS_API_KEY and RELAY_PASS come from the repository's Actions secrets. Neither is printed or written.
import os, sys, json, math, re, datetime, subprocess, urllib.request, urllib.parse, urllib.error
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
# Ten books cost the same as one region equivalent under Odds API v4 (1-10 books = 1 region).
# v4.0/4.2: Pinnacle is in both pull_lines (reference yardstick in daily.py) and pull_games (weighted sharp anchor in gline.py;
# games.py skips it via SKIP_BOOKS so legacy Games tab consensus is unchanged).
BOOKS = ["hardrockbet", "draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "fanatics", "pinnacle", "novig", "kalshi"]
MARKETS = {"NBA": ["player_points", "player_rebounds", "player_assists", "player_threes", "player_points_rebounds_assists",
                   "player_points_rebounds", "player_points_assists", "player_rebounds_assists"],
           "NFL": ["player_pass_yds", "player_pass_attempts", "player_pass_completions", "player_pass_tds", "player_rush_yds",
                   "player_rush_attempts", "player_receptions", "player_reception_yds", "player_anytime_td"]}
ALT = {"NBA": ["player_points_alternate", "player_rebounds_alternate", "player_assists_alternate", "player_threes_alternate",
               "player_points_rebounds_assists_alternate"],
       "NFL": ["player_pass_yds_alternate", "player_rush_yds_alternate", "player_reception_yds_alternate", "player_receptions_alternate"]}
LITE = {"NBA": ["player_points", "player_rebounds", "player_assists"], "NFL": ["player_reception_yds", "player_rush_yds", "player_pass_yds"]}
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

ST = {}
KIND, TIER, CAP = None, "unknown", 0
FULL_MIN = 500      # credits left at or above which the relay pulls everything
errors, notes, spent = [], [], 0


def _load_st():
    global ST
    try:
        with open("status.json", encoding="utf-8") as f:
            ST = json.load(f)
    except Exception:
        ST = {}
    ST.setdefault("files", [])
    ST.setdefault("done", {})


def finish(exit_code=0):
    ST.update(updated_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"), et=NOW.strftime("%Y-%m-%d %H:%M"),
              kind=KIND, tier=TIER, spent=spent, errors=errors, notes=notes)
    ST["files"] = ST["files"][-90:]
    with open("status.json", "w", encoding="utf-8") as f:
        json.dump(ST, f, indent=1)
    print(f"relay {KIND}: tier {TIER}, credits spent {spent}, remaining {ST.get('quota', {}).get('remaining')}, errors {len(errors)}")
    for x in errors + notes:
        print(" -", x)
    sys.exit(exit_code)


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
    if team is None:
        return ""
    s = re.sub(r"\([^)]*\)", " ", str(team).lower())
    if lg == "NBA" and "new orleans" in s and "hornets" in s:
        return "NO"
    w = re.sub(r"[^a-z0-9 ]", "", s).split()
    return CODE[lg].get(w[-1], str(team)) if w else str(team)


def fmt(x, price=False):
    if x is None or isinstance(x, bool):
        return ""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(v):
        return ""
    return str(int(round(v))) if price else str(x)


def rows_for(ev):
    """One row per book, market and player: bookmaker|market|player|line|over|under (anytime TD: line empty, yes|no)."""
    if not isinstance(ev, dict):
        return []
    out = []
    for bk in ev.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            by = {}
            for o in m.get("outcomes") or []:
                nm = " ".join(str(o.get("description") or "").replace("|", "/").split())
                if nm:
                    by.setdefault((nm, o.get("point")), {})[str(o.get("name") or "").lower()] = o.get("price")
            if m.get("key", "").endswith("_alternate"):
                for (nm, pt), d in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1] if kv[0][1] is not None else 0)):
                    out.append("|".join([bk.get("key", ""), m.get("key", ""), nm, fmt(pt), fmt(d.get("over", d.get("yes")), True), fmt(d.get("under", d.get("no")), True)]))
                continue
            best = {}
            for (nm, pt), d in by.items():
                ov, un = d.get("over", d.get("yes")), d.get("under", d.get("no"))
                try:
                    bal = abs(float(ov) - float(un)) if ov is not None and un is not None else 1e9
                except (TypeError, ValueError):
                    bal = 1e9
                if nm not in best or bal < best[nm][0]:
                    best[nm] = (bal, pt, ov, un)
            for nm, (_, pt, ov, un) in best.items():
                out.append("|".join([bk.get("key", ""), m.get("key", ""), nm, fmt(pt), fmt(ov, True), fmt(un, True)]))
    return out


def chosen(lg, evs):
    if not isinstance(evs, list):
        return []
    out = []
    for e in sorted(evs, key=lambda e: str(e.get("commence_time") or "") if isinstance(e, dict) else ""):
        if not isinstance(e, dict) or not e.get("commence_time"):
            continue
        try:
            t = datetime.datetime.fromisoformat(str(e["commence_time"]).replace("Z", "+00:00")).astimezone(ET)
        except ValueError:
            continue
        mins = (t - NOW).total_seconds() / 60
        if mins < 10:
            continue
        same_day = t.strftime("%Y-%m-%d") == TODAY
        if KIND == "test":
            ok = True
        elif KIND == "close":
            ok = mins <= 270
        elif KIND == "lineups":
            ok = mins <= 300
        elif lg == "NBA" or TIER == "lite":
            ok = same_day
        else:
            ok = mins <= (6 * 1440 if NOW.weekday() == 2 else 30 * 60)
        if ok:
            out.append((e, t))
    return out[:1] if KIND == "test" else out[:4] if TIER == "lite" else out


def save(what, lg, name, head, body, **meta):
    os.makedirs("data/" + what, exist_ok=True)
    p = f"data/{what}/{name}.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write(head + "\n" + "\n".join(body) + "\n")
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-salt", "-pass", "env:RELAY_PASS",
                    "-in", p, "-out", p + ".enc"], check=True)
    plain = os.environ.get("RELAY_PLAIN")
    if plain:
        os.makedirs(f"{plain}/{what}", exist_ok=True)
        with open(p, encoding="utf-8") as src_f, open(f"{plain}/{what}/{name}.txt", "w", encoding="utf-8") as dst_f:
            dst_f.write(src_f.read())
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
        for attempt in (1, 2, 3):
            try:
                j, h = get(API + SPORT[lg] + "/events/" + e["id"] + "/odds", {"apiKey": KEY, "bookmakers": ",".join(BOOKS),
                                                                             "markets": ",".join(mk), "oddsFormat": "american"})
                break
            except RuntimeError as x:
                if attempt < 3 and "bookmaker" in str(x).lower() and len(BOOKS) > 7:
                    BOOKS = BOOKS[:7]
                    continue
                if attempt < 3 and "bookmaker" in str(x).lower() and len(BOOKS) > 4:
                    BOOKS = BOOKS[:4]
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
    name = f"{lg}_test" if KIND == "test" else f"{lg}_{TODAY}" + (f"_close{NOW:%H}" if KIND == "close" else "_pm" if KIND == "evening" else "_late" if KIND == "lineups" else "")
    save("lines", lg, name, f"# relay pulled {NOW:%Y-%m-%d %H:%M} ET, {KIND}, books: {','.join(BOOKS)}\nbookmaker_key|market_key|player|line|over_price|under_price",
         body, rows=sum(books.values()), games=games, books=books, markets=len(mk))


def pull_games(lg):
    """Moneylines, spreads and totals for game picks & gline: one call a league for every game, 3 credits.
    v4.2: runs on midday, evening, close (Sunday 12:30 PM NFL), lineups (6:40/9:15 PM NBA), and test; also runs in lite tier."""
    global spent, BOOKS
    if CAP and spent + 3 > CAP:
        notes.append(f"{lg}: game odds skipped at credit cap {CAP}")
        return
    evs = h = None
    for attempt in (1, 2, 3):
        try:
            evs, h = get(API + SPORT[lg] + "/odds", {"apiKey": KEY, "bookmakers": ",".join(BOOKS), "markets": "h2h,spreads,totals", "oddsFormat": "american", "dateFormat": "iso"})
            break
        except RuntimeError as x:
            if attempt < 3 and "bookmaker" in str(x).lower() and len(BOOKS) > 7:
                BOOKS = BOOKS[:7]
                continue
            if attempt < 3 and "bookmaker" in str(x).lower() and len(BOOKS) > 4:
                BOOKS = BOOKS[:4]
                continue
            errors.append(f"{lg} game odds: {x}")
            return
    if not isinstance(evs, list):
        errors.append(f"{lg} game odds: unexpected response shape")
        return
    quota(h)
    try:
        spent += int(float(h.get("x-requests-last")))
    except Exception:
        spent += 3
    body, n = [], 0
    for e in sorted(evs, key=lambda e: str(e.get("commence_time") or "") if isinstance(e, dict) else ""):
        if not isinstance(e, dict) or not e.get("commence_time"):
            continue
        try:
            t = datetime.datetime.fromisoformat(str(e["commence_time"]).replace("Z", "+00:00")).astimezone(ET)
        except ValueError:
            continue
        mins = (t - NOW).total_seconds() / 60
        if mins < 10 or mins > (8 * 1440 if lg == "NFL" else 3 * 1440):
            continue
        rows = []
        for bk in e.get("bookmakers") or []:
            for m in bk.get("markets") or []:
                for o in m.get("outcomes") or []:
                    nm = o.get("name") or ""
                    team = code(lg, nm) if m.get("key") != "totals" else nm
                    px_s = fmt(o.get("price"), True)
                    if not px_s:
                        continue
                    rows.append("|".join([bk.get("key", ""), m.get("key", ""), team, fmt(o.get("point")), px_s]))
        if rows:
            n += 1
            body += [f"# game: {code(lg, e.get('away_team'))} @ {code(lg, e.get('home_team'))}", f"# tip: {t:%Y-%m-%d %H:%M} ET"] + rows
    if not body:
        notes.append(f"{lg}: no game odds to save")
        return
    sfx = f"_close{NOW:%H}" if KIND == "close" else "_pm" if KIND == "evening" else "_late" if KIND == "lineups" else ""
    name = f"{lg}_test" if KIND == "test" else f"{lg}_{TODAY}{sfx}"
    save("games", lg, name, f"# relay pulled {NOW:%Y-%m-%d %H:%M} ET, {KIND}, game odds\nbookmaker_key|market_key|team|point|price", body, rows=len(body), games=n)


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


NBA_CODE = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}


def pull_lineups():
    url = f"https://stats.nba.com/js/data/leaders/00_daily_lineups_{NOW:%Y%m%d}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                                               "Referer": "https://www.nba.com/", "Origin": "https://www.nba.com", "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            j = json.load(r)
    except Exception as x:
        errors.append(f"NBA lineups: {type(x).__name__} {str(x)[:120]}")
        return
    cell = lambda v: " ".join(str(v if v is not None else "").replace("|", "/").split())
    body, conf, n = [], 0, 0
    for g in j.get("games") or []:
        for side in ("awayTeam", "homeTeam"):
            t = g.get(side) or {}
            tcode = NBA_CODE.get(t.get("teamAbbreviation"), t.get("teamAbbreviation"))
            for p in t.get("players") or []:
                body.append("| " + " | ".join(cell(x) for x in (tcode, p.get("playerName"), p.get("position"), p.get("lineupStatus"), p.get("rosterStatus"))) + " |")
                n += 1
                conf += str(p.get("lineupStatus") or "").lower() == "confirmed"
    if not body:
        notes.append("NBA lineups: nba.com has no lineups posted for today yet")
        return
    save("lineups", "NBA", f"NBA_{TODAY}", f"Source: nba.com daily lineups, pulled {NOW:%Y-%m-%d %H:%M} ET by the relay. {conf} of {n} players confirmed.\n| team | player | pos | lineup | roster |\n|---|---|---|---|---|",
         body, rows=len(body), confirmed=conf)


def due():
    h = NOW.hour + NOW.minute / 60
    if 6.5 <= h < 10.75 and ST["done"].get("early") != TODAY:
        return "early"
    if 11 <= h < (12.75 if NOW.weekday() >= 5 else 15.5) and ST["done"].get("midday") != TODAY:
        return "midday"
    if 17.75 <= h < 19.75 and ST["done"].get("evening") != TODAY:
        return "evening"
    if NOW.weekday() == 6 and 12 <= h < 13.75 and ST["done"].get("close_early") != TODAY:
        return "close"
    if 18.5 <= h < 20.25 and ST["done"].get("evening") == TODAY and ST["done"].get("lineups_a") != TODAY:
        return "lineups"
    if 20.9 <= h < 23 and ST["done"].get("lineups_b") != TODAY:
        return "lineups"
    return None


def main():
    global KIND, TIER, CAP
    _load_st()
    KIND = MODE if MODE in ("early", "midday", "evening", "close", "test", "lineups") else None if MODE == "none" else due()
    with open("/tmp/relay_kind", "w", encoding="utf-8") as f:
        f.write(KIND or "none")
    TIER, CAP = "unknown", 0
    if not KIND:
        print("Nothing due at", NOW.strftime("%a %H:%M ET"))
        sys.exit(0)
    if not KEY or not PASS:
        errors.append("Missing secret: add ODDS_API_KEY and RELAY_PASS under Settings, Secrets and variables, Actions")
        finish(1)
    try:
        _, h0 = get(API + SPORT["NBA"] + "/events", {"apiKey": KEY, "dateFormat": "iso"})
        quota(h0)
    except RuntimeError as x:
        errors.append(f"The Odds API did not accept the request: {x}")
        finish(1)
    rem = ST.get("quota", {}).get("remaining")
    # v4.2.2 (Armanddo, Nov 27: "I want everything and I'll add more credits soon"): full pulls continue down to FULL_MIN credits
    # (it was 3000). 500 leaves room for one whole run at the 450 cap. Under that: three markets, four games. Under 150: nothing.
    TIER = "full" if rem is not None and rem >= FULL_MIN else "lite" if rem is not None and rem >= 150 else "none"
    CAP = {"full": 450, "lite": 24, "none": 0}[TIER]
    if KIND == "test":
        CAP = min(CAP, 20)
    if TIER == "none":
        notes.append("Credits are nearly gone, so no lines were pulled")
    elif KIND == "early":
        notes.append("Morning refresh: no lines pulled, they post later in the morning")
    elif KIND == "close" and TIER == "lite":
        notes.append("Closing prop lines are skipped on a small plan; pulling game odds (3 credits/league)")
        for lg in ("NBA", "NFL"):
            pull_games(lg)
    elif KIND == "lineups":
        if TIER == "full":
            for lg in ("NBA", "NFL"):
                pull_lines(lg)
                pull_games(lg)
        else:
            notes.append("Lineups run: no late prop prices on a small plan; pulling game odds")
            for lg in ("NBA", "NFL"):
                pull_games(lg)
    else:
        for lg in ("NBA", "NFL"):
            pull_lines(lg)
            if KIND in ("midday", "evening", "close", "test"):
                pull_games(lg)
    if KIND in ("early", "midday", "evening", "test", "lineups", "close"):
        for lg in ("NBA", "NFL"):
            pull_news(lg)
    if KIND in ("evening", "lineups", "test"):
        pull_lineups()
    if KIND in ("early", "midday", "evening"):
        ST["done"][KIND] = TODAY
    elif KIND == "close":
        ST["done"]["close_early" if NOW.hour < 15 else "close_late"] = TODAY
    elif KIND == "lineups":
        ST["done"]["lineups_a" if NOW.hour < 20 or (NOW.hour == 20 and NOW.minute < 54) else "lineups_b"] = TODAY
    finish(0)


if __name__ == "__main__":
    main()

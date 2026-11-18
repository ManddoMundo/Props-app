"""Who is out for the next games, from ESPN's public injury pages (no key). Falls back to the Sports Leader nightly
injury file when ESPN fails, but only when that file covers most of the league. Writes out/injuries.json:
  {asof, NBA: {src, teams, t: {team: {m, p: [[name, status, value]]}}}, NFL: {src, teams, t: {team: {p: [[name, status, pos, snaps]]}}}}
NBA value = the player's average Game Score this season (3 games or more) times his share of the team's last 10 games.
m = the team's status-weighted missing value. NFL lists only players who took 60% or more of the snaps in the team's last
three games, so long-term absences the line already reflects drop off. Display and tracking only: the game model does not
use it (tested: injuries explain how lines move from the open, but add nothing against the closing line).
A failure leaves the last file in place and the Games tab shows no injury notes."""
import json, re, datetime, urllib.request
import pandas as pd

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{}/injuries"
SL = "https://github.com/WalrusQuant/sportsleader-data/releases/download/{}_injuries/{}.parquet"
W = {"Out": 1.0, "Doubtful": .85, "Questionable": .4, "Day-To-Day": .4, "Injured Reserve": 1.0, "Suspension": 1.0}
NFLT = {"WSH": "WAS", "LAR": "LA"}
MIN_TEAMS = 15


def espn(path):
    """[(team, espn player id, name, status, position)] from ESPN's injury page."""
    req = urllib.request.Request(ESPN.format(path), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        js = json.load(r)
    out = []
    for tm in js.get("injuries") or []:
        for x in tm.get("injuries") or []:
            a = x.get("athlete") or {}
            t = (a.get("team") or {}).get("abbreviation")
            pid = None
            for ln in a.get("links") or []:
                m = re.search(r"/id/(\d+)", ln.get("href") or "")
                if m:
                    pid = int(m.group(1)); break
            st = x.get("status") or ""
            if t and st in W:
                out.append((t, pid, a.get("displayName") or "", st, (a.get("position") or {}).get("abbreviation") or ""))
    return out


def sportsleader(lg, season):
    """Same rows from the Sports Leader nightly file: the open entries seen in its newest snapshot."""
    f = f"{D}sl/{lg}_injuries_{season}.parquet"
    urllib.request.urlretrieve(SL.format(lg, season), f)
    i = pd.read_parquet(f)
    o = i[i.valid_to.isna() & (i.last_seen >= i.last_seen.max() - pd.Timedelta(hours=30))]
    o = o.sort_values("valid_from").groupby("player_id").tail(1)
    return [(r.team_abbr, None if pd.isna(r.player_id) else int(r.player_id), r.player_name, r.status, "" if pd.isna(r.position) else r.position)
            for r in o.itertuples() if r.status in W]


def rows(lg, path, season):
    err = []
    for name, f in (("espn", lambda: espn(path)), ("sportsleader", lambda: sportsleader(lg, season))):
        try:
            x = f()
            n = len({t for t, *_ in x})
            if n >= MIN_TEAMS:
                return name, x
            err.append(f"{name} covered {n} teams")
        except Exception as e:
            err.append(f"{name}: {str(e)[:60]}")
    raise RuntimeError("; ".join(err))


def nba(x):
    b = pd.read_parquet(D + "nba_pb_2027.parquet")
    b = b[b.season_type.isin([2, 3])].copy()
    num = lambda c: pd.to_numeric(b[c], errors="coerce").fillna(0) if c in b else 0
    b["gs"] = (num("points") + .4 * num("field_goals_made") - .7 * num("field_goals_attempted") - .4 * (num("free_throws_attempted") - num("free_throws_made"))
               + .7 * num("offensive_rebounds") + .3 * num("defensive_rebounds") + num("steals") + .7 * num("assists") + .7 * num("blocks") - .4 * num("fouls") - num("turnovers"))
    b["pid"] = pd.to_numeric(b.athlete_id, errors="coerce"); b["mn"] = num("minutes")
    last10 = {t: set(z.sort_values("game_date").game_id.unique()[-10:]) for t, z in b.groupby("team_abbreviation")}
    pl = b[b.mn > 0]
    val = {}
    for (t, p), z in pl.groupby(["team_abbreviation", "pid"]):
        if len(z) >= 3:
            val[(t, p)] = (float(z.gs.mean()), len(set(z.game_id) & last10.get(t, set())) / 10.0)
    T = {}
    for t, pid, nm, st, pos in x:
        avg, rec = val.get((t, pid), (0.0, 0.0))
        v = W[st] * rec * max(avg, 0)
        e = T.setdefault(t, dict(m=0.0, p=[]))
        if v > 0:
            e["m"] += v; e["p"].append([nm, st, round(avg * rec, 1)])
    for e in T.values():
        e["m"] = round(e["m"], 1); e["p"].sort(key=lambda q: -q[2]); e["p"] = e["p"][:5]
    return T


def nfl(x):
    s = pd.read_csv(D + "nfl_snaps_2026.csv")
    s = s[s.game_type == "REG"] if "game_type" in s else s
    wk = {t: sorted(z.week.unique())[-3:] for t, z in s.groupby("team")}
    s = s[s.apply(lambda r: r.week in wk.get(r.team, []), axis=1)].copy()
    s["sh"] = s[["offense_pct", "defense_pct"]].max(axis=1)
    norm = lambda n: re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", str(n).lower()))
    share = (s.assign(k=s.player.map(norm)).groupby(["team", "k"]).sh.sum() / 3.0).to_dict()
    T = {}
    for t, pid, nm, st, pos in x:
        t = NFLT.get(t, t); sh = share.get((t, norm(nm)), 0.0)
        e = T.setdefault(t, dict(p=[]))
        if sh >= .6 and st != "Questionable" or (sh >= .6 and pos == "QB"):
            e["p"].append([nm, st, pos, round(sh, 2)])
    for e in T.values():
        e["p"].sort(key=lambda q: (q[2] != "QB", q[1] == "Questionable", -q[3])); e["p"] = e["p"][:5]
    return T


def main():
    try:
        out = json.load(open(O + "injuries.json"))
    except Exception:
        out = {}
    msg = []
    for lg, path, season, f in (("NBA", "basketball/nba", 2027, nba), ("NFL", "football/nfl", 2026, nfl)):
        try:
            src, x = rows(lg.lower(), path, season)
            T = f(x)
            out[lg] = dict(src=src, teams=len(T), t=T, asof=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
            msg.append(f"{lg} {len(T)} teams from {src}")
        except Exception as e:
            msg.append(f"{lg} not refreshed ({str(e)[:120]})")
    json.dump(out, open(O + "injuries.json", "w"), separators=(",", ":"))
    print("injuries: " + " | ".join(msg))


if __name__ == "__main__":
    main()

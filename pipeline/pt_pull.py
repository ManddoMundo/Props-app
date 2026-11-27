#!/usr/bin/env python3
"""Lab data puller (nothing here runs in the daily job):
Pulls daily player-game tracking stats from stats.nba.com (leaguedashptstats, PerMode=Totals)
for Passing (POTENTIAL_AST, AST) and Rebounding (REB_CHANCES, REB) across the game dates
present in nba_pb_{season}.parquet, saving resumable parquet caches to /home/claude/props/data/nba_pt_{season}.parquet.

Note: stats.nba.com frequently rate-limits or blocks cloud IPs (GitHub Actions / containers).
If requests time out or return 403/429, run this script on a residential/local machine and copy
nba_pt_2025.parquet, nba_pt_2026.parquet, nba_pt_2027.parquet into /home/claude/props/data/.

Usage:
  python3 pt_pull.py                 # pulls 2025, 2026, 2027 seasons (resuming any existing dates)
  python3 pt_pull.py 2027            # pulls 2026-27 season only
  python3 pt_pull.py 2025 --limit 5  # test 5 dates first"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
import pandas as pd

D = "/home/claude/props/data/"
BASE_URL = "https://stats.nba.com/stats/leaguedashptstats"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}
SEASON_STR = {2025: "2024-25", 2026: "2025-26", 2027: "2026-27"}


def fetch_day(season_str, date_iso, measure, retries=3):
    """Fetch one day (YYYY-MM-DD) of leaguedashptstats for PtMeasureType in ('Passing', 'Rebounding')."""
    y, m, d = date_iso.split("-")
    mmddyyyy = f"{m}/{d}/{y}"
    params = {
        "College": "", "Conference": "", "Country": "",
        "DateFrom": mmddyyyy, "DateTo": mmddyyyy,
        "Division": "", "DraftPick": "", "DraftYear": "",
        "GameScope": "", "Height": "", "LastNGames": "0",
        "LeagueID": "00", "Location": "", "Month": "0",
        "OpponentTeamID": "0", "Outcome": "", "PORound": "0",
        "PerMode": "Totals", "PlayerExperience": "", "PlayerOrTeam": "Player",
        "PlayerPosition": "", "PtMeasureType": measure,
        "Season": season_str, "SeasonSegment": "", "SeasonType": "Regular Season",
        "StarterBench": "", "TeamID": "0", "VsConference": "",
        "VsDivision": "", "Weight": "",
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    for att in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
            rs = j["resultSets"][0]
            return pd.DataFrame(rs["rowSet"], columns=rs["headers"])
        except Exception as e:
            if att == retries:
                raise RuntimeError(f"{measure} {date_iso}: {type(e).__name__} {str(e)[:100]}") from None
            time.sleep(2.5 * att)
    return pd.DataFrame()


def pull_season(season, limit=None):
    pb_path = f"{D}nba_pb_{season}.parquet"
    if not os.path.exists(pb_path):
        print(f"Missing {pb_path}; run run.sh first.")
        return
    pb = pd.read_parquet(pb_path, columns=["game_date", "season_type"])
    dates = sorted(pb[pb.season_type == 2].game_date.astype(str).str[:10].unique())
    out_path = f"{D}nba_pt_{season}.parquet"
    cur = pd.read_parquet(out_path) if os.path.exists(out_path) else pd.DataFrame()
    done = set(cur["gd"].unique()) if len(cur) else set()
    todo = [dt for dt in dates if dt not in done]
    if limit is not None:
        todo = todo[:limit]
    print(f"Season {season} ({SEASON_STR[season]}): {len(dates)} reg dates, {len(done)} cached, {len(todo)} to pull")
    rows = [cur] if len(cur) else []
    sstr = SEASON_STR[season]
    for i, dt in enumerate(todo, 1):
        try:
            p = fetch_day(sstr, dt, "Passing")
            time.sleep(0.75)
            r = fetch_day(sstr, dt, "Rebounding")
            time.sleep(0.75)
        except RuntimeError as err:
            print(f"  STOP at {dt}: {err}")
            break
        if p.empty and r.empty:
            continue
        p_sub = p[["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "AST", "POTENTIAL_AST"]].copy() if len(p) else pd.DataFrame(columns=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "AST", "POTENTIAL_AST"])
        r_sub = r[["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "REB", "REB_CHANCES"]].copy() if len(r) else pd.DataFrame(columns=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "REB", "REB_CHANCES"])
        m = p_sub.merge(r_sub, on=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"], how="outer")
        m["gd"] = dt
        m["season"] = season
        rows.append(m)
        if i % 10 == 0 or i == len(todo):
            df = pd.concat(rows, ignore_index=True).drop_duplicates(["gd", "PLAYER_ID"], keep="last")
            df.to_parquet(out_path, index=False)
            print(f"  saved {i}/{len(todo)} ({dt}): {len(df)} total player-days -> {out_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]
    seasons = [int(x) for x in args] if args else [2025, 2026, 2027]
    for s in seasons:
        pull_season(s, limit=limit)

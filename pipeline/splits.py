"""Trends by split for the Research room: each slate player's recent games tagged home or away, rest, and how soft the
opponent's defense was for each stat, so the page can show his record against today's line in the same situation as
tonight. Display only: nothing here feeds the projections or the desk's picks.

Writes out/research/splits_nba.json and out/research/splits_nfl.json (fetched by the page when the Splits sheet opens):
  {asof, cols: [...], rank: {season: {team: {stat: rank}}}, p: {player id: [[date, opp, home, rest, start, season, *stats], ...]}}
Rank 1 is the defense that allows the most of that stat per game (the softest). Rest is days off before the game."""
import json, os
import numpy as np, pandas as pd

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
DATA = json.load(open(O + "data.json"))
os.makedirs(O + "research", exist_ok=True)


def ranks(df, team_col, opp_col, game_col, stats):
    """Per season, what each defense allows a game for each stat, ranked 1 (allows most) to N."""
    out = {}
    for s, d in df.groupby("season"):
        g = d.groupby([game_col, opp_col])[stats].sum().reset_index()          # what each defense gave up in each game
        a = g.groupby(opp_col)[stats].mean()
        out[str(s)] = {t: {k: int(r) for k, r in zip(stats, row)} for t, row in a.rank(ascending=False, method="min").iterrows()}
    return out


def nba():
    d = pd.concat([pd.read_parquet(f"{D}nba_pb_{y}.parquet") for y in (2026, 2027)])
    d = d[d.season_type.isin([2, 3, 5]) & d.minutes.notna() & (d.minutes > 0)].copy()
    d = d.rename(columns={"points": "pts", "rebounds": "reb", "assists": "ast", "three_point_field_goals_made": "fg3",
                          "team_abbreviation": "team", "opponent_team_abbreviation": "opp", "minutes": "min"})
    for k in ("pts", "reb", "ast", "fg3"): d[k] = d[k].fillna(0)
    for c, parts in {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}.items():
        d[c] = d[parts].sum(axis=1)
    d["pid"] = d.athlete_id.astype(float).astype(str)
    d["gd"] = pd.to_datetime(d.game_date)
    stats = ["pts", "reb", "ast", "fg3", "pra", "pr", "pa", "ra"]
    rk = ranks(d, "team", "opp", "game_id", stats)
    # team rest: days since the team's previous game, minus one (0 = second night of a back-to-back)
    tg = d[["team", "game_id", "gd"]].drop_duplicates().sort_values("gd")
    tg["rest"] = tg.groupby("team").gd.diff().dt.days.sub(1).clip(lower=0, upper=7)
    d = d.merge(tg[["team", "game_id", "rest"]], on=["team", "game_id"], how="left")
    want = {p["id"] for p in DATA["NBA"]["players"] if p["m"] >= 10}
    P = {}
    for pid, x in d[d.pid.isin(want)].sort_values("gd").groupby("pid"):
        x = x.tail(30)
        P[pid] = [[r.gd.strftime("%Y-%m-%d"), r.opp, int(r.home_away == "home"), None if pd.isna(r.rest) else int(r.rest), int(bool(r.starter)), int(r.season),
                   int(r["min"]), int(r.pts), int(r.reb), int(r.ast), int(r.fg3)] for _, r in x.iterrows()]
    cur = str(int(d.season.max()))
    tr = tg.sort_values("gd").groupby("team").gd.last().dt.strftime("%Y-%m-%d").to_dict()      # each club's last game, for tonight's rest
    return dict(asof=str(d.gd.max().date()), cur=cur, cols=["date", "opp", "home", "rest", "start", "season", "min", "pts", "reb", "ast", "fg3"],
                rank=rk, last=tr, p=P)


def nfl():
    w = pd.concat([pd.read_csv(f"{D}nfl_pw_{y}.csv", low_memory=False) for y in (2025, 2026)])
    w = w[w.season_type.isin(["REG", "POST"])].copy()
    num = ["passing_yards", "attempts", "completions", "passing_tds", "rushing_yards", "carries", "receptions", "receiving_yards", "rushing_tds", "receiving_tds"]
    for k in num: w[k] = w[k].fillna(0)
    w = w.rename(columns={"passing_yards": "pass_yds", "attempts": "pass_att", "completions": "pass_cmp", "passing_tds": "pass_td", "rushing_yards": "rush_yds",
                          "carries": "rush_att", "receptions": "rec", "receiving_yards": "rec_yds"})
    w["td"] = (w.rushing_tds + w.receiving_tds > 0).astype(int)
    g = pd.read_csv(f"{D}nfl_games.csv", low_memory=False)
    g = g[g.season.isin([2025, 2026])][["game_id", "gameday", "home_team", "away_team", "home_rest", "away_rest"]]
    w = w.merge(g, on="game_id", how="left")
    w["home"] = (w.team == w.home_team).astype(int)
    w["rest"] = np.where(w.home == 1, w.home_rest, w.away_rest)
    stats = ["pass_yds", "pass_att", "pass_cmp", "pass_td", "rush_yds", "rush_att", "rec", "rec_yds", "td"]
    rk = ranks(w, "team", "opponent_team", "game_id", stats)
    want = {p["id"] for p in DATA["NFL"]["players"]}
    P = {}
    for pid, x in w[w.player_id.isin(want)].sort_values(["season", "week"]).groupby("player_id"):
        x = x.tail(17)
        P[pid] = [[str(r.gameday) if isinstance(r.gameday, str) else "", r.opponent_team, int(r.home), None if pd.isna(r.rest) else int(r.rest), 1, int(r.season),
                   int(r.week)] + [int(r[k]) for k in stats] for _, r in x.iterrows()]
    cur = str(int(w.season.max()))
    gs = g.dropna(subset=["gameday"])
    played = w[["team", "gameday"]].dropna().drop_duplicates().sort_values("gameday")
    tr = played.groupby("team").gameday.last().to_dict()
    return dict(asof=str(w.gameday.dropna().max()), cur=cur, cols=["date", "opp", "home", "rest", "start", "season", "week"] + stats, rank=rk, last=tr, p=P)


if __name__ == "__main__":
    for lg, f in (("nba", nba), ("nfl", nfl)):
        try:
            r = f()
            json.dump(r, open(O + f"research/splits_{lg}.json", "w"), separators=(",", ":"))
            print(f"splits {lg}: {len(r['p'])} players, {os.path.getsize(O + f'research/splits_{lg}.json') // 1024} KB")
        except Exception as e:
            print(f"splits {lg} failed:", e)

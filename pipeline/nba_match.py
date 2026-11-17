"""NBA matchup sheets for the Research room: defense by position, pace, and each rotation player's minutes trend.
Display only: nothing here feeds the projections or the desk's picks.

Writes out/research/nba_match.json (fetched when the sheet opens):
  {asof, season, lg: {pace, dvp: {pos: {stat: per game}}}, teams: {team: {g, pace, pace_rk, dvp: {pos: {stat: [per game, rank]}}}},
   min: {player id: [season avg, last 5 avg, last game, games]}}
Defense by position: what a defense gives up a game to guards (G), forwards (F) and centers (C), this season. Rank 1 gives
up the most. Pace: possessions a game (both teams' average), estimated from the box score as FGA - OREB + TOV + 0.44 FTA."""
import json, os
import numpy as np, pandas as pd

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
DATA = json.load(open(O + "data.json"))
STATS = ["pts", "reb", "ast", "fg3"]


def main():
    d = pd.read_parquet(f"{D}nba_pb_2027.parquet")
    d = d[d.season_type.isin([2, 3, 5]) & d.minutes.notna() & (d.minutes > 0)].copy()
    d = d.rename(columns={"points": "pts", "rebounds": "reb", "assists": "ast", "three_point_field_goals_made": "fg3",
                          "team_abbreviation": "team", "opponent_team_abbreviation": "opp", "minutes": "min"})
    for k in STATS + ["field_goals_attempted", "offensive_rebounds", "turnovers", "free_throws_attempted"]:
        d[k] = d[k].fillna(0)
    d["pos"] = d.athlete_position_abbreviation.map(lambda p: "G" if p in ("PG", "SG", "G") else ("C" if p == "C" else "F"))
    d["pid"] = d.athlete_id.astype(float).astype(str)
    # pace: each team's possessions in a game, averaged with its opponent's
    t = d.groupby(["game_id", "team", "opp"]).agg(fga=("field_goals_attempted", "sum"), orb=("offensive_rebounds", "sum"),
                                                  tov=("turnovers", "sum"), fta=("free_throws_attempted", "sum")).reset_index()
    t["poss"] = t.fga - t.orb + t.tov + 0.44 * t.fta
    g = t.groupby("game_id").poss.mean().rename("gposs")
    t = t.merge(g, on="game_id")
    pace = t.groupby("team").gposs.mean()
    games = t.groupby("team").game_id.nunique()
    # defense by position: what each defense allows a game to each position group
    a = d.groupby(["game_id", "opp", "pos"])[STATS].sum().reset_index()
    allowed = a.groupby(["opp", "pos"])[STATS].sum().reset_index()
    allowed = allowed[allowed.opp.isin(games.index)]
    allowed[STATS] = allowed[STATS].div(allowed.opp.map(games), axis=0)
    teams = {}
    pr = pace.rank(ascending=False, method="min")
    for tm in pace.index:
        teams[tm] = dict(g=int(games[tm]), pace=round(float(pace[tm]), 1), pace_rk=int(pr[tm]), dvp={})
    for pos, x in allowed.groupby("pos"):
        x = x.set_index("opp")
        for k in STATS:
            rk = x[k].rank(ascending=False, method="min")
            for tm in x.index:
                if tm in teams:
                    teams[tm]["dvp"].setdefault(pos, {})[k] = [round(float(x.loc[tm, k]), 1), int(rk[tm])]
    lgv = {pos: {k: round(float(x[k].mean()), 1) for k in STATS} for pos, x in allowed.groupby("pos")}
    # minutes trend for everyone on the slate
    want = {p["id"] for p in DATA["NBA"]["players"]}
    M = {}
    for pid, x in d[d.pid.isin(want)].sort_values("game_date").groupby("pid"):
        m = x["min"].values
        M[pid] = [round(float(m.mean()), 1), round(float(m[-5:].mean()), 1), int(m[-1]), int(len(m))]
    out = dict(asof=str(d.game_date.max())[:10], season=int(d.season.max()), lg=dict(pace=round(float(pace.mean()), 1), dvp=lgv), teams=teams, min=M)
    os.makedirs(O + "research", exist_ok=True)
    json.dump(out, open(O + "research/nba_match.json", "w"), separators=(",", ":"))
    print(f"nba matchups: {len(teams)} teams, {len(M)} players, {os.path.getsize(O + 'research/nba_match.json') // 1024} KB")


if __name__ == "__main__":
    main()

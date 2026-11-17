"""With and without: what actually happened to each teammate in the games a regular missed, and how far the
stress test's own shift (the engine, run on today's roster) lands from that. Display and audit only: nothing here
feeds the projections or the desk's picks.

Writes out/ww.json:
  NBA / NFL -> { by: {player id: {n_out, n_in, mates: [...]}}, check: {...} }
Each mate row holds his per-game average with the player in and with him out, over the games where the mate played,
plus the engine's predicted change when the player is switched off today. Samples are small; the page shows n."""
import json, math
import numpy as np, pandas as pd

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
DATA = json.load(open(O + "data.json"))


# ---------- the engine, as in engine.js (same maths, so a shift here is the shift the page shows) ----------
def nba_side(model, side, roster, active):
    act = [p for p in roster if active(p)]
    tot = sum(p["m"] for p in act); W = sum(p["m"] * max(38 - p["m"], 0.5) for p in act)
    mins, out = {}, {}
    for p in act:
        up = p["m"] + (240 - tot) * (p["m"] * max(38 - p["m"], 0.5)) / W
        mins[p["id"]] = min(p["m"] + model["bm"] * ((up if tot < 240 else p["m"] * 240 / tot) - p["m"]), 40)
        out[p["id"]] = {"min": mins[p["id"]]}
    for k in ("pts", "reb", "ast", "fg3"):
        R = sum(mins[p["id"]] * p["r"][k] for p in act)
        boost = (side["T"][k] / R) ** model["bs"][k] * model["cal"][k]
        ln = model.get("lin", {}).get(k)
        for p in act:
            raw = mins[p["id"]] * p["r"][k] * boost
            out[p["id"]][k] = max(0.05, ln[0] + ln[1] * raw) if ln else raw
    return out


def nfl_side(model, side, roster, active):
    act = [p for p in roster if active(p)]
    St, Sc = side["rest"][0], side["rest"][1]
    for p in act: St += p["ts"]; Sc += p["cs"]
    b, c, out = model["beta"], model["cal"], {}
    lin = model.get("lin") or {}
    L = lambda k, v: max(0.05, lin[k][0] + lin[k][1] * v) if k in lin else v
    for p in act:
        tsn = p["ts"] * max(St, 1e-9) ** -b; csn = p["cs"] * max(Sc, 1e-9) ** -b
        tgt = side["PA"] * model["tpa"] * tsn; car = side["CAR"] * csn
        out[p["id"]] = {"tgt": tgt, "car": L("rush_att", car * c["rush_att"]),
                        "rec_yds": L("rec_yds", tgt * p["cr"] * p["ypr"] * side["padj"] * c["rec_yds"]),
                        "rush_yds": L("rush_yds", car * p["ypc"] * side["radj"] * c["rush_yds"])}
    return out


def shift(lg, side, roster, x):
    f = nba_side if lg == "NBA" else nfl_side
    M = DATA[lg]["model"]
    base = f(M, side, roster, lambda p: p["active"] or p["id"] == x)
    sat = f(M, side, roster, lambda p: (p["active"] or p["id"] == x) and p["id"] != x)
    return {i: {k: sat[i][k] - base[i][k] for k in sat[i]} for i in sat if i in base}


def mean(v):
    return float(np.mean(v)) if len(v) else None


# ---------- NBA: last season and this one, regular season and playoffs ----------
def nba():
    L = DATA["NBA"]
    d = pd.concat([pd.read_parquet(f"{D}nba_pb_{y}.parquet") for y in (2026, 2027)])
    d = d[d.season_type.isin([2, 3, 5])].copy()
    d["pid"] = d.athlete_id.astype(float).astype(str)
    d["min"] = d.minutes.fillna(0)
    d = d.rename(columns={"points": "pts", "rebounds": "reb", "assists": "ast", "three_point_field_goals_made": "fg3", "team_abbreviation": "team"})
    for k in ("pts", "reb", "ast", "fg3"): d[k] = d[k].fillna(0)
    d["gd"] = d.game_date.astype(str)
    tg = d.groupby(["team", "season"]).apply(lambda x: sorted(set(zip(x.gd, x.game_id))), include_groups=False).to_dict()
    roster = {}
    for p in L["players"]: roster.setdefault(p["team"], []).append(p)
    sides = {s["team"]: s for s in L["sides"]}
    by, pairs = {}, []
    for t, rs in roster.items():
        side = sides.get(t)
        if side is None: continue
        dt = d[d.team == t]
        for xp in rs:
            if xp["m"] < 20: continue                     # regulars only: a bench player sitting moves nothing measurable
            x = xp["id"]; dx = dt[dt.pid == x]
            if dx.empty: continue
            played, out_g = set(), set()
            for s, ds in dx.groupby("season"):
                lo, hi = ds.gd.min(), ds.gd.max()       # his time on this club that season: first to last box score he is listed in
                games = [g for gd, g in tg.get((t, s), []) if lo <= gd <= hi]
                p_ = set(ds[ds["min"] > 0].game_id)
                played |= p_ & set(games); out_g |= set(games) - p_
            if len(played) < 8 or len(out_g) < 2: continue
            sh = shift("NBA", side, rs, x)
            mates = []
            for yp in rs:
                if yp["id"] == x: continue
                dy = dt[(dt.pid == yp["id"]) & (dt["min"] > 0)]
                wi, wo = dy[dy.game_id.isin(played)], dy[dy.game_id.isin(out_g)]
                if len(wo) < 2 or len(wi) < 3: continue
                row = dict(id=yp["id"], n_in=len(wi), n_out=len(wo))
                for k in ("min", "pts", "reb", "ast"):
                    row[k] = [round(mean(wi[k]), 1), round(mean(wo[k]), 1)]
                e = sh.get(yp["id"])
                row["eng"] = {k: round(e[k], 1) for k in ("min", "pts", "reb", "ast")} if e else None
                mates.append(row)
                if e:
                    pairs.append(dict(w=min(len(wo), 10), obs={k: row[k][1] - row[k][0] for k in ("min", "pts", "reb", "ast")}, eng=e))
            mates.sort(key=lambda r: -abs(r["min"][1] - r["min"][0]))
            if mates: by[x] = dict(n_out=len(out_g), n_in=len(played), mates=mates[:6])
    return dict(by=by, check=score(pairs, ("min", "pts", "reb", "ast")), span="2025-26 and 2026-27 seasons")


# ---------- NFL: 2025 and 2026 seasons, from the weekly stats file ----------
def nfl():
    L = DATA["NFL"]
    w = pd.concat([pd.read_csv(f"{D}nfl_pw_{y}.csv", low_memory=False) for y in (2025, 2026)])
    w = w[w.season_type == "REG"].copy()
    for k in ("targets", "carries", "receiving_yards", "rushing_yards"): w[k] = w[k].fillna(0)
    w = w.rename(columns={"targets": "tgt", "carries": "car", "receiving_yards": "rec_yds", "rushing_yards": "rush_yds"})
    g = pd.read_csv(f"{D}nfl_games.csv", low_memory=False)
    g = g[g.season.isin([2025, 2026]) & (g.game_type == "REG") & g.result.notna()]
    tg = {}
    for r in g.itertuples():
        for t in (r.home_team, r.away_team): tg.setdefault((t, r.season), []).append(r.week)
    roster = {}
    for p in L["players"]: roster.setdefault(p["team"], []).append(p)
    sides = {s["team"]: s for s in L["sides"]}
    by, pairs = {}, []
    for t, rs in roster.items():
        side = sides.get(t)
        if side is None: continue
        wt = w[w.team == t]
        for xp in rs:
            if not (xp["ts"] >= 0.12 or xp["cs"] >= 0.25): continue     # a real share of the targets or the carries
            x = xp["id"]; dx = wt[wt.player_id == x]
            if dx.empty: continue
            played, out_w = set(), set()
            for s, ds in dx.groupby("season"):
                lo, hi = ds.week.min(), ds.week.max()
                wk = [k for k in tg.get((t, s), []) if lo <= k <= hi]
                p_ = set(ds.week)
                played |= {(s, k) for k in p_ & set(wk)}; out_w |= {(s, k) for k in set(wk) - p_}
            if len(played) < 5 or len(out_w) < 1: continue
            sh = shift("NFL", side, rs, x)
            mates = []
            for yp in rs:
                if yp["id"] == x or yp["pos"] == "QB": continue
                dy = wt[wt.player_id == yp["id"]]
                key = list(zip(dy.season, dy.week))
                wi = dy[[k in played for k in key]]; wo = dy[[k in out_w for k in key]]
                if len(wo) < 1 or len(wi) < 3: continue
                row = dict(id=yp["id"], n_in=len(wi), n_out=len(wo))
                for k in ("tgt", "car", "rec_yds", "rush_yds"):
                    row[k] = [round(mean(wi[k]), 1), round(mean(wo[k]), 1)]
                e = sh.get(yp["id"])
                row["eng"] = {k: round(e[k], 1) for k in ("tgt", "car", "rec_yds", "rush_yds")} if e else None
                if max(row["tgt"] + row["car"]) < 1.5: continue
                mates.append(row)
                if e:
                    pairs.append(dict(w=min(len(wo), 6), obs={k: row[k][1] - row[k][0] for k in ("tgt", "car", "rec_yds", "rush_yds")}, eng=e))
            mates.sort(key=lambda r: -abs((r["tgt"][1] - r["tgt"][0]) + (r["car"][1] - r["car"][0])))
            if mates: by[x] = dict(n_out=len(out_w), n_in=len(played), mates=mates[:6])
    return dict(by=by, check=score(pairs, ("tgt", "car", "rec_yds", "rush_yds")), span="2025 and 2026 regular seasons")


def score(pairs, keys):
    """How far the engine's shift lands from what happened, next to assuming nothing changes. Weighted by games missed."""
    out = {"pairs": len(pairs)}
    for k in keys:
        w = np.array([p["w"] for p in pairs], float); o = np.array([p["obs"][k] for p in pairs]); e = np.array([p["eng"][k] for p in pairs])
        if not len(w): continue
        big = (np.abs(o) >= np.quantile(np.abs(o), 0.5)) & (np.abs(e) >= 0.1)     # clear moves the engine also calls
        sign = float(np.average((np.sign(o) == np.sign(e))[big], weights=w[big])) if big.any() else None
        out[k] = dict(mae_engine=round(float(np.average(np.abs(o - e), weights=w)), 2), mae_none=round(float(np.average(np.abs(o), weights=w)), 2),
                      mean_obs=round(float(np.average(o, weights=w)), 2), mean_engine=round(float(np.average(e, weights=w)), 2), n_called=int(big.sum()),
                      corr=round(float(np.corrcoef(o, e)[0, 1]), 2) if len(o) > 2 and np.std(e) > 0 else None, same_way=round(sign, 2) if sign is not None else None)
    return out


if __name__ == "__main__":
    res = {}
    for lg, f in (("NBA", nba), ("NFL", nfl)):
        try:
            res[lg] = f()
            c = res[lg]["check"]
            print(lg, "players with history", len(res[lg]["by"]), "pairs", c["pairs"], {k: v for k, v in c.items() if k != "pairs"})
        except Exception as e:
            print(lg, "with/without failed:", e)
    json.dump(res, open(O + "ww.json", "w"), separators=(",", ":"))

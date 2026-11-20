"""NBA prop model: minutes x per-minute rate, re-balanced inside the team's expected total.
Since v3.50 the points and threes rates are built from shots taken and shooting percentage (the shot build, see SHOT_ON).
Walk-forward: every feature for a game is built only from games played before it."""
import json, os
from collections import defaultdict, deque
import numpy as np, pandas as pd
from common import fit_dispersion, score, norm, load_news, load_lineups

D = "/home/claude/props/data/"
OUT = "/home/claude/props/out/"
BASE = ["pts", "reb", "ast", "fg3"]
COMBO = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
HLM, HLR, HLT = 3.0, 15.0, 10.0
DM, DR, DT = 0.5 ** (1 / HLM), 0.5 ** (1 / HLR), 0.5 ** (1 / HLT)
PM0 = 15.0  # pseudo-minutes of positional prior in each rate
MW0 = 0.05    # pseudo-games of a 14-minute prior in the minutes average
CARRY = 0.6   # weight kept on last season's per-minute rates when a new season starts
# v3.24: the league's starting lineups. A player starting tonight after coming off the bench in his last game plays about
# 21% more than his minutes average says, one back on the bench after starting about 15% less (fitted on 2024-25; scored
# on 2025-26 and 2026-27: points CRPS +3.3% and +6.5%, rebounds +3.1% and +3.5%, assists +2.4% and +3.3% on those players,
# lab lineup_bt.py). Applied to his minutes before the team is rebalanced to 240, so his teammates absorb it.
LINEUP_F = {"promoted": 1.21, "demoted": 0.853}
# v3.50 the shot build: points and threes per minute come from shots taken and shooting percentage, not from recent points.
# Volume (two-point tries, three-point tries, free throw tries per minute) keeps the 15-game memory. Each percentage is pulled
# toward the position's with a prior counted in attempts. Points: 60 twos, 120 threes, 40 free throws, 15-game memory.
# Threes: 240 attempts on a 100-game memory, because a few weeks of three-point shooting says little. Every setting was chosen
# on 2024-25 and scored once on 2025-26 and 2026-27 (lab shot_bt.py): points miss 4.846 to 4.832 (-0.30%), threes 0.981 to
# 0.973 (-0.80%), better in both seasons. The old build over-projected players shooting hot by 2.5% on points and 3.6% on
# threes and under-projected cold ones by 2.1% and 4.5%; this one is within 1.3% in every band. Rebounds and assists unchanged.
SHOT_ON = True      # the lab sets this False to rebuild the old rates for comparison
SHOT = ["a2", "m2", "a3", "m3", "fa", "fm"]
SH_N = dict(p2=60.0, p3=120.0, pf=40.0)
HL3, N3 = 100.0, 240.0
D3 = 0.5 ** (1 / HL3)
ROT_T = 250.0       # live lineup with no news: fill the rotation by minutes to this team total (walk-forward tested, CHANGELOG v1.3)
ROT_T_NEWS = 246.0  # with lineup news. v3.16: replayed 2025-26 as the desk sees it at noon (last game's roster, the official
                    # injury report at noon). Tuned on games to Jan 31: 236 under-projected points by 0.23 a player, 246 by 0.10;
                    # on Feb 1 on, 246 had no bias (-0.01) and a lower points miss (4.868 vs 4.879). Was 236 (CHANGELOG v1.4).


def load():
    d = pd.concat([pd.read_parquet(f"{D}nba_pb_{y}.parquet") for y in (2025, 2026, 2027)])
    d = d[d.season_type.isin([2, 3, 5]) & d.minutes.notna() & (d.minutes > 0)].copy()
    d = d.rename(columns={"points": "pts", "rebounds": "reb", "assists": "ast", "three_point_field_goals_made": "fg3",
                          "athlete_display_name": "name", "team_abbreviation": "team", "opponent_team_abbreviation": "opp",
                          "athlete_position_abbreviation": "posr", "minutes": "min"})
    teams = d[d.season == 2027].team.unique()
    d = d[d.team.isin(teams) & d.opp.isin(teams)]
    d["pos"] = d.posr.map(lambda p: "G" if p in ("PG", "SG", "G") else ("C" if p == "C" else "F"))
    d["gd"] = d.game_date.astype(str)
    d["pid"] = d.athlete_id.astype(str)
    d[BASE] = d[BASE].fillna(0)
    num = lambda c: pd.to_numeric(d[c], errors="coerce").fillna(0)
    d["a3"], d["m3"] = num("three_point_field_goals_attempted"), d["fg3"]
    d["a2"], d["m2"] = (num("field_goals_attempted") - d["a3"]).clip(lower=0), (num("field_goals_made") - d["m3"]).clip(lower=0)
    d["fa"], d["fm"] = num("free_throws_attempted"), num("free_throws_made")
    return d.sort_values(["gd", "game_id"])


class State:
    def __init__(self, pri, lg, spri=None):
        self.pri, self.lg, self.spri = pri, lg, spri
        self.pl = defaultdict(lambda: defaultdict(float))
        self.tm = defaultdict(lambda: defaultdict(float))
        self.last = defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))
        self.ps = {}

    def team_feat(self, t, o):
        T, O, f = self.tm[t], self.tm[o], {}
        for s in BASE:
            off = (T[s] + 3 * self.lg[s]) / (T["g"] + 3)
            de = (O[s + "_a"] + 3 * self.lg[s]) / (O["g"] + 3)
            f["T_" + s] = off * de / self.lg[s]
        return f

    def player_feat(self, pid, pos):
        s = self.pl[pid]
        f = dict(m=(s["mw"] + MW0 * 14.0) / (s["w"] + MW0), n=s["n"])
        for k in BASE:
            f["r_" + k] = (s[k] + PM0 * self.pri[pos][k]) / (s["min"] + PM0)
        if self.spri:      # v3.50 the shot build (see SHOT_ON above)
            P = self.spri[pos]
            v2, v3, vf = ((s[a] + PM0 * P[v]) / (s["min"] + PM0) for v, a in (("v2", "a2"), ("v3", "a3"), ("vf", "fa")))
            p2, p3, pf = ((s[m] + SH_N[k] * P[k]) / (s[a] + SH_N[k]) for k, m, a in (("p2", "m2", "a2"), ("p3", "m3", "a3"), ("pf", "fm", "fa")))
            f["r_pts"] = 2 * v2 * p2 + 3 * v3 * p3 + vf * pf
            f["r_fg3"] = v3 * (s["m3L"] + N3 * P["p3"]) / (s["a3L"] + N3)
        return f

    def shot_view(self, pid, pos, recent):
        """v3.50, for the page only: the parts of the shot build (per 36 minutes and the steadied percentages), the per-minute
        rates the old build would have used, and his shots and shooting over his last 10 and last 60 games (recent = his box
        score rows, oldest first). a/b rows: games, shots a game, threes tried a game, true shooting, three-point percentage."""
        s, P = self.pl[pid], self.spri[pos]
        v2, v3, vf = ((s[a] + PM0 * P[v]) / (s["min"] + PM0) for v, a in (("v2", "a2"), ("v3", "a3"), ("vf", "fa")))
        p2, p3, pf = ((s[m] + SH_N[k] * P[k]) / (s[a] + SH_N[k]) for k, m, a in (("p2", "m2", "a2"), ("p3", "m3", "a3"), ("pf", "fm", "fa")))
        p3L = (s["m3L"] + N3 * P["p3"]) / (s["a3L"] + N3)

        def cut(z):
            n = len(z)
            if not n: return None
            fga, a3, fa, pts, m3 = (float(z[c].sum()) for c in ("a2", "a3", "fa", "pts", "m3")); fga += a3
            den = 2 * (fga + 0.44 * fa)
            return [n, round(fga / n, 1), round(a3 / n, 1), round(pts / den, 3) if den > 0 else None, round(m3 / a3, 3) if a3 >= 10 else None]
        return dict(v=[round(36 * (v2 + v3), 1), round(36 * v3, 1), round(36 * vf, 1)], p=[round(p2, 3), round(p3, 3), round(pf, 3), round(p3L, 3)],
                    r0=[round((s[k] + PM0 * self.pri[pos][k]) / (s["min"] + PM0), 5) for k in ("pts", "fg3")], a=cut(recent.tail(10)), b=cut(recent))

    def update(self, season, t, o, rows):
        T, O = self.tm[t], self.tm[o]
        for k in BASE + ["g"]:
            T[k] *= DT
        for k in [b + "_a" for b in BASE]:
            O[k] *= DT
        T["g"] += 1
        for k in BASE:
            tot = sum(r[k] for r in rows)
            T[k] += tot; O[k + "_a"] += tot
        for r in rows:
            pid = r["pid"]; s = self.pl[pid]
            if self.ps.get(pid, season) != season:
                s["mw"] *= 0.35; s["w"] *= 0.35
                for k in BASE + ["min"] + SHOT + ["a3L", "m3L"]:
                    s[k] *= CARRY
            self.ps[pid] = season
            s["mw"] *= DM; s["w"] *= DM
            for k in BASE + ["min"] + SHOT:
                s[k] *= DR
            s["a3L"] *= D3; s["m3L"] *= D3
            s["mw"] += r["min"]; s["w"] += 1; s["min"] += r["min"]; s["n"] += 1
            for k in BASE + SHOT:
                s[k] += r[k]
            s["a3L"] += r["a3"]; s["m3L"] += r["m3"]
            L = self.last[pid]
            for k in BASE + ["min"]:
                L[k].append(float(r[k]))
            L["meta"].append((r["gd"], o)); L["team"].append(t); L["start"].append(bool(r["starter"]))


def walk(d):
    tr0 = d[d.season == 2025]
    pri = {p: {k: x[k].sum() / x["min"].sum() for k in BASE} for p, x in tr0.groupby("pos")}
    lg = {k: float(tr0.groupby(["game_id", "team"])[k].sum().mean()) for k in BASE}
    tot = lambda x, c: float(x[c].sum())
    spri = {p: dict(v2=tot(x, "a2") / tot(x, "min"), v3=tot(x, "a3") / tot(x, "min"), vf=tot(x, "fa") / tot(x, "min"),
                    p2=tot(x, "m2") / tot(x, "a2"), p3=tot(x, "m3") / tot(x, "a3"), pf=tot(x, "fm") / tot(x, "fa")) for p, x in tr0.groupby("pos")}
    S = State(pri, lg, spri if SHOT_ON else None)
    prow, trow = [], []
    keep = ["pid", "name", "pos", "min", "starter", "gd"] + BASE + SHOT
    for gid, gdf in d.groupby("game_id", sort=False):
        sides = [(t, x.opp.iloc[0], x[keep].to_dict("records")) for t, x in gdf.groupby("team")]
        for t, o, rows in sides:
            tf = S.team_feat(t, o)
            trow.append(dict(game_id=gid, team=t, opp=o, **tf))
            for r in rows:
                pf = S.player_feat(r["pid"], r["pos"])
                L = S.last[r["pid"]]
                l5 = {"l5_" + k: (float(np.mean(list(L[k])[-5:])) if L[k] else np.nan) for k in BASE}
                prow.append(dict(game_id=gid, team=t, opp=o, season=int(gdf.season.iloc[0]), gd=r["gd"], pid=r["pid"], name=r["name"],
                                 pos=r["pos"], **pf, **l5, y_min=r["min"], **{k: r[k] for k in BASE}))
        season = int(gdf.season.iloc[0])
        for t, o, rows in sides:
            S.update(season, t, o, rows)
    pr, tr = pd.DataFrame(prow), pd.DataFrame(trow)
    for c, parts in COMBO.items():
        pr[c] = pr[parts].sum(axis=1); pr["l5_" + c] = pr[["l5_" + p for p in parts]].sum(axis=1, min_count=len(parts))
    return pr, tr, S


def project(pr, tr, M):
    d = pr.merge(tr, on=["game_id", "team"], suffixes=("", "_t"))
    g = d.groupby(["game_id", "team"])
    # re-balance to 240 team minutes: a surplus is trimmed pro rata, a shortfall goes mostly
    # to players with headroom so a 37-minute star is not pushed to 44
    tot = g.m.transform("sum")
    w = d.m * np.maximum(38.0 - d.m, 0.5)
    up = d.m + (240.0 - tot) * w / w.groupby([d.game_id, d.team]).transform("sum")
    d["mn"] = np.minimum(d.m + M["bm"] * (np.where(tot < 240, up, d.m * 240.0 / tot) - d.m), 40.0)
    for k in BASE:
        raw = d.mn * d["r_" + k]
        d["mu_" + k] = raw * (d["T_" + k] / raw.groupby([d.game_id, d.team]).transform("sum")) ** M["bs"][k] * M["cal"].get(k, 1.0)
        if "lin" in M:   # slope correction: the raw build-up is a little too timid about stars and too kind to the bench
            d["mu_" + k] = np.maximum(M["lin"][k][0] + M["lin"][k][1] * d["mu_" + k], 0.05)
    for c, parts in COMBO.items():
        d["mu_" + c] = d[["mu_" + p for p in parts]].sum(axis=1)
    return d


def main():
    d = load()
    pr, tr, S = walk(d)
    first = pr[pr.season == 2025].gd.min()
    warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
    is_tr, is_te = warm & (pr.season == 2025), pr.season >= 2026
    M = {"bm": 0.8, "bs": {k: 0.5 for k in BASE}, "cal": {}}

    def mae(dd, k):
        mm = dd.mn >= 15
        return np.abs(dd.loc[mm, k] - dd.loc[mm, "mu_" + k]).mean()

    best = None
    for bm in (0.0, 0.5, 0.8, 1.0):
        M["bm"] = bm
        dd = project(pr[is_tr], tr, M)
        e = np.abs(dd.y_min - dd.mn).mean()
        print("bm", bm, round(e, 3))
        if best is None or e < best[0]:
            best = (e, bm)
    M["bm"] = best[1]
    for k in BASE:
        best = None
        for bs in (0.0, 0.25, 0.5, 0.75, 1.0):
            M["bs"][k] = bs
            e = mae(project(pr[is_tr], tr, M), k)
            if best is None or e < best[0]:
                best = (e, bs)
        M["bs"][k] = best[1]
    print("tuned", M)

    def finish(mask):
        m = dict(bm=M["bm"], bs=dict(M["bs"]), cal={})
        dd = project(pr[mask], tr, m); mm = dd.mn >= 15
        m["cal"] = {k: float(dd.loc[mm, k].sum() / dd.loc[mm, "mu_" + k].sum()) for k in BASE}
        dd = project(pr[mask], tr, m); mm = dd.mn >= 15
        m["lin"] = {k: [float(v) for v in np.polyfit(dd.loc[mm, "mu_" + k], dd.loc[mm, k], 1)[::-1]] for k in BASE}
        dd = project(pr[mask], tr, m); mm = dd.mn >= 15
        m["disp"] = {k: fit_dispersion(dd.loc[mm, "mu_" + k], dd.loc[mm, k]) for k in BASE + list(COMBO)}
        return m

    m_tr = finish(is_tr)
    te = project(pr[is_te], tr, m_tr); mm = te.mn >= 15
    rng = np.random.default_rng(11)
    bt = {}
    for k in BASE + list(COMBO):
        a, b = m_tr["disp"][k]
        sc = score(te.loc[mm, "mu_" + k], te.loc[mm, k], a, b, rng)
        l5 = te.loc[mm, "l5_" + k]; ok = l5.notna()
        sc["mae_model_vs_l5"] = [float(np.abs(te.loc[mm, k][ok] - te.loc[mm, "mu_" + k][ok]).mean()), float(np.abs(te.loc[mm, k][ok] - l5[ok]).mean())]
        bt[k] = sc
        print(k, sc["n"], "MAE", round(sc["mae_model_vs_l5"][0], 2), "vs L5", round(sc["mae_model_vs_l5"][1], 2), "cover80", round(sc["cover80"], 3),
              "bias", round(sc["bias"], 2), "brier", round(sc["brier"], 4), [(round(r["pred"], 2), round(r["obs"], 2)) for r in sc["reliability"]])
    bt["minutes"] = dict(mae=float(np.abs(te.y_min - te.mn)[mm].mean()))
    print("minutes MAE", bt["minutes"])

    MF = finish(warm)

    # ---------- upcoming slate ----------
    sch = pd.read_parquet(D + "nba_sched_2027.parquet")
    sch["gd"] = sch.game_date.astype(str)
    last_gd = d.gd.max()
    up = sch[(sch.gd > last_gd) & (sch.status_type_name == "STATUS_SCHEDULED")].sort_values("game_date_time")
    days = sorted(up.gd.unique())[:3]
    up = up[up.gd.isin(days)]
    cur = d[d.season == 2027]
    recent = {pid: x.tail(60) for pid, x in d.groupby("pid")} if SHOT_ON else {}      # v3.50: shots and shooting for the page
    news = load_news("NBA", days[:1])     # only news dated the first slate day counts
    LU = load_lineups("NBA", days[0]) if days else {}      # v3.24: the league's starting fives, first slate day only
    LUF = {}
    print("starting lineups:", f"{len(LU)} teams ({sum(v['confirmed'] for v in LU.values())} confirmed)" if LU else "none posted yet")
    print("lineup news:", "on, %d out, %d questionable, %d with a book line" % (len(news["out"]), len(news["q"]), len(news["inn"])) if news["on"] else "none for " + (days[0] if days else "?") + ", lineup is whoever played last game")
    games, sides, prow, trow, players, seen = [], [], [], [], {}, set()
    for r in up.itertuples():
        gid = str(r.game_id)
        games.append(dict(id=gid, day=r.gd, time=pd.Timestamp(r.game_date_time).strftime("%H:%M"), away=r.away_abbreviation, home=r.home_abbreviation))
        for t, o, h in ((r.home_abbreviation, r.away_abbreviation, 1), (r.away_abbreviation, r.home_abbreviation, 0)):
            tf = S.team_feat(t, o)
            trow.append(dict(game_id=gid, team=t, opp=o, **tf))
            # oppf: what the opponent allows next to the league average (1.04 = 4% more). Only used for the pick write-ups.
            oppf = {k: round(((S.tm[o][k + "_a"] + 3 * S.lg[k]) / (S.tm[o]["g"] + 3)) / S.lg[k], 3) for k in BASE}
            sides.append(dict(game=gid, team=t, opp=o, home=h, T={k: round(tf["T_" + k], 3) for k in BASE}, oppf=oppf))
            tg = cur[cur.team == t]
            gids = list(dict.fromkeys(tg.game_id))[-5:]
            cand = tg[tg.game_id.isin(gids)].drop_duplicates("pid", keep="last")
            played_last = set(tg[tg.game_id == gids[-1]].pid)
            played_prev = set(tg[tg.game_id == gids[-2]].pid) if len(gids) > 1 else played_last
            pool = []
            for x in cand.itertuples():
                L = S.last[x.pid]
                if list(L["team"])[-1] != t:
                    continue
                pf = S.player_feat(x.pid, x.pos)
                # Lineup: default is whoever played the team's last game. Today's news overrides it:
                # ruled out -> sits; the book is offering a line on him -> plays (covers a star back from a rest night).
                nm = norm(x.name)
                active = x.pid in played_last
                if nm in news["out"]: active = False
                elif nm in news["inn"]: active = True
                # one night off is rest, not a role question; two straight absences is
                missed = (x.pid not in played_last) and ((x.pid not in played_prev) or not news["on"])
                lu = None
                if x.pid in LUF and r.gd != days[0]: pf = dict(pf, m=pf["m"] * LUF[x.pid])      # a role change tonight carries to tomorrow (the page uses one number a player)
                if t in LU and r.gd == days[0]:      # v3.24: the starting five the league lists for tonight
                    T5 = LU[t]
                    if nm in T5["inactive"]: active = False
                    elif nm in T5["start"]:
                        active, lu = True, "S"
                        if not list(L["start"])[-1]: pf = dict(pf, m=pf["m"] * LINEUP_F["promoted"]); LUF[x.pid] = LINEUP_F["promoted"]
                    elif active:
                        lu = "B"
                        if list(L["start"])[-1]: pf = dict(pf, m=pf["m"] * LINEUP_F["demoted"]); LUF[x.pid] = LINEUP_F["demoted"]
                pool.append([x, L, pf, nm, active, missed, lu])
            # Rotation fill: after a blowout or a rest night the last box score lists 12 to 14 players. Keeping them all
            # squeezes the starters' minutes. Fill by minutes until the team total reaches ROT_T; the deep bench sits.
            cum = 0.0
            for z in sorted([z for z in pool if z[4]], key=lambda z: (z[6] != "S", -z[2]["m"])):      # a listed starter always plays
                if cum >= (ROT_T_NEWS if news["on"] else ROT_T) and z[3] not in news["inn"] and z[6] != "S":
                    z[4] = False
                else:
                    cum += z[2]["m"]
            for x, L, pf, nm, active, missed, lu in pool:
                if active:
                    prow.append(dict(game_id=gid, team=t, opp=o, pid=x.pid, name=x.name, pos=x.pos, **pf))
                if x.pid in seen:
                    continue
                seen.add(x.pid)
                k = len(L["meta"])
                logs = dict(d=[m[0][5:] for m in L["meta"]], opp=[m[1] for m in L["meta"]], min=[int(v) for v in L["min"]],
                            **{b: [int(v) for v in L[b]] for b in BASE})
                players[x.pid] = dict(id=x.pid, name=x.name, pos=x.posr, grp=x.pos, team=t, active=bool(active), missed=bool(missed), q=bool(nm in news["q"]),
                                      n=int(pf["n"]), m=round(pf["m"], 3), start=bool(list(L["start"])[-1]),
                                      **({"lu": lu, "luc": bool(LU[t]["confirmed"])} if lu else {}),
                                      r={b: round(pf["r_" + b], 5) for b in BASE}, logs=logs,
                                      **({"sh": S.shot_view(x.pid, x.pos, recent[x.pid])} if SHOT_ON and x.pid in recent else {}))
    upr, utr = pd.DataFrame(prow), pd.DataFrame(trow)
    proj = project(upr, utr, MF)
    check = {f"{r.game_id}|{r.pid}": {k: round(float(getattr(r, "mu_" + k)), 4) for k in BASE + list(COMBO)} | {"mn": round(float(r.mn), 4)} for r in proj.itertuples()}
    out = dict(league="NBA", label=" / ".join(x[5:] for x in days), data_through=last_gd, games=games, sides=sides, players=list(players.values()),
               model=dict(bm=MF["bm"], bs=MF["bs"], cal=MF["cal"], lin=MF["lin"], disp={k: list(v) for k, v in MF["disp"].items()}),
               backtest=bt, backtest_note="Fit on the 2024-25 season, scored on 2025-26 and 2026-27 games it never saw. These scores know who played each night; replayed with only the noon injury report, the points miss was 4.87 against 4.71 here and minutes 5.01 against 4.64.")
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(OUT + "nba.json", "w")); json.dump(check, open(OUT + "nba_check.json", "w"))
    print("lin", {k: [round(z, 3) for z in v] for k, v in MF["lin"].items()})
    hb = te[mm & (te.mu_pts >= 20)]; lb = te[mm & (te.mu_pts < 10)]
    print("test bias pts: proj 20+ %+.2f (n%d), proj under 10 %+.2f" % ((hb.pts - hb.mu_pts).mean(), len(hb), (lb.pts - lb.mu_pts).mean()))
    print("players", len(players), "games", len(games), "cal", {k: round(v, 3) for k, v in MF["cal"].items()})
    print("disp", {k: [round(z, 2) for z in v] for k, v in MF["disp"].items()})
    print(proj.sort_values("mu_pts", ascending=False).head(12)[["name", "team", "opp", "mn", "mu_pts", "mu_reb", "mu_ast", "mu_fg3"]].round(1).to_string())


if __name__ == "__main__":
    main()

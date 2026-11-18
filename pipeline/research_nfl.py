#!/usr/bin/env python3
"""NFL research tables for the Research tab. Everything here comes from free files:
nflverse play-by-play, weekly player stats, snap counts, weekly rosters, injury reports, FTN charting flags and
Pro Football Reference advanced stats. Writes out/research/nfl.json (published beside the page as research/nfl.json).

Definitions worth knowing (they are printed on the page too):
  role        this week: rank by average offensive snap share over the team's last five games, active players only.
              what a defense allows: who filled the role by snap share on the day.
  rank        on anything a defense allows, rank 1 allows the most (softest). On the defense board, rank 1 is the best defense.
  red zone    plays that start at or inside the 20. A look is a carry or a target.
  early       a team's first two offensive drives of a game.
Run after the downloads in run.sh. Nothing here feeds the pricing model or the pick policy."""
import json, datetime, sys, os
from zoneinfo import ZoneInfo      # v3.19: real Eastern time (a fixed UTC-5 was an hour off in daylight time)
import numpy as np, pandas as pd
from common import norm

DATA, O = "/home/claude/props/data/", "/home/claude/props/out/"
SEASON = 2026
NICK = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
        "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
        "LA": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
        "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders"}
ROLE_N = {"WR": 3, "TE": 2, "RB": 2, "QB": 1}
r1 = lambda x, d=1: None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def rank_desc(s):          # 1 = largest value
    return s.rank(ascending=False, method="min").astype(int)


def shrink(x, n, prior, k):
    return (x * n + prior * k) / (n + k)


def main(today=None):
    today = today or datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    # ---------------- load ----------------
    pbp = pd.read_parquet(DATA + "nfl_play_by_play_2026.parquet")
    pbp = pbp[pbp.season_type == "REG"].copy()
    pw = pd.read_csv(DATA + "nfl_pw_2026.csv", low_memory=False)
    pw = pw[pw.season_type == "REG"].copy()
    snaps = pd.read_csv(DATA + "nfl_snaps_2026.csv")
    snaps = snaps[snaps.game_type == "REG"]
    players = pd.read_parquet(DATA + "nfl_players.parquet", columns=["gsis_id", "pfr_id", "display_name", "position"])
    ros = pd.read_parquet(DATA + "nfl_roster_weekly_2026.parquet", columns=["team", "position", "status", "full_name", "gsis_id", "week", "game_type"])
    inj = pd.read_parquet(DATA + "nfl_injuries_2026.parquet")
    games = pd.read_csv(DATA + "nfl_games.csv"); games = games[(games.season == SEASON) & (games.game_type == "REG")].copy()
    thru = int(pbp.week.max())
    done = games[games.home_score.notna()]
    gp_team = pd.concat([done.home_team, done.away_team]).value_counts().to_dict()
    teams = sorted(gp_team)
    up = games[(games.home_score.isna()) & (games.gameday >= today)].sort_values(["gameday", "gametime"])
    up = up[up.week <= up.week.min() + 1] if len(up) else up
    next_game = {}
    for g in up.itertuples():
        for t, o, h in ((g.home_team, g.away_team, 1), (g.away_team, g.home_team, 0)):
            next_game.setdefault(t, dict(opp=o, home=h, week=int(g.week), id=g.game_id, day=g.gameday, time=g.gametime))

    # ---------------- player identity and status ----------------
    pfr2g = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id.to_dict()
    snaps = snaps.assign(pid=snaps.pfr_player_id.map(pfr2g))
    last_row = pw.sort_values("week").groupby("player_id").tail(1).set_index("player_id")
    name = last_row.player_display_name.to_dict(); pos = last_row.position.to_dict()
    # the snap file labels some backs HB and some receivers by slot; the stat file's position is the one used everywhere else
    snaps["position"] = snaps.pid.map(pos).fillna(snaps.position.replace({"HB": "RB"}))
    rl = ros[ros.game_type == "REG"].sort_values("week").groupby("gsis_id").tail(1).set_index("gsis_id")
    cur_team = rl.team.to_dict(); rstatus = rl.status.to_dict()
    for pid, t in last_row.team.items():
        cur_team.setdefault(pid, t)
    iw = int(inj.week.max()) if len(inj) else -1
    inj_now = inj[inj.week == iw].set_index("gsis_id").report_status.to_dict() if len(inj) else {}
    try:      # game-day downgrades from the desk's own news pull, when it is dated today
        nw = json.load(open(O + "news.json")).get("NFL", {}); news_out = set(nw.get("out", [])) if nw.get("date") == today else set()
    except Exception:
        news_out = set()
    dc = pd.read_parquet(DATA + "nfl_depth_charts_2026.parquet", columns=["dt", "team", "gsis_id", "pos_abb", "pos_rank"])
    dc = dc[dc.dt == dc.groupby("team").dt.transform("max")]
    qb1 = dc[(dc.pos_abb == "QB") & (dc.pos_rank == 1)].drop_duplicates("team").set_index("team").gsis_id.to_dict()

    def status(pid):
        t = cur_team.get(pid); ng = next_game.get(t)
        if rstatus.get(pid) in ("RES", "RET", "CUT", "EXE"):
            return "IR" if rstatus.get(pid) == "RES" else "OFF"
        if ng and ng["week"] == iw and norm(name.get(pid, "")) in news_out:
            return "OUT"
        if ng and ng["week"] == iw and isinstance(inj_now.get(pid), str):       # this week's report covers his next game
            return {"Out": "OUT", "Doubtful": "D", "Questionable": "Q"}.get(inj_now[pid], "")
        return ""

    # ---------------- per-game player lines ----------------
    num = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries", "rushing_yards", "rushing_tds",
           "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_air_yards"]
    pw[num] = pw[num].fillna(0)
    pw["grp"] = pw.position.where(pw.position.isin(["QB", "RB", "WR", "TE"]))
    pw["td"] = pw.rushing_tds + pw.receiving_tds
    gp = pw.groupby("player_id").game_id.nunique().to_dict()

    # ---------------- roles ----------------
    sn = snaps[(snaps.offense_snaps > 0) & snaps.pid.notna() & snaps.position.isin(["QB", "RB", "WR", "TE"])].copy()
    # WR and TE roles follow snaps. RB roles follow the ball (carries + targets), QB the pass attempts; snaps break ties.
    use = pw.assign(o=pw.carries.fillna(0) + pw.targets.fillna(0), a=pw.attempts.fillna(0))[["game_id", "player_id", "o", "a"]].rename(columns={"player_id": "pid"})
    sn = sn.merge(use, on=["game_id", "pid"], how="left").fillna({"o": 0, "a": 0})
    sn["m"] = np.where(sn.position == "RB", sn.o + sn.offense_pct, np.where(sn.position == "QB", sn.a + sn.offense_pct, sn.offense_pct))
    sn["rk"] = sn.groupby(["game_id", "team", "position"]).m.rank(ascending=False, method="first")
    sn["role"] = [f"{p}{int(k)}" if k <= ROLE_N[p] else None for p, k in zip(sn.position, sn.rk)]
    sn.loc[sn.position == "QB", "role"] = np.where(sn[sn.position == "QB"].rk == 1, "QB", None)
    day_role = sn.dropna(subset=["role"]).set_index(["game_id", "pid"]).role.to_dict()          # who filled the role on the day
    wk_of = games.set_index("game_id").week.to_dict()
    sn["week"] = sn.game_id.map(wk_of)
    cur_role, snap_share = {}, {}
    for t in teams:
        x = sn[sn.team == t]; last5 = sorted(x.week.unique())[-5:]
        x = x[x.week.isin(last5)]
        avg = x.groupby(["pid", "position"])[["offense_pct", "m"]].mean().reset_index()
        avg = avg[[cur_team.get(p) == t for p in avg.pid]]
        for p, s in zip(avg.pid, avg.offense_pct):
            snap_share[p] = float(s)
        ok = avg[[status(p) not in ("IR", "OFF", "OUT", "D") for p in avg.pid]]
        for ps, n in ROLE_N.items():
            z = ok[ok.position == ps].sort_values("m", ascending=False).head(n)
            for i, p in enumerate(z.pid):
                cur_role[p] = "QB" if ps == "QB" else f"{ps}{i + 1}"
        q = qb1.get(t)        # the depth chart names this week's quarterback, even one who has not played for the team yet
        if q and cur_team.get(q, t) == t and status(q) not in ("IR", "OFF", "OUT", "D"):
            for p in [p for p, r in cur_role.items() if r == "QB" and cur_team.get(p) == t]:
                del cur_role[p]
            cur_role[q] = "QB"; cur_team[q] = t

    # ---------------- what each defense allows, by role and by position ----------------
    pw["role"] = [day_role.get((g, p)) for g, p in zip(pw.game_id, pw.player_id)]
    STAT = dict(tgt="targets", rec="receptions", ryd="receiving_yards", rtd="receiving_tds", car="carries", ruyd="rushing_yards", rutd="rushing_tds",
                att="attempts", cmp="completions", pyd="passing_yards", ptd="passing_tds", int="passing_interceptions", td="td")
    allow, lg_role = {t: {} for t in teams}, {}
    def allowed(mask, key):
        x = pw[mask].groupby("opponent_team")[list(STAT.values())].sum()
        x = x.reindex(teams).fillna(0)
        x = x.div(pd.Series(gp_team).reindex(teams), axis=0)
        lg_role[key] = {k: r1(x[c].mean(), 3) for k, c in STAT.items()}
        rk = {k: rank_desc(x[c]) for k, c in STAT.items()}
        for t in teams:
            allow[t][key] = {k: [r1(x.loc[t, c], 2), int(rk[k][t])] for k, c in STAT.items()}
    for role in ("QB", "WR1", "WR2", "WR3", "TE1", "TE2", "RB1", "RB2"):
        allowed(pw.role == role, role)
    for g in ("WR", "TE", "RB"):
        allowed(pw.grp == g, g)
    allowed(pw.grp == "QB", "QBs")

    # ---------------- play subsets ----------------
    pbp["is_run"] = (pbp.play_type == "run") & (pbp.qb_kneel != 1) & (pbp.two_point_attempt != 1)
    pbp["is_tgt"] = (pbp.play_type == "pass") & (pbp.sack != 1) & pbp.receiver_player_id.notna() & (pbp.two_point_attempt != 1)
    pbp["is_att"] = (pbp.play_type == "pass") & (pbp.sack != 1) & (pbp.qb_spike != 1) & (pbp.two_point_attempt != 1)
    pbp["is_db"] = (pbp.play_type == "pass") & (pbp.qb_spike != 1) & (pbp.two_point_attempt != 1) | ((pbp.play_type == "run") & (pbp.qb_scramble == 1))
    pbp["scrim"] = (pbp.is_run | (pbp.play_type == "pass")) & (pbp.two_point_attempt != 1) & (pbp.qb_spike != 1)
    pbp["off_td"] = (pbp.touchdown == 1) & (pbp.td_team == pbp.posteam) & ((pbp.rush_touchdown == 1) | (pbp.pass_touchdown == 1))
    pbp["who"] = np.where(pbp.is_run, pbp.rusher_player_id, np.where(pbp.is_tgt, pbp.receiver_player_id, None))
    looks = pbp[pbp.is_run | pbp.is_tgt].copy()
    played = pw.groupby("player_id").game_id.apply(set).to_dict()

    # ---------------- red zone ----------------
    rz = looks[looks.yardline_100 <= 20]
    rz_pl = rz.groupby("who").agg(looks=("who", "size"), car=("is_run", "sum"), tgt=("is_tgt", "sum")).astype(int)
    rz_td = pbp[pbp.off_td & (pbp.yardline_100 <= 20)].groupby("td_player_id").size()
    rz_tg = rz.groupby(["posteam", "game_id"]).size()
    rzp = pbp[(pbp.yardline_100 <= 20) & pbp.posteam.notna() & pbp.play_type.isin(["run", "pass", "field_goal", "qb_kneel", "qb_spike"])]
    trips = rzp.groupby(["game_id", "posteam", "defteam", "fixed_drive"]).off_td.max().reset_index()
    o_tr = trips.groupby("posteam").agg(n=("off_td", "size"), td=("off_td", "sum")); d_tr = trips.groupby("defteam").agg(n=("off_td", "size"), td=("off_td", "sum"))
    lg_rzr = trips.off_td.mean()
    rz_team = {t: dict(trips=r1(o_tr.n.get(t, 0) / gp_team[t], 2), tdr=r1(o_tr.td.get(t, 0) / max(o_tr.n.get(t, 0), 1), 3),
                       looks=r1(rz_tg.get(t, pd.Series(dtype=float)).sum() / gp_team[t], 1)) for t in teams}
    d_rate = pd.Series({t: d_tr.td.get(t, 0) / max(d_tr.n.get(t, 0), 1) for t in teams}); d_rk = rank_desc(d_rate)
    rz_def = {t: dict(tdr=r1(d_rate[t], 3), rk=int(d_rk[t]), trips=r1(d_tr.n.get(t, 0) / gp_team[t], 2), n=int(d_tr.n.get(t, 0))) for t in teams}

    def share_in_games(pid, per_tg, total):
        """player's total over the team's total in the games he played"""
        t = cur_team.get(pid); gs = played.get(pid, set())
        den = sum(per_tg.get((t, g), 0) for g in gs)
        return (total / den) if den else 0.0
    rz_tg_d = rz_tg.to_dict()

    # ---------------- first touchdown, early drives ----------------
    pbp = pbp.sort_values(["game_id", "order_sequence"])
    ftd = pbp[pbp.off_td].groupby("game_id").head(1)
    first_td = ftd.td_player_id.value_counts().to_dict()
    td_games = pbp[pbp.off_td].groupby("td_player_id").game_id.nunique().to_dict()
    dr = pbp[pbp.scrim & pbp.posteam.notna()].groupby(["game_id", "posteam", "defteam", "fixed_drive"]).off_td.max().reset_index()
    dr["k"] = dr.groupby(["game_id", "posteam"]).fixed_drive.rank(method="first")
    early = dr[dr.k <= 2]
    e_off = early.groupby("posteam").off_td.agg(["mean", "size"]); e_def = early.groupby("defteam").off_td.agg(["mean", "size"])
    lg_e = float(early.off_td.mean())
    e_ork = rank_desc(e_off["mean"].reindex(teams).fillna(0)); e_drk = rank_desc(e_def["mean"].reindex(teams).fillna(0))
    ek = set(zip(early.game_id, early.posteam, early.fixed_drive))
    el = looks[[(g, p, d) in ek for g, p, d in zip(looks.game_id, looks.posteam, looks.fixed_drive)]]
    e_pl = el.groupby("who").size().to_dict(); e_tg = el.groupby(["posteam", "game_id"]).size().to_dict()

    # ---------------- run direction ----------------
    runs = pbp[pbp.is_run & (pbp.qb_scramble != 1) & pbp.run_location.notna()]
    LOC = ["left", "middle", "right"]
    dloc = runs.groupby(["defteam", "run_location"]).agg(n=("yards_gained", "size"), y=("yards_gained", "sum"), s=("success", "mean")).reset_index()
    lg_loc = runs.groupby("run_location").yards_gained.mean().to_dict()
    dloc["ypc"] = [shrink(y / n, n, lg_loc[l], 20) for y, n, l in zip(dloc.y, dloc.n, dloc.run_location)]
    dloc["rk"] = dloc.groupby("run_location").ypc.rank(ascending=False, method="min").astype(int)
    run_def = {t: {} for t in teams}
    for x in dloc.itertuples():
        run_def[x.defteam][x.run_location] = [r1(x.y / x.n, 2), int(x.rk), int(x.n), r1(x.s, 3)]
    ploc = runs.groupby(["rusher_player_id", "run_location"]).agg(n=("yards_gained", "size"), y=("yards_gained", "sum")).unstack(fill_value=0)
    car_tg = pbp[pbp.is_run].groupby(["posteam", "game_id"]).size().to_dict()
    car_pl = pbp[pbp.is_run].groupby("rusher_player_id").size().to_dict()

    # ---------------- shares by period ----------------
    looks["per"] = looks.qtr.clip(upper=4).astype(int)
    looks["rzl"] = (looks.yardline_100 <= 20).astype(int)
    looks["ry"] = np.where(looks.is_tgt, looks.receiving_yards.fillna(0), 0.0); looks["ay"] = np.where(looks.is_tgt, looks.air_yards.fillna(0), 0.0)
    looks["ruy"] = np.where(looks.is_run, looks.rushing_yards.fillna(looks.yards_gained).fillna(0), 0.0); looks["cp"] = np.where(looks.is_tgt, looks.complete_pass.fillna(0), 0)
    agg = dict(tgt=("is_tgt", "sum"), rec=("cp", "sum"), ryd=("ry", "sum"), air=("ay", "sum"), car=("is_run", "sum"), ruyd=("ruy", "sum"), rz=("rzl", "sum"))
    pq = looks.groupby(["who", "game_id", "per"]).agg(**agg).reset_index()
    tq = looks.groupby(["posteam", "game_id", "per"]).agg(**agg).reset_index()
    PER = {"Full": [1, 2, 3, 4], "1H": [1, 2], "2H": [3, 4], "Q1": [1], "Q2": [2], "Q3": [3], "Q4": [4]}
    tot = pq.groupby("who")[["tgt", "car"]].sum()
    keep = set(tot[(tot.tgt + tot.car) >= 10].index)
    tq_i = {k: v for k, v in tq.groupby(["posteam", "per"])}
    share = {}
    for pid, x in pq[pq.who.isin(keep)].groupby("who"):
        t = cur_team.get(pid); gs = played.get(pid, set()); n = max(len(gs), 1); row = {}
        for pn, qs in PER.items():
            a = x[x.per.isin(qs)][list(agg)].sum()
            tm = pd.concat([tq_i[(t, q)] for q in qs if (t, q) in tq_i]) if t else None
            tm = tm[tm.game_id.isin(gs)][list(agg)].sum() if tm is not None and len(tm) else None
            sh = lambda k: max(0.0, r1(100 * a[k] / tm[k], 1)) if tm is not None and tm[k] > 0 else 0.0
            row[pn] = [r1(a.tgt / n, 1), sh("tgt"), r1(a.rec / n, 1), r1(a.ryd / n, 1), sh("air"), r1(a.car / n, 1), sh("car"), r1(a.ruyd / n, 1), sh("rz")]
        share[pid] = row

    # ---------------- team boards ----------------
    ftn = pd.read_parquet(DATA + "nfl_ftn_charting_2026.parquet")
    ftn = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})[["game_id", "play_id", "is_play_action", "is_motion", "is_screen_pass", "is_rpo", "n_blitzers", "n_defense_box"]]
    pb = pbp.merge(ftn, on=["game_id", "play_id"], how="left")
    sc = pb[pb.scrim & pb.posteam.notna()].copy()
    sc["expl"] = np.where(sc.play_type == "pass", sc.yards_gained >= 20, sc.yards_gained >= 10)
    sc["stuff"] = sc.is_run & (sc.yards_gained <= 0)
    sc["neutral"] = sc.down.isin([1, 2]) & sc.wp.between(.2, .8) & (sc.half_seconds_remaining > 120)
    sc["is_pass_play"] = (sc.play_type == "pass") | (sc.qb_scramble == 1)
    pfp = pd.read_parquet(DATA + "nfl_advstats_week_pass_2026.parquet"); pfr = pd.read_parquet(DATA + "nfl_advstats_week_rush_2026.parquet"); pfd = pd.read_parquet(DATA + "nfl_advstats_week_def_2026.parquet")
    for z in (pfp, pfr, pfd):
        z.drop(z[z.game_type != "REG"].index, inplace=True)
    pts_for = {t: (done[done.home_team == t].home_score.sum() + done[done.away_team == t].away_score.sum()) / gp_team[t] for t in teams}
    pts_ag = {t: (done[done.home_team == t].away_score.sum() + done[done.away_team == t].home_score.sum()) / gp_team[t] for t in teams}
    drv = pbp.dropna(subset=["drive_time_of_possession"]).drop_duplicates(["game_id", "posteam", "fixed_drive"])
    drv = drv.assign(sec=[int(a) * 60 + int(b) for a, b in (str(s).split(":")[:2] for s in drv.drive_time_of_possession)])
    top = drv.groupby("posteam").sec.sum()
    pen = pbp[(pbp.penalty == 1) & pbp.penalty_team.notna()]

    def board(side):
        k = "posteam" if side == "off" else "defteam"; o = "defteam" if side == "off" else "posteam"
        g = sc.groupby(k); P = sc[sc.play_type == "pass"]; A = sc[sc.is_att]; Rn = sc[sc.is_run]; D = sc[sc.is_db]
        out = pd.DataFrame(index=teams)
        out["pts"] = pd.Series(pts_for if side == "off" else pts_ag)
        out["epa"] = g.epa.mean(); out["succ"] = 100 * g.success.mean(); out["ypp"] = g.yards_gained.mean(); out["expl"] = 100 * g.expl.mean()
        t3 = sc[sc.down == 3].groupby(k); out["third"] = 100 * t3.first_down.mean()
        out["pyd"] = P.groupby(k).yards_gained.sum() / pd.Series(gp_team); out["ypa"] = A.groupby(k).yards_gained.mean(); out["cmp"] = 100 * A.groupby(k).complete_pass.mean()
        out["ptd"] = P.groupby(k).pass_touchdown.sum() / pd.Series(gp_team); out["int"] = A.groupby(k).interception.sum() / pd.Series(gp_team)
        out["xpass"] = 100 * (A.yards_gained >= 20).groupby(A[k]).mean(); out["adot"] = A.groupby(k).air_yards.mean(); out["deep"] = 100 * (A.air_yards >= 20).groupby(A[k]).mean()
        out["ruyd"] = Rn.groupby(k).yards_gained.sum() / pd.Series(gp_team); out["ypc"] = Rn.groupby(k).yards_gained.mean(); out["rutd"] = Rn.groupby(k).rush_touchdown.sum() / pd.Series(gp_team)
        out["xrush"] = 100 * (Rn.yards_gained >= 10).groupby(Rn[k]).mean(); out["stuff"] = 100 * Rn.groupby(k).stuff.mean()
        out["sack"] = 100 * D.groupby(k).sack.mean(); out["qbhit"] = D.groupby(k).qb_hit.sum() / pd.Series(gp_team)
        pr = pfp.groupby("team" if side == "off" else "opponent").times_pressured.sum(); out["press"] = 100 * pr / D.groupby(k).size()
        out["blitz"] = 100 * (D.n_blitzers > 0).groupby(D[k]).mean()
        yb = pfr.groupby("team" if side == "off" else "opponent")[["rushing_yards_before_contact", "carries"]].sum(); out["ybc"] = yb.rushing_yards_before_contact / yb.carries
        out["to"] = (sc.interception.fillna(0) + sc.fumble_lost.fillna(0)).groupby(sc[k]).sum() / pd.Series(gp_team)
        pk = pen[pen.penalty_team == pen[k]] if True else pen
        out["pen"] = pk.groupby(k).size() / pd.Series(gp_team); out["peny"] = pk.groupby(k).penalty_yards.sum() / pd.Series(gp_team)
        out["rztd"] = 100 * pd.Series({t: (o_tr if side == "off" else d_tr).td.get(t, 0) / max((o_tr if side == "off" else d_tr).n.get(t, 0), 1) for t in teams})
        return out.astype(float)
    BO, BD = board("off"), board("def")
    # which way is good for the side shown: +1 higher is better, -1 lower is better, 0 no ranking (a tendency, not a quality)
    GOOD_OFF = dict(pts=1, epa=1, succ=1, ypp=1, expl=1, third=1, pyd=1, ypa=1, cmp=1, ptd=1, int=-1, xpass=1, adot=0, deep=0, ruyd=1, ypc=1, rutd=1, xrush=1, stuff=-1,
                    sack=-1, qbhit=-1, press=-1, blitz=0, ybc=1, to=-1, pen=-1, peny=-1, rztd=1)
    def pack(df, good):
        res = {t: {} for t in teams}
        for c in df.columns:
            g = good[c]; rk = df[c].rank(ascending=(g < 0), method="min") if g else df[c].rank(ascending=False, method="min")
            for t in teams:
                res[t][c] = [r1(df.loc[t, c], 3 if c == "epa" else 2 if c in ("ypp", "ypa", "ypc", "ybc", "adot") else 1), int(rk[t])]
        return res
    GOOD_DEF = {k: (-v if k not in ("to", "pen", "peny", "sack", "qbhit", "press", "int", "stuff") else (1 if k in ("to", "sack", "qbhit", "press", "int", "stuff") else -1)) for k, v in GOOD_OFF.items()}
    GOOD_DEF.update(adot=0, deep=0, blitz=0)
    off_b, def_b = pack(BO, GOOD_OFF), pack(BD, GOOD_DEF)

    # tendencies (how a team chooses to play; ranked by amount, not quality)
    T = pd.DataFrame(index=teams)
    T["proe"] = sc.groupby("posteam").pass_oe.mean()
    nz = sc[sc.neutral]; T["npass"] = 100 * nz.groupby("posteam").is_pass_play.mean()
    T["pace"] = top / sc.groupby("posteam").size(); T["plays"] = sc.groupby("posteam").size() / pd.Series(gp_team)
    T["shot"] = 100 * sc.groupby("posteam").shotgun.mean(); T["nohud"] = 100 * sc.groupby("posteam").no_huddle.mean()
    D = sc[sc.is_db]; T["pa"] = 100 * D.groupby("posteam").is_play_action.mean(); T["motion"] = 100 * sc.groupby("posteam").is_motion.mean()
    T["screen"] = 100 * D.groupby("posteam").is_screen_pass.mean(); T["rpo"] = 100 * sc.groupby("posteam").is_rpo.mean()
    f4 = pbp[(pbp.down == 4) & (pbp.ydstogo <= 2) & (pbp.yardline_100 <= 60) & pbp.play_type.isin(["run", "pass", "punt", "field_goal"])]
    T["go4"] = 100 * f4.play_type.isin(["run", "pass"]).groupby(f4.posteam).mean(); T["go4n"] = f4.groupby("posteam").size()
    T["box"] = sc[sc.is_run].groupby("defteam").n_defense_box.mean(); T["dblitz"] = 100 * (D.n_blitzers > 0).groupby(D.defteam).mean()
    T = T.astype(float)
    tend = {t: {c: [r1(T.loc[t, c], 2 if c in ("proe", "pace", "box") else 1), int(T[c].rank(ascending=(c == "pace"), method="min")[t]) if c != "go4n" else 0] for c in T.columns} for t in teams}

    # trenches: who is behind the pressure, and what each defender has allowed in coverage
    pfd["pid"] = pfd.pfr_player_id.map(pfr2g)
    dsum = pfd.groupby(["team", "pfr_player_name", "pfr_player_id"])[["def_pressures", "def_sacks", "def_times_hurried", "def_times_hitqb", "def_targets", "def_completions_allowed",
                                                                 "def_yards_allowed", "def_receiving_td_allowed", "def_ints", "def_missed_tackles"]].sum().reset_index()
    dpos = players.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id").set_index("pfr_id").position.to_dict()
    def rating(c, a, y, td, it):
        if a <= 0: return None
        f = lambda v: min(max(v, 0), 2.375)
        return r1((f((c / a - .3) * 5) + f((y / a - 3) * .25) + f(td / a * 20) + f(2.375 - it / a * 25)) / 6 * 100, 1)
    rushers, cover = {}, {}
    for t, x in dsum.groupby("team"):
        z = x.sort_values("def_pressures", ascending=False).head(5)
        rushers[t] = [[n, dpos.get(i, ""), int(p), r1(s, 1), int(h)] for n, i, p, s, h in zip(z.pfr_player_name, z.pfr_player_id, z.def_pressures, z.def_sacks, z.def_times_hurried) if p > 0]
        z = x[x.def_targets >= 8].sort_values("def_targets", ascending=False).head(7)
        cover[t] = [[n, dpos.get(i, ""), int(a), r1(100 * c / a, 1), int(y), r1(y / a, 1), int(td), int(it), rating(c, a, y, td, it)]
                    for n, i, a, c, y, td, it in zip(z.pfr_player_name, z.pfr_player_id, z.def_targets, z.def_completions_allowed, z.def_yards_allowed, z.def_receiving_td_allowed, z.def_ints)]

    # ---------------- players ----------------
    lg_rate = {}
    for key in ("QB", "WR1", "WR2", "WR3", "TE1", "TE2", "RB1", "RB2", "WR", "TE", "RB"):
        lg_rate[key] = lg_role[key]["td"]
    ptot = pw.groupby("player_id")[list(STAT.values())].sum()
    P = {}
    lg_rz_share_n = 6
    zero = pd.Series(0.0, index=ptot.columns)
    dname = players.drop_duplicates("gsis_id").set_index("gsis_id").display_name.to_dict()
    spos = sn.drop_duplicates("pid", keep="last").set_index("pid").position.to_dict(); sgp = sn.groupby("pid").game_id.nunique().to_dict()
    for pid in list(ptot.index) + [p for p in cur_role if p not in ptot.index]:
        t = cur_team.get(pid); g = pos.get(pid) or spos.get(pid); role = cur_role.get(pid)
        if t not in gp_team or g not in ("QB", "RB", "WR", "TE"):
            continue
        n = gp.get(pid, 0) or sgp.get(pid, 0); s = ptot.loc[pid] if pid in ptot.index else zero
        if not role and (n == 0 or (s.targets + s.carries + s.attempts) < 5):      # every role holder is listed, even one who rarely sees the ball
            continue
        n = max(n, 1); name.setdefault(pid, dname.get(pid, pid))
        rzl = int(rz_pl.looks.get(pid, 0)); rshare = share_in_games(pid, rz_tg_d, rzl)
        ecnt = int(e_pl.get(pid, 0)); eshare = share_in_games(pid, e_tg, ecnt)
        d = dict(n=name.get(pid, pid), t=t, pos=g, role=role, st=status(pid), gp=int(n), snap=r1(100 * snap_share.get(pid, 0), 1),
                 pg={k: r1(s[c] / n, 2 if k in ("rtd", "rutd", "ptd", "td", "int") else 1) for k, c in STAT.items()},
                 td=int(s.td), tdg=int(td_games.get(pid, 0)), ftd=int(first_td.get(pid, 0)),
                 rz=[r1(rzl / n, 2), int(rz_pl.car.get(pid, 0)), int(rz_pl.tgt.get(pid, 0)), r1(100 * rshare, 1), int(rz_td.get(pid, 0))],
                 early=[ecnt, r1(100 * eshare, 1)])
        if pid in ploc.index and ploc.loc[pid]["n"].sum() >= 8:
            nn = ploc.loc[pid]["n"]; yy = ploc.loc[pid]["y"]; tn = nn.sum()
            d["run"] = dict(n=int(tn), mix=[r1(100 * nn.get(l, 0) / tn, 0) for l in LOC], ypc=[r1(yy.get(l, 0) / nn.get(l, 1), 1) if nn.get(l, 0) else None for l in LOC],
                            share=r1(100 * share_in_games(pid, car_tg, car_pl.get(pid, 0)), 1))
        P[pid] = d

    out = dict(built=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), season=SEASON, thru=thru,
               teams={t: dict(n=NICK.get(t, t), gp=int(gp_team[t]), nx=next_game.get(t)) for t in teams},
               games=[dict(id=g.game_id, week=int(g.week), day=g.gameday, wd=g.weekday[:3], time=g.gametime, away=g.away_team, home=g.home_team,
                           spread=None if pd.isna(g.spread_line) else float(g.spread_line), total=None if pd.isna(g.total_line) else float(g.total_line)) for g in up.itertuples()],
               players=P, allow=allow, lg=lg_role, share=share, per=list(PER),
               rz=dict(team=rz_team, dfn=rz_def, lg=r1(lg_rzr, 3)),
               early=dict(off={t: [r1(100 * e_off["mean"].get(t, 0), 1), int(e_off["size"].get(t, 0)), int(e_ork[t])] for t in teams},      # [TD rate %, drives, rank: 1 scores most]
                          dfn={t: [r1(100 * e_def["mean"].get(t, 0), 1), int(e_def["size"].get(t, 0)), int(e_drk[t])] for t in teams},      # [TD rate % allowed, drives, rank: 1 allows most]
                          lg=r1(100 * lg_e, 1), games=int(ftd.game_id.nunique())),
               run=dict(dfn=run_def, lg={l: r1(lg_loc[l], 2) for l in LOC}),
               board=dict(off=off_b, dfn=def_b), tend=tend, rushers=rushers, cover=cover)
    os.makedirs(O + "research", exist_ok=True)
    json.dump(out, open(O + "research/nfl.json", "w"), separators=(",", ":"))
    print(f"research: through week {thru}, {len(P)} players, {len(out['games'])} upcoming games, {len(json.dumps(out, separators=(',', ':'))) // 1024} KB")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)

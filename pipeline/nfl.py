"""NFL prop model: team volume x player share x efficiency, negative binomial distributions.
Walk-forward: every feature for a game is built only from games played before it."""
import json, sys
from types import SimpleNamespace
from collections import defaultdict, deque
import numpy as np, pandas as pd
from common import fit_dispersion, score, nb_k, norm, load_news

D = "/home/claude/props/data/"
OUT = "/home/claude/props/out/"
HL_FAST, HL_SLOW, HL_TEAM = 3.0, 10.0, 6.0
DF, DS, DT = 0.5 ** (1 / HL_FAST), 0.5 ** (1 / HL_SLOW), 0.5 ** (1 / HL_TEAM)
PRI_T = {"WR": .07, "TE": .05, "RB": .04, "QB": .0}
PRI_C = {"WR": .01, "TE": .0, "RB": .15, "QB": .08}
NUM = ["completions", "attempts", "passing_yards", "passing_tds", "carries", "rushing_yards", "rushing_tds",
       "receptions", "targets", "receiving_yards", "receiving_tds"]
STATS = {  # market -> (actual column, relevance filter column, min)
    "pass_yds": ("passing_yards", "f_pass", 15), "pass_att": ("attempts", "f_pass", 15),
    "pass_cmp": ("completions", "f_pass", 15), "pass_td": ("passing_tds", "f_pass", 15),
    "rush_yds": ("rushing_yards", "f_rush", 4), "rush_att": ("carries", "f_rush", 4),
    "rec": ("receptions", "mu_tgt", 2.5), "rec_yds": ("receiving_yards", "mu_tgt", 2.5),
}


def load():
    pw = pd.concat([pd.read_csv(f"{D}nfl_pw_{y}.csv", low_memory=False) for y in (2023, 2024, 2025, 2026)])
    pw = pw[pw.position.isin(["QB", "RB", "WR", "TE", "FB"])].copy()
    pw["pos"] = pw.position.replace({"FB": "RB"})
    pw[NUM] = pw[NUM].fillna(0)
    g = pd.read_csv(D + "nfl_games.csv")
    g = g[g.season >= 2023].copy()
    return pw, g


def priors(pw):
    tr = pw[pw.season <= 2024]
    P = {}
    for pos, d in tr.groupby("pos"):
        P[pos] = dict(cr=d.receptions.sum() / max(d.targets.sum(), 1), ypr=d.receiving_yards.sum() / max(d.receptions.sum(), 1),
                      ypc=d.rushing_yards.sum() / max(d.carries.sum(), 1), rtd=d.receiving_tds.sum() / max(d.targets.sum(), 1),
                      rutd=d.rushing_tds.sum() / max(d.carries.sum(), 1))
    q = tr[tr.pos == "QB"]
    P["QB"].update(cp=q.completions.sum() / q.attempts.sum(), ypa=q.passing_yards.sum() / q.attempts.sum(),
                   ptd=q.passing_tds.sum() / q.attempts.sum())
    tm = tr.groupby(["game_id", "team"])[["attempts", "targets", "carries", "passing_yards", "rushing_yards"]].sum()
    P["lg"] = dict(tpa=tm.targets.sum() / tm.attempts.sum(), ypa=tm.passing_yards.sum() / tm.attempts.sum(),
                   ypc=tm.rushing_yards.sum() / tm.carries.sum(), pa=tm.attempts.mean(), car=tm.carries.mean())
    return P


class State:
    def __init__(self, P):
        self.P = P
        self.pl = defaultdict(lambda: defaultdict(float))
        self.tm = defaultdict(lambda: defaultdict(float))
        self.last = defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))
        self.pseason = {}

    def team_feat(self, t, o):
        L, T, O = self.P["lg"], self.tm[t], self.tm[o]
        w, wo = T["g"], O["g"]
        f = dict(t_pa=(T["pa"] + 2 * L["pa"]) / (w + 2), t_car=(T["car"] + 2 * L["car"]) / (w + 2),
                 o_pa=(O["pa_f"] + 2 * L["pa"]) / (wo + 2), o_car=(O["car_f"] + 2 * L["car"]) / (wo + 2),
                 padj=((O["py_a"] + 150 * L["ypa"]) / (O["pa_f"] + 150)) / L["ypa"],
                 radj=((O["ry_a"] + 120 * L["ypc"]) / (O["car_f"] + 120)) / L["ypc"])
        return f

    def player_feat(self, pid, pos):
        s, P = self.pl[pid], self.P
        pp = P[pos]
        f = dict(ts=(s["tgt"] + 30 * PRI_T[pos]) / (s["ttgt"] + 30), cs=(s["car"] + 25 * PRI_C[pos]) / (s["tcar"] + 25),
                 as_=(s["att"] + 30 * (0.05 if pos == "QB" else 0)) / (s["tatt"] + 30) if pos == "QB" else 0.0,
                 cr=(s["rec"] + 30 * pp["cr"]) / (s["tgt_s"] + 30), ypr=(s["recyd"] + 25 * pp["ypr"]) / (s["rec"] + 25),
                 ypc=(s["rushyd"] + 50 * pp["ypc"]) / (s["car_s"] + 50), rtd=(s["rectd"] + 100 * pp["rtd"]) / (s["tgt_s"] + 100),
                 rutd=(s["rushtd"] + 120 * pp["rutd"]) / (s["car_s"] + 120), n=s["n"], w=s["w"])
        if pos == "QB":
            q = P["QB"]
            f.update(cp=(s["comp"] + 150 * q["cp"]) / (s["att_s"] + 150), ypa=(s["passyd"] + 200 * q["ypa"]) / (s["att_s"] + 200),
                     ptd=(s["passtd"] + 300 * q["ptd"]) / (s["att_s"] + 300))
        else:
            f.update(cp=0.0, ypa=0.0, ptd=0.0)
        return f

    def update(self, season, t, o, rows):
        tot = {c: float(sum(r[c] for r in rows)) for c in NUM}
        T, O = self.tm[t], self.tm[o]
        for k in ("pa", "car", "g"):
            T[k] *= DT
        for k in ("pa_f", "car_f", "py_a", "ry_a"):
            O[k] *= DT
        T["pa"] += tot["attempts"]; T["car"] += tot["carries"]; T["g"] += 1
        O["pa_f"] += tot["attempts"]; O["car_f"] += tot["carries"]; O["py_a"] += tot["passing_yards"]; O["ry_a"] += tot["rushing_yards"]
        for r in rows:
            pid = r["player_id"]; s = self.pl[pid]
            if self.pseason.get(pid, season) != season:      # new season: roles reset faster than skill
                for k in ("tgt", "ttgt", "car", "tcar", "att", "tatt"):
                    s[k] *= 0.5
                for k in ("tgt_s", "rec", "recyd", "rectd", "car_s", "rushyd", "rushtd", "att_s", "comp", "passyd", "passtd"):
                    s[k] *= 0.8
            self.pseason[pid] = season
            for k in ("tgt", "ttgt", "car", "tcar", "att", "tatt"):
                s[k] *= DF
            for k in ("tgt_s", "rec", "recyd", "rectd", "car_s", "rushyd", "rushtd", "att_s", "comp", "passyd", "passtd", "w"):
                s[k] *= DS
            s["tgt"] += r["targets"]; s["ttgt"] += tot["targets"]; s["car"] += r["carries"]; s["tcar"] += tot["carries"]
            s["att"] += r["attempts"]; s["tatt"] += tot["attempts"]
            s["tgt_s"] += r["targets"]; s["rec"] += r["receptions"]; s["recyd"] += r["receiving_yards"]; s["rectd"] += r["receiving_tds"]
            s["car_s"] += r["carries"]; s["rushyd"] += r["rushing_yards"]; s["rushtd"] += r["rushing_tds"]
            s["att_s"] += r["attempts"]; s["comp"] += r["completions"]; s["passyd"] += r["passing_yards"]; s["passtd"] += r["passing_tds"]
            s["n"] += 1; s["w"] += 1
            lg = self.last[pid]
            for c in NUM:
                lg[c].append(float(r[c]))
            lg["meta"].append((season, int(r["week"]), o, r["game_id"]))
            lg["team"].append(t)


def ctx(g):
    """Vegas context from the team's side."""
    out = {}
    for r in g.itertuples():
        sp, tot = r.spread_line, r.total_line
        ok = pd.notna(sp) and pd.notna(tot)
        out[(r.game_id, r.home_team)] = dict(spread=sp if ok else 0.0, total=tot if ok else 44.0, ip=(tot / 2 + sp / 2) if ok else 22.0, home=1)
        out[(r.game_id, r.away_team)] = dict(spread=-sp if ok else 0.0, total=tot if ok else 44.0, ip=(tot / 2 - sp / 2) if ok else 22.0, home=0)
    return out


def walk(pw, g, P):
    C = ctx(g)
    done = g[g.home_score.notna()].sort_values(["gameday", "game_id"])
    byg = {k: v for k, v in pw.groupby(["game_id", "team"])}
    S = State(P)
    prow, trow = [], []
    for r in done.itertuples():
        pend = []
        for t, o in ((r.home_team, r.away_team), (r.away_team, r.home_team)):
            d = byg.get((r.game_id, t))
            if d is None:
                continue
            rows = d.to_dict("records")
            tf = S.team_feat(t, o); c = C[(r.game_id, t)]
            trow.append(dict(game_id=r.game_id, team=t, opp=o, season=r.season, week=r.week, **tf, **c,
                             y_pa=sum(x["attempts"] for x in rows), y_car=sum(x["carries"] for x in rows)))
            for x in rows:
                pf = S.player_feat(x["player_id"], x["pos"])
                l5 = {("l5_" + cn): (float(np.mean(list(S.last[x["player_id"]][cn])[-5:])) if S.last[x["player_id"]][cn] else np.nan) for cn in NUM}
                prow.append(dict(game_id=r.game_id, team=t, opp=o, season=r.season, week=r.week, player_id=x["player_id"],
                                 name=x["player_display_name"], pos=x["pos"], **pf, **l5, **{c2: x[c2] for c2 in NUM}))
            pend.append((t, o, rows))
        for t, o, rows in pend:
            S.update(r.season, t, o, rows)
    return pd.DataFrame(prow), pd.DataFrame(trow), S, C


TF = ["t_pa", "t_car", "o_pa", "o_car", "spread", "total"]


def fit_team(tr):
    X = np.c_[np.ones(len(tr)), tr[TF].values]
    return {"pa": np.linalg.lstsq(X, tr.y_pa.values, rcond=None)[0].tolist(),
            "car": np.linalg.lstsq(X, tr.y_car.values, rcond=None)[0].tolist()}


def project(pr, tr, M, P):
    """Turn component features into means. Mirrors the in-page engine exactly."""
    X = np.c_[np.ones(len(tr)), tr[TF].values]
    tr = tr.assign(PA=X @ np.array(M["team"]["pa"]), CAR=X @ np.array(M["team"]["car"]),
                   tdadj=(tr.ip / M["lg_ip"]).clip(0.45, 1.8))
    d = pr.merge(tr[["game_id", "team", "PA", "CAR", "padj", "radj", "tdadj"]], on=["game_id", "team"])
    grp = d.groupby(["game_id", "team"])
    b = M["beta"]
    # a side with nobody active (stats for its last game not posted yet) sums to zero: floor it so the shares come out 0, not NaN
    d["tsn"] = d.ts * grp.ts.transform("sum").clip(lower=1e-9) ** (-b)
    d["csn"] = d.cs * grp.cs.transform("sum").clip(lower=1e-9) ** (-b)
    d["asn"] = np.minimum(d.as_ / grp.as_.transform("sum").clip(lower=1e-6), 1.0) * 0.985
    c = M["cal"]
    d["mu_tgt"] = d.PA * P["lg"]["tpa"] * d.tsn
    d["mu_rec"] = d.mu_tgt * d.cr * c["rec"]
    d["mu_rec_yds"] = d.mu_tgt * d.cr * d.ypr * d.padj * c["rec_yds"]
    d["mu_rush_att"] = d.CAR * d.csn * c["rush_att"]; d["f_rush"] = d.mu_rush_att
    d["mu_rush_yds"] = d.CAR * d.csn * d.ypc * d.radj * c["rush_yds"]
    d["mu_pass_att"] = d.PA * d.asn * c["pass_att"]; d["f_pass"] = d.mu_pass_att
    d["mu_pass_cmp"] = d.PA * d.asn * d.cp * c["pass_cmp"]
    d["mu_pass_yds"] = d.PA * d.asn * d.ypa * d.padj * c["pass_yds"]
    d["mu_pass_td"] = d.PA * d.asn * d.ptd * d.tdadj * c["pass_td"]
    d["mu_td"] = (d.mu_tgt * d.rtd + d.CAR * d.csn * d.rutd) * d.tdadj * c["td"]
    for k, (a0, b0) in M.get("lin", {}).items():   # slope correction, fit on rows where the market is relevant
        d["mu_" + k] = np.maximum(a0 + b0 * d["mu_" + k], 0.05)
    return d


def main():
    pw, g = load()
    P = priors(pw)
    pr, tr, S, C = walk(pw, g, P)
    pr["y_td"] = ((pr.receiving_tds + pr.rushing_tds) > 0).astype(int)
    warm = ~((pr.season == 2023) & (pr.week <= 4))
    twarm = ~((tr.season == 2023) & (tr.week <= 4))
    is_tr, is_te = warm & (pr.season <= 2024), pr.season >= 2025
    M = {"lg_ip": float(tr.ip.mean()), "beta": 0.8, "cal": defaultdict(lambda: 1.0)}

    def fit(mask_p, mask_t, beta=None):
        m = dict(M); m["cal"] = defaultdict(lambda: 1.0)
        if beta is not None:
            m["beta"] = beta
        m["team"] = fit_team(tr[mask_t])
        d = project(pr[mask_p], tr, m, P)
        cal = {}
        for k, (col, fcol, mn) in STATS.items():
            mm = d[fcol] >= mn
            cal[k] = float(d.loc[mm, col].sum() / d.loc[mm, "mu_" + k].sum())
        mm = (d.mu_tgt >= 2.5) | (d.f_rush >= 4)
        cal["td"] = float((d.loc[mm, "receiving_tds"] + d.loc[mm, "rushing_tds"]).sum() / d.loc[mm, "mu_td"].sum())
        m["cal"] = cal
        d = project(pr[mask_p], tr, m, P); lin = {}
        for k, (col, fcol, mn) in STATS.items():
            mm = d[fcol] >= mn
            lin[k] = [float(v) for v in np.polyfit(d.loc[mm, "mu_" + k], d.loc[mm, col], 1)[::-1]]
        m["lin"] = lin
        return m

    # tune the share re-normalisation strength on the training seasons only
    best = None
    for beta in (0.0, 0.4, 0.6, 0.8, 1.0):
        m = fit(is_tr, twarm & (tr.season <= 2024), beta)
        d = project(pr[is_tr], tr, m, P)
        e = np.abs(d.loc[d.mu_tgt >= 2.5, "receiving_yards"] - d.loc[d.mu_tgt >= 2.5, "mu_rec_yds"]).mean() \
            + 1.0 * np.abs(d.loc[d.f_rush >= 4, "rushing_yards"] - d.loc[d.f_rush >= 4, "mu_rush_yds"]).mean()
        print("beta", beta, round(e, 3))
        if best is None or e < best[0]:
            best = (e, beta)
    M["beta"] = best[1]

    def dispersion(m, mask):
        d = project(pr[mask], tr, m, P)
        disp = {}
        for k, (col, fcol, mn) in STATS.items():
            mm = d[fcol] >= mn
            disp[k] = fit_dispersion(d.loc[mm, "mu_" + k], d.loc[mm, col])
        return disp

    # ---------- honest test: fit on 2023-24, score on 2025-26 ----------
    m_tr = fit(is_tr, twarm & (tr.season <= 2024))
    m_tr["disp"] = dispersion(m_tr, is_tr)
    te = project(pr[is_te], tr, m_tr, P)
    rng = np.random.default_rng(7)
    bt = {}
    for k, (col, fcol, mn) in STATS.items():
        mm = te[fcol] >= mn
        a, b = m_tr["disp"][k]
        sc = score(te.loc[mm, "mu_" + k], te.loc[mm, col], a, b, rng)
        l5 = te.loc[mm, "l5_" + col]; ok = l5.notna()
        sc["mae_model_vs_l5"] = [float(np.abs(te.loc[mm, col][ok] - te.loc[mm, "mu_" + k][ok]).mean()),
                                 float(np.abs(te.loc[mm, col][ok] - l5[ok]).mean())]
        bt[k] = sc
        print(k, sc["n"], "MAE", round(sc["mae_model_vs_l5"][0], 2), "vs L5", round(sc["mae_model_vs_l5"][1], 2),
              "cover80", round(sc["cover80"], 3), "bias", round(sc["bias"], 2), "brier", round(sc["brier"], 4), round(sc["brier_coinflip"], 4))
    mm = (te.mu_tgt >= 2.5) | (te.f_rush >= 4)
    ptd = 1 - np.exp(-te.loc[mm, "mu_td"]); ytd = te.loc[mm, "y_td"]
    rel = []
    for lo, hi in ((0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .65), (.65, 1.01)):
        q = (ptd >= lo) & (ptd < hi)
        if q.sum() >= 25:
            rel.append(dict(lo=lo, hi=min(hi, 1), n=int(q.sum()), pred=float(ptd[q].mean()), obs=float(ytd[q].mean())))
    bt["any_td"] = dict(n=int(mm.sum()), brier=float(((ptd - ytd) ** 2).mean()),
                        brier_coinflip=float(((ytd.mean() - ytd) ** 2).mean()), reliability=rel)
    print("any_td", [(round(r["pred"], 2), round(r["obs"], 2), r["n"]) for r in rel])

    # ---------- final model: refit on everything for live use ----------
    allp, allt = warm, twarm
    MF = fit(allp, allt)
    MF["disp"] = dispersion(MF, allp)
    MF["cal"] = dict(MF["cal"])

    # ---------- upcoming slate ----------
    up = g[(g.season == 2026) & g.home_score.isna()]
    wk = int(up.week.min()); up = up[up.week == wk]
    last_game = {}
    for r in g[g.home_score.notna()].sort_values("gameday").itertuples():
        last_game[r.home_team] = r.game_id; last_game[r.away_team] = r.game_id
    recent = pw[pw.season == 2026].sort_values("week")
    prow, trow, meta, qbnew = [], [], {}, {}
    news = load_news("NFL", [str(x) for x in up.gameday])
    print("lineup news:", "on, %d out, %d questionable, %d with a book line, book QBs %s" % (len(news["out"]), len(news["q"]), len(news["inn"]), news["qb_game"]) if news["on"] else "none this week, lineup is whoever played last game")
    for r in up.itertuples():
        qb = {r.home_team: r.home_qb_name, r.away_team: r.away_qb_name}
        qbn = {t: (norm(qb[t]) if isinstance(qb[t], str) else None) for t in qb}
        cands, imported = {}, {}
        for t in (r.home_team, r.away_team):
            tg = recent[recent.team == t]
            wks = sorted(tg.week.unique())[-4:]
            cand = tg[tg.week.isin(wks)].drop_duplicates("player_id", keep="last")
            cands[t] = (tg, [x for x in cand.itertuples() if list(S.last[x.player_id]["team"])[-1] == t])
        # Starting QB: the book's passing yards market names him. That beats the schedule file and last week's box score.
        bookqb = list(news["qb_game"].get(f"{r.away_team}@{r.home_team}", []))
        if bookqb:
            found = set()
            for t in cands:
                hit = [x for x in cands[t][1] if x.pos == "QB" and norm(x.player_display_name) in bookqb]
                if hit:
                    qbn[t] = norm(hit[0].player_display_name); found.add(qbn[t])
            left = [n for n in bookqb if n not in found]
            open_t = [t for t in cands if qbn[t] not in found]
            if len(left) == 1 and len(open_t) == 1:      # a QB who has not played for this team yet (trade, signing)
                z = pw[(pw.pos == "QB") & (pw.player_display_name.map(norm) == left[0])].sort_values(["season", "week"])
                if len(z) and z.iloc[-1].player_id in S.last:
                    imported[open_t[0]] = SimpleNamespace(player_id=z.iloc[-1].player_id, player_display_name=z.iloc[-1].player_display_name, pos="QB")
                    qbn[open_t[0]] = left[0]
        for t, o in ((r.home_team, r.away_team), (r.away_team, r.home_team)):
            tf = S.team_feat(t, o); c = C[(r.game_id, t)]
            trow.append(dict(game_id=r.game_id, team=t, opp=o, season=r.season, week=r.week, **tf, **c))
            tg, cand = cands[t]
            played_last = set(tg[tg.game_id == last_game[t]].player_id)
            for x in cand + ([imported[t]] if t in imported else []):
                pf = S.player_feat(x.player_id, x.pos)
                nm = norm(x.player_display_name)
                if x.pos == "QB":
                    active = (nm == qbn[t]) if qbn[t] else (x.player_id in played_last and pf["as_"] > 0.5)
                    if active and x.player_id not in played_last:
                        qbnew[t] = True
                else:
                    active = x.player_id in played_last or nm in news["inn"]     # the book has a line on him: he is expected back
                if nm in news["out"]:
                    active = False
                prow.append(dict(game_id=r.game_id, team=t, opp=o, season=r.season, week=r.week, player_id=x.player_id,
                                 name=x.player_display_name, pos=x.pos, **pf))
                meta[x.player_id] = dict(active=bool(active), missed_last=x.player_id not in played_last, q=nm in news["q"])
    upr, utr = pd.DataFrame(prow), pd.DataFrame(trow)
    act = upr[upr.player_id.map(lambda i: meta[i]["active"])]
    proj = project(act, utr, MF, P)

    X = np.c_[np.ones(len(utr)), utr[TF].values]
    utr["PA"] = X @ np.array(MF["team"]["pa"]); utr["CAR"] = X @ np.array(MF["team"]["car"])
    utr["tdadj"] = (utr.ip / MF["lg_ip"]).clip(0.45, 1.8)
    games = [dict(id=r.game_id, day=r.gameday, wd=r.weekday, time=r.gametime, away=r.away_team, home=r.home_team,
                  spread=None if pd.isna(r.spread_line) else float(r.spread_line), total=None if pd.isna(r.total_line) else float(r.total_line))
             for r in up.sort_values(["gameday", "gametime"]).itertuples()]
    teams = {r.team: dict(opp=r.opp, game=r.game_id, PA=round(r.PA, 2), CAR=round(r.CAR, 2), padj=round(r.padj, 4), radj=round(r.radj, 4),
                          tdadj=round(r.tdadj, 4), ip=round(r.ip, 2), home=int(r.home), qbnew=bool(qbnew.get(r.team, False))) for r in utr.itertuples()}
    players = []
    for x in upr.itertuples():
        lg = S.last[x.player_id]
        n = len(lg["meta"]); k = min(n, 10)
        logs = dict(wk=[f"{m[0] % 100}W{m[1]}" for m in list(lg["meta"])[-k:]], opp=[m[2] for m in list(lg["meta"])[-k:]])
        for cn in NUM:
            logs[cn] = [int(v) for v in list(lg[cn])[-k:]]
        if max(x.ts, x.cs) < 0.03 and x.pos != "QB":
            continue
        if x.pos == "QB" and not meta[x.player_id]["active"] and x.as_ < 0.3:
            continue
        players.append(dict(id=x.player_id, name=x.name, pos=x.pos, team=x.team, active=meta[x.player_id]["active"],
                            missed=meta[x.player_id]["missed_last"], q=bool(meta[x.player_id]["q"]), n=int(x.n),
                            ts=round(x.ts, 5), cs=round(x.cs, 5), as_=round(x.as_, 5), cr=round(x.cr, 4), ypr=round(x.ypr, 3),
                            ypc=round(x.ypc, 3), rtd=round(x.rtd, 5), rutd=round(x.rutd, 5), cp=round(x.cp, 4), ypa=round(x.ypa, 3),
                            ptd=round(x.ptd, 5), logs=logs))
    # sums over every active row (including tiny roles we do not display) so the page normalises the same way
    sums = act.groupby("team")[["ts", "cs", "as_"]].sum()
    shown = {p["id"] for p in players}
    rest = act[~act.player_id.isin(shown)].groupby("team")[["ts", "cs", "as_"]].sum()
    for t in teams:
        teams[t]["rest"] = [round(float(rest.ts.get(t, 0)), 5), round(float(rest.cs.get(t, 0)), 5), round(float(rest.as_.get(t, 0)), 5)]
    check = {r.player_id: {k: round(float(getattr(r, "mu_" + k)), 4) for k in list(STATS) + ["td", "tgt"]} | {"f_pass": round(float(r.f_pass), 4), "f_rush": round(float(r.f_rush), 4)} for r in proj.itertuples()}
    out = dict(league="NFL", label=f"Week {wk}", data_through=f"2026 Week {wk - 1}", games=games, teams=teams, players=players,
               model=dict(beta=MF["beta"], tpa=P["lg"]["tpa"], cal=MF["cal"], lin=MF["lin"], disp={k: list(v) for k, v in MF["disp"].items()}),
               backtest=bt, backtest_note="Fit on 2023-24 seasons, scored on 2025 and 2026 games it never saw.")
    import os; os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(OUT + "nfl.json", "w"))
    json.dump(check, open(OUT + "nfl_check.json", "w"))
    print("lin", {k: [round(z, 3) for z in v] for k, v in MF["lin"].items()})
    for k, col, f in (("rec_yds", "receiving_yards", "mu_tgt"), ("rush_yds", "rushing_yards", "f_rush")):
        z = te[te[f] >= (2.5 if f == "mu_tgt" else 4)]; hi = z[z["mu_" + k] >= 60]; lo = z[z["mu_" + k] < 25]
        print("test bias %s: proj 60+ %+.2f (n%d), proj under 25 %+.2f" % (k, (hi[col] - hi["mu_" + k]).mean(), len(hi), (lo[col] - lo["mu_" + k]).mean()))
    print("players", len(players), "games", len(games), "beta", MF["beta"], "cal", {k: round(v, 3) for k, v in MF["cal"].items()})
    print("disp", {k: [round(z, 2) for z in v] for k, v in MF["disp"].items()})
    top = proj.sort_values("mu_rec_yds", ascending=False).head(8)[["name", "team", "mu_tgt", "mu_rec", "mu_rec_yds", "mu_td"]]
    print(top.round(2).to_string()); print(proj.sort_values("mu_pass_yds", ascending=False).head(6)[["name", "team", "mu_pass_att", "mu_pass_yds", "mu_pass_td"]].round(2).to_string())
    print(proj.sort_values("mu_rush_yds", ascending=False).head(6)[["name", "team", "mu_rush_att", "mu_rush_yds", "mu_td"]].round(2).to_string())


if __name__ == "__main__":
    main()

# Research tool (v3.21 closing-line test). Run from /home/claude/props/lab with the decrypted history files in /home/claude/hist/txt (history.yml pulls them).
"""v3.21 closing-line test (research). Charter, fixed before scoring:
Lines: the books' closing player props, one snapshot ten minutes before each game (history pull, 2026-27 NBA from Oct 22 and
2026 NFL weeks 1-10). Universe: every player and market Hard Rock quoted, matched to a walk-forward projection (lab, fitted
on earlier seasons) and to the player's result. Pushes are left out. Markets: NBA points, rebounds, assists, threes; NFL
passing, rushing and receiving yards and receptions.
Question 1, who prices the over best at Hard Rock's line (log loss, lower is better): Hard Rock's own no-vig price, the other
books' consensus, the model alone, the desk's blend (daily.py: market + w x (c x model - market)), and the simulator.
Question 2, the desk's pick rules replayed on these lines (daily.py eligible() and cmd_pick() limits, flat one unit at Hard
Rock's price). Limits of the replay: closing lines are tougher than the late-morning lines the desk bets; the lab projections
know nothing about the day's injury news (the live desk does); the confidence haircut uses what the lab has (history length,
minutes swing, low count, large edge, NFL blowout spread)."""
import sys, os, re, json, glob, math, unicodedata, datetime
sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
from scipy import stats
from common import nb_k

H = "/home/claude/hist/txt/"
MAPK = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3",
        "player_pass_yds": "pass_yds", "player_rush_yds": "rush_yds", "player_reception_yds": "rec_yds", "player_receptions": "rec"}
DISP = {"NBA": json.load(open("nba_mtr.json"))["disp"], "NFL": json.load(open("nfl_mtr.json"))["disp"]}
CAL = json.load(open("/home/claude/props/out/calib.json"))
CFG = dict(min_edge=.03, max_edge=.12, min_adj_ev=.025, min_odds=-160, max_odds=150, min_games=8, nba_min_minutes=20.0, min_books=2,
           max_picks=3, max_per_game=2, cal_c_n0=5, pick_markets={"NBA": ["pts", "reb", "ast"], "NFL": ["rec_yds", "rush_yds", "pass_yds"]})


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'\-]", " ", s); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    return " ".join(s.split())


def dec(a): return 1 + (a / 100 if a > 0 else 100 / -a)


def pov(lg, mkt, mu, line):
    a, b = DISP[lg][mkt]; k = float(nb_k(np.array([max(mu, .01)]), a, b)[0]); pr = k / (k + max(mu, .01))
    un = stats.nbinom.cdf(math.ceil(line) - 1, k, pr); push = stats.nbinom.pmf(int(line), k, pr) if float(line).is_integer() else 0
    o = 1 - un - push; return o / (o + un)


def imean(lg, mkt, line, p):
    lo, hi = .02, max(6 * line + 20, 10)
    for _ in range(36):
        mid = (lo + hi) / 2
        if pov(lg, mkt, mid, line) < p: lo = mid
        else: hi = mid
    return (lo + hi) / 2


if __name__ == '__main__':
    # ---- closing lines
    rows = []
    for f in sorted(glob.glob(H + "*.txt")):
        lg = os.path.basename(f)[:3]; gl = tip = None
        for ln in open(f):
            if ln.startswith("# game:"): gl = ln[7:].strip(); continue
            if ln.startswith("# tip:"): tip = ln[6:].strip()[:10]; continue
            if ln.startswith("#") or ln.startswith("bookmaker"): continue
            b, m, p, l, o, u = ln.rstrip("\n").split("|")
            if m not in MAPK or not l or not o or not u: continue
            rows.append(dict(lg=lg, date=tip, gl=gl, book=b, mkt=MAPK[m], name=p, key=norm(p), line=float(l), o=int(o), u=int(u)))
    Lq = pd.DataFrame(rows); print("closing quotes", len(Lq), Lq.groupby("lg").size().to_dict())

    # ---- projections and results
    A = pd.read_parquet("nba_proj.parquet"); A = A[A.season == 2027].copy(); A["date"] = A.gd.astype(str); A["key"] = A.name.map(norm)
    prior = pd.read_parquet("nba_proj.parquet").sort_values("gd")
    prior["n_prev"] = prior.groupby("pid").cumcount()
    prior["cvmin"] = prior.groupby("pid").y_min.transform(lambda s: s.shift(1).rolling(5, min_periods=3).std() / s.shift(1).rolling(5, min_periods=3).mean())
    A = A.merge(prior[["game_id", "pid", "n_prev", "cvmin"]], on=["game_id", "pid"], how="left")
    N = pd.read_parquet("nfl_proj.parquet"); Gm = pd.read_parquet("nfl_games.parquet")
    N = N[N.season == 2026].merge(Gm[["game_id", "gameday", "spread_line"]], on="game_id", how="left"); N["date"] = N.gameday.astype(str); N["key"] = N.name.map(norm)
    allN = pd.read_parquet("nfl_proj.parquet").merge(Gm[["game_id", "gameday"]], on="game_id").sort_values("gameday")
    allN["n_prev"] = allN.groupby("player_id").cumcount(); N = N.merge(allN[["game_id", "player_id", "n_prev"]], on=["game_id", "player_id"], how="left")
    MU = {"NBA": {"pts": ("mu_pts", "pts"), "reb": ("mu_reb", "reb"), "ast": ("mu_ast", "ast"), "fg3": ("mu_fg3", "fg3")},
          "NFL": {"pass_yds": ("mu_pass_yds", "passing_yards"), "rush_yds": ("mu_rush_yds", "rushing_yards"), "rec_yds": ("mu_rec_yds", "receiving_yards"), "rec": ("mu_rec", "receptions")}}
    P = {"NBA": A, "NFL": N}

    # ---- one row per Hard Rock quote, with the market view from the other books
    out = []
    for (lg, date, key, mkt), q in Lq.groupby(["lg", "date", "key", "mkt"]):
        hr = q[q.book == "hardrockbet"]
        if hr.empty: continue
        hr = hr.iloc[0]
        cand = P[lg][(P[lg].date == date) & (P[lg].key == key)]
        if len(cand) != 1: continue
        x = cand.iloc[0]; mcol, ycol = MU[lg][mkt]; mu, y = float(x[mcol]), x[ycol]
        if pd.isna(y) or mu <= 0: continue
        line = hr.line
        if float(y) == line: continue          # push
        po, pu = 1 / dec(hr.o), 1 / dec(hr.u); p_hr = po / (po + pu)
        oth = [imean(lg, mkt, r.line, (1 / dec(r.o)) / (1 / dec(r.o) + 1 / dec(r.u))) for r in q[q.book != "hardrockbet"].itertuples()]
        mm = float(np.median(oth)) if oth else None
        out.append(dict(lg=lg, date=date, gl=hr.gl, game=x.game_id, key=key, name=hr["name"], mkt=mkt, line=line, o=int(hr.o), u=int(hr.u), y=float(y),
                        over=float(float(y) > line), mu=mu, mm=mm, nb=len(oth), p_hr=p_hr,
                        n_prev=x.get("n_prev"), mn=x.get("mn") if lg == "NBA" else None, cvmin=x.get("cvmin") if lg == "NBA" else None,
                        spread=x.get("spread_line") if lg == "NFL" else None, pidx=cand.index[0]))
    R = pd.DataFrame(out); print("matched Hard Rock props (no pushes)", len(R), R.groupby(["lg", "mkt"]).size().to_dict())
    R["game"] = R.game.astype(str); R.to_pickle("close_rows.pkl")
    hrq = Lq[Lq.book == "hardrockbet"].groupby(["lg", "date", "key", "mkt"]).ngroups; print("Hard Rock quotes", hrq)

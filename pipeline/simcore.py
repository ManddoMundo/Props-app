"""Game simulator core: plays a game out thousands of times so the players in it move together.

NBA. Each run draws one game, then fills in the box score from the top down, so every number adds up:
  1. The game: home margin ~ Normal(spread, sd) and total ~ Normal(total, sd), which give the two team scores.
  2. Minutes: each player's projected minutes are moved by how lopsided this run's game is (starters sit in a blowout,
     the bench plays more; table fitted on 2024-25 box scores), plus his own night-to-night noise, then rescaled so the
     team's minutes add back up.
  3. Team totals given the score: threes, rebounds and assists follow the team's points (a hot shooting night means more
     threes and more assists), with the leftover noise measured on 2024-25 games.
  4. Shares: the team's threes, its other points, rebounds and assists are dealt out to the players in proportion to
     their projections times their minutes this run, with a Dirichlet draw so a player can have a big or quiet night.
     A player's points are 3 x his threes plus his share of the other points, so the team score is the players' points.
The projections themselves come from nba.py; the simulator only changes how the numbers vary together.
Display and tracking only: nothing here feeds the desk's prices or picks (see sim.py and the CHANGELOG, v3.20)."""
import numpy as np

# Fitted on 2024-25 (season 2025) with sim_bt.py; the margin and total spreads for market inputs on 2025-26 games
# before Jan 1, 2026. Scored on Jan 1, 2026 onward. Numbers and the test are in the CHANGELOG, v3.20.
NBA = {
    "mbins": [2.5, 7.5, 12.5, 17.5, 22.5, 27.5, 35.0],          # |final margin| bin centres for the minutes table
    "tiers": [15.0, 24.0, 30.0],                                   # projected minutes cut points: <15, 15-24, 24-30, 30+
    # relative minutes by tier (rows: <15, 15-24, 24-30, 30+) at each |margin|: a 36-minute star plays about 13% less
    # in a 30-point game than in a close one, the end of the bench about 30% more
    "mrel": [[1.0241, 1.0163, 0.8619, 0.8832, 0.9886, 1.2063, 1.2886], [0.9771, 0.9696, 1.0067, 1.0199, 1.0113, 1.0613, 1.0502],
             [1.0133, 1.0123, 1.009, 1.0054, 1.0064, 0.951, 0.9195], [1.048, 1.0356, 1.0124, 0.9808, 0.9593, 0.8989, 0.8742]],
    "msd": [0.7741, 0.4414, 0.2655, 0.2049],                       # night-to-night minutes noise by tier (log sd)
    "gam": {"fg3": 1.56, "reb": 0.119, "ast": 1.026},              # team stat elasticity to team points
    "tint": {"fg3": 0.0, "reb": -0.008, "ast": 0.0},           # v3.21: no shrink on threes and assists (it pulled starters under)
    "tsd": {"fg3": 0.2364, "reb": 0.1473, "ast": 0.1521},          # leftover team-level noise (share of the mean)
    "alpha": {"fg3": 80.0, "non3": 80.0, "reb": 1000.0, "ast": 320.0},   # v3.21 refit on 2024-25
    "sd_m": 14.14, "sd_t": 19.55,                                  # final margin and total around the line (2025-26 to Dec 31)
    "sd_m_model": 15.17, "sd_t_model": 19.18, "hfa_model": 1.93, "tadj_model": 1.36,   # around the sum of player projections
}


def tier_of(mn, cuts):
    return np.searchsorted(np.asarray(cuts), mn, side="right")


def rel_minutes(P, tiers, aM):
    """Relative minutes for each player (tier index) at each run's |margin|: shape [N, n]."""
    tab = np.asarray(P["mrel"])                       # [4, 7]
    xs = np.asarray(P["mbins"])
    cols = np.stack([np.interp(aM, xs, tab[t]) for t in range(tab.shape[0])], axis=1)   # [N, 4]
    return cols[:, tiers]


def dm_alloc(rng, total, share, alpha):
    """Deal `total` (shape [N]) out over players with expected shares `share` (shape [n] or [N, n]) using a
    Dirichlet-multinomial with concentration alpha. Returns integer counts [N, n] that add up to total."""
    s = np.maximum(np.asarray(share, float), 1e-6)
    s = s / s.sum(axis=-1, keepdims=True)
    N = total.shape[0]
    g = rng.gamma(np.broadcast_to(alpha * s, (N, s.shape[-1])))
    pi = g / g.sum(axis=1, keepdims=True)
    pi = pi / pi.sum(axis=1, keepdims=True)
    return rng.multinomial(np.maximum(total, 0).astype(np.int64), pi)


def nba_game(rng, N, home, away, margin, total, P=NBA, sd_m=None, sd_t=None):
    """home/away: dict(mu={pts,reb,ast,fg3: array[n]}, mn=array[n]). margin = expected home minus away points,
    total = expected combined points. Returns per-run samples."""
    sd_m = P["sd_m"] if sd_m is None else sd_m
    sd_t = P["sd_t"] if sd_t is None else sd_t
    M = rng.normal(margin, sd_m, N)
    T = rng.normal(total, sd_t, N)
    sc = np.stack([np.round((T - M) / 2), np.round((T + M) / 2)], axis=1)          # away, home
    tie = sc[:, 0] == sc[:, 1]
    sc[tie, 1 - (M[tie] > 0).astype(int)] -= 1           # no ties: the side the margin favours keeps the point
    sc = np.maximum(sc, 60)
    aM = np.abs(sc[:, 1] - sc[:, 0])
    out = {"score": sc.astype(np.int16), "M": (sc[:, 1] - sc[:, 0]).astype(np.int16), "teams": []}
    for j, side in enumerate((away, home)):
        mu = {k: np.maximum(np.asarray(side["mu"][k], float), 0.01) for k in ("pts", "reb", "ast", "fg3")}
        mn = np.asarray(side["mn"], float)
        n = len(mn)
        tiers = tier_of(mn, P["tiers"])
        rel = rel_minutes(P, tiers, aM)
        z = rng.standard_normal((N, n))
        sd = np.asarray(P["msd"])[tiers]
        mins = mn * rel * np.exp(sd * z - sd * sd / 2)
        mins = np.minimum(mins * (min(mn.sum(), 241.0) / mins.sum(axis=1, keepdims=True)), 44.0)   # stat shares use relative minutes, so this only keeps the box score to a real night's 240    # v3.20: 48 in the backtest; 44 keeps a regulation night believable on the page
        r = mins / np.maximum(mn, 1e-6)
        Pt = sc[:, j].astype(float)
        Pm = mu["pts"].sum()
        box = {"min": mins}
        tot = {}
        for k in ("fg3", "reb", "ast"):
            m = mu[k].sum() * np.exp(P["tint"][k]) * (Pt / Pm) ** P["gam"][k]
            tot[k] = np.maximum(np.round(m * (1 + P["tsd"][k] * rng.standard_normal(N))), 0)
        tot["fg3"] = np.minimum(tot["fg3"], np.floor(Pt / 3) - 2)
        if P.get("ast_fgm"):
            # v3.21: assists come off made baskets. The team's field goals made this run (its threes plus its twos, the
            # twos being what is left of the points after free throws) set how many assists there can be; the share of
            # baskets that were assisted is the team's own, from its players' projections.
            ftsh = P.get("ft_share", 0.18)
            fgm = tot["fg3"] + np.round((Pt - 3 * tot["fg3"]) * (1 - ftsh) / 2)
            efgm = mu["fg3"].sum() + (mu["pts"].sum() - 3 * mu["fg3"].sum()) * (1 - ftsh) / 2
            rate = np.clip(mu["ast"].sum() * np.exp(P["tint"]["ast"]) / max(efgm, 1.0), 0.05, 0.95)
            tot["ast"] = rng.binomial(np.maximum(fgm, 0).astype(np.int64), rate)
        f3 = dm_alloc(rng, tot["fg3"], mu["fg3"] * r, P["alpha"]["fg3"])
        non3 = dm_alloc(rng, Pt - 3 * tot["fg3"], np.maximum(mu["pts"] - 3 * mu["fg3"], 0.1) * r, P["alpha"]["non3"])
        box["fg3"] = f3
        box["pts"] = 3 * f3 + non3
        box["reb"] = dm_alloc(rng, tot["reb"], mu["reb"] * r, P["alpha"]["reb"])
        box["ast"] = dm_alloc(rng, tot["ast"], mu["ast"] * r, P["alpha"]["ast"])
        out["teams"].append(box)
    return out


# ---------------------------------------------------------------- scoring helpers (shared by the backtest and the live log)

def crps_samples(samples, y, xmax):
    """CRPS of integer samples [N, n] against outcomes y [n] on the grid 0..xmax."""
    grid = np.arange(xmax + 1)
    F = (samples[:, :, None] <= grid).mean(axis=0)                  # [n, G]
    H = (y[:, None] <= grid).astype(float)
    return ((F - H) ** 2).sum(axis=1)


def crps_sorted(samples, y):
    """CRPS of samples [N, n] (any real values) against y [n]: E|X - y| - E|X - X'| / 2, exact for the sample."""
    x = np.sort(samples, axis=0).astype(float)
    N = x.shape[0]
    a = np.abs(x - y[None, :]).mean(axis=0)
    w = (2 * np.arange(1, N + 1) - N - 1)[:, None]
    return a - (w * x).sum(axis=0) / (N * N)


# ---------------------------------------------------------------- NFL
# Each run draws the game (margin and total around the line), then the game script: a team that ends up trailing by more
# than the spread said throws more and runs less, and the other way round (fitted on 2023-24). Targets and carries are
# dealt out by the players' projected shares (Dirichlet-multinomial), catches by each player's catch rate, yards per
# catch and per carry drawn one play at a time, all scaled by how well the offence played in that run (its points against
# what the line implied). The quarterback's passing yards are the sum of his receivers' yards, so the two move together.
NFL = {
    "sd_m": 12.93, "sd_t": 12.79,                         # final margin and total around the closing spread and total
    "pa_slope": -0.0046, "pa_sd": 0.05,                   # pass attempts: per point the team beats its spread by; leftover log sd
    "car_slope": 0.0107, "car_sd": 0.16,                  # carries
    "rec_el": 0.264, "rec_sd": 0.06,                      # yards per catch: elasticity to points over implied, leftover team log sd
    "rush_el": 0.088, "rush_sd": 0.05,
    "td_el": 0.93,
    "catch_sd": 9.85, "carry_sd": 6.22,                    # yards: per-catch and per-carry spread
    "alpha": {"tgt": 60.0, "car": 15.0, "td": 30.0},     # carries 15: the 2023-24 fit (v3.20 shipped 60 by mistake)
    "tpa": 0.954, "other_ypr": 8.5,
    "emp": True,                                          # v3.21: catch and carry yards drawn from real 2023-24 plays
    "qb_c": 1.5,                                          # v3.21: QB share of dropbacks ~ beta(share*1.5, (1-share)*1.5)
}


def _lnorm(rng, x, sd, N):
    """Mean-one lognormal multiplier with log mean x (array [N]) and leftover sd, normalised so E = 1 over the spread of x."""
    z = x + sd * rng.standard_normal(N)
    return np.exp(z - np.log(np.mean(np.exp(z))))


def _load_lib():
    import json, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nfl_yards_lib.json")
    try:
        return {k: np.asarray(v, float) for k, v in json.load(open(p)).items()}
    except Exception:
        return None


_LIB = _load_lib()


def _pgroup(pos):
    pos = np.asarray(pos).astype(str)
    return np.where(np.isin(pos, ["RB", "FB"]), "RB", np.where(pos == "TE", "TE", np.where(pos == "QB", "QB", "WR")))


def _emp_sum(rng, cnt, lib, scale):
    """Sum of cnt[N, m] draws from an empirical quantile table lib, each column scaled by scale[m]."""
    cnt = cnt.astype(np.int64); K = int(cnt.max()) if cnt.size else 0
    if K == 0:
        return np.zeros(cnt.shape)
    out = np.zeros(cnt.shape)
    for k in range(K):
        on = cnt > k
        out += lib[rng.integers(0, len(lib), cnt.shape)] * on
    return out * scale[None, :]


def nfl_game(rng, N, home, away, spread, total, P=NFL):
    """home/away: dict(PA, CAR, ip, mu={tgt, rec, rec_yds, rush_att, rush_yds, pass_att, pass_cmp, pass_yds, td: array[n]}, qb=array[n] bool).
    spread = expected home minus away points; total = expected combined points."""
    M = rng.normal(spread, P["sd_m"], N)
    T = np.maximum(rng.normal(total, P["sd_t"], N), 6)
    sc = np.stack([np.maximum(np.round((T - M) / 2), 0), np.maximum(np.round((T + M) / 2), 0)], axis=1)
    tie = sc[:, 0] == sc[:, 1]
    sc[tie, (M[tie] > 0).astype(int)] += 3                # overtime field goal
    sc[sc == 1] = 2
    out = {"score": sc.astype(np.int16), "M": (sc[:, 1] - sc[:, 0]).astype(np.int16), "teams": []}
    for j, (side, sp) in enumerate(((away, -spread), (home, spread))):
        mu = {k: np.maximum(np.asarray(side["mu"][k], float), 0.0) for k in side["mu"]}
        n = len(mu["tgt"]); qb = np.asarray(side["qb"], bool)
        pts = sc[:, j].astype(float)
        dM = (sc[:, j] - sc[:, 1 - j]) - sp
        pa = rng.poisson(side["PA"] * _lnorm(rng, P["pa_slope"] * dM, P["pa_sd"], N))
        car = rng.poisson(side["CAR"] * _lnorm(rng, P["car_slope"] * dM, P["car_sd"], N))
        lp = np.log(np.maximum(pts, 3) / max(side["ip"], 3))
        eff_r = _lnorm(rng, P["rec_el"] * lp, P["rec_sd"], N)
        eff_u = _lnorm(rng, P["rush_el"] * lp, P["rush_sd"], N)
        # targets: projected players plus everyone else on the roster
        # team volume: never less than the players' own projections add up to (plus a little for everyone else),
        # so every projected player keeps his projected average
        tg_exp = max(side["PA"] * P["tpa"], mu["tgt"].sum() / 0.95)
        sh = np.append(mu["tgt"], tg_exp - mu["tgt"].sum())
        tgt = dm_alloc(rng, np.round(rng.binomial(pa, P["tpa"]) * tg_exp / max(side["PA"] * P["tpa"], 1e-6)), sh, P["alpha"]["tgt"])
        cr = np.append(np.clip(mu["rec"] / np.maximum(mu["tgt"], 1e-6), 0.05, 0.95), 0.62)
        rec = rng.binomial(tgt, cr)
        ypr = np.append(np.where(mu["rec"] > 1e-6, mu["rec_yds"] / np.maximum(mu["rec"], 1e-6), 8.0), P["other_ypr"])
        kap = (ypr / P["catch_sd"]) ** 2                   # gamma shape per catch
        pos = np.append(np.asarray(side.get("pos", ["WR"] * n)), "WR")
        if P.get("emp"):
            # v3.21: each catch is a real 2023-24 catch for that position (WR, TE or RB), scaled to the player's yards per catch
            ry = np.zeros(rec.shape)
            for g in ("WR", "TE", "RB"):
                cols = np.where(_pgroup(pos) == g)[0]
                if len(cols):
                    lib = _LIB["catch_" + g]
                    ry[:, cols] = _emp_sum(rng, rec[:, cols], lib, ypr[cols] / lib.mean())
            ry = np.round(ry * eff_r[:, None])
        else:
            ry = rng.gamma(np.maximum(rec * kap, 1e-9), (ypr / kap) * eff_r[:, None]) * (rec > 0)
            ry = np.round(ry)
        # carries
        car_exp = max(side["CAR"], mu["rush_att"].sum() / 0.97)
        csh = np.append(mu["rush_att"], car_exp - mu["rush_att"].sum())
        cars = dm_alloc(rng, np.round(car * car_exp / max(side["CAR"], 1e-6)), csh, P["alpha"]["car"])
        ypc = np.append(np.where(mu["rush_att"] > 1e-6, mu["rush_yds"] / np.maximum(mu["rush_att"], 1e-6), 3.5), 3.8)
        if P.get("emp"):
            # v3.21: each carry is a real 2023-24 carry (designed runs for backs, all runs for quarterbacks), scaled to his yards per carry
            rush = np.zeros(cars.shape)
            for g in ("RB", "QB"):
                cols = np.where((_pgroup(pos) == "QB") == (g == "QB"))[0]
                if len(cols):
                    lib = _LIB["carry_" + g]
                    rush[:, cols] = _emp_sum(rng, cars[:, cols], lib, ypc[cols] / lib.mean())
            rush = np.round(rush * eff_u[:, None])
        else:
            rush = np.round(rng.normal(cars * ypc * eff_u[:, None], np.sqrt(cars) * P["carry_sd"]))
            rush = np.maximum(rush, -2 * cars)
        # touchdowns
        tdm = mu["td"].sum() + 0.3
        tds = rng.poisson((tdm * np.exp(P["td_el"] * lp)) / np.mean(np.exp(P["td_el"] * lp)))
        td = dm_alloc(rng, tds, np.append(mu["td"], 0.3), P["alpha"]["td"])
        # quarterback: attempts, completions and yards are the passing game he ran
        qshare = np.where(qb, mu["pass_att"] / max(mu["pass_att"][qb].sum(), 1e-6), 0.0) if qb.any() else np.zeros(n)
        box = {"tgt": tgt[:, :n], "rec": rec[:, :n], "rec_yds": ry[:, :n], "rush_att": cars[:, :n], "rush_yds": rush[:, :n], "td": td[:, :n]}
        box["pass_att"] = np.round(pa[:, None] * qshare[None, :] * (mu["pass_att"][qb].sum() / max(side["PA"], 1e-6) if qb.any() else 0))
        # the passing game is the receivers' catches and yards; scaled so the quarterback keeps his own projected average
        e_rec = (sh / sh.sum() * tg_exp * cr).sum(); e_yds = (sh / sh.sum() * tg_exp * cr * ypr).sum()
        kc = mu["pass_cmp"] / np.maximum(qshare * e_rec, 1e-6); ky = mu["pass_yds"] / np.maximum(qshare * e_yds, 1e-6)
        box["pass_cmp"] = np.round(rec.sum(1)[:, None] * qshare[None, :] * np.where(qb, kc, 0)[None, :])
        box["pass_yds"] = np.round(ry.sum(1)[:, None] * qshare[None, :] * np.where(qb, ky, 0)[None, :])
        qc = P.get("qb_c", 0.0)
        if qc > 0 and qb.any():
            # v3.21: the quarterback's share of the team's dropbacks is itself uncertain (early exits, benchings, a split
            # job). Drawn from a beta around his projected share; wider for a part-timer, left-leaning for a starter.
            s_ = np.clip(mu["pass_att"] / max(side["PA"], 1e-6), 0.02, 0.985)
            f = rng.beta(np.maximum(s_ * qc, 1e-3)[None, :].repeat(N, 0), np.maximum((1 - s_) * qc, 1e-3)[None, :].repeat(N, 0)) / s_[None, :]
            for k in ("pass_att", "pass_cmp", "pass_yds"):
                box[k] = np.where(qb[None, :], np.round(box[k] * f), box[k])
        # each player's touchdowns split into catches and runs by his own mix (rfrac: share of his TDs that come through the air)
        frac = np.append(np.clip(np.asarray(side.get("rfrac", np.ones(n)), float), 0, 1), 0.7)
        rec_td = rng.binomial(td, frac)
        box["rec_td"] = rec_td[:, :n]
        box["pass_td"] = np.round(rec_td.sum(1)[:, None] * qshare[None, :])
        box["score"] = pts
        out["teams"].append(box)
    return out

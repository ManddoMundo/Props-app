"""Lab, v3.52 (research only; nothing here runs in the daily job):
Tests whether adding Vegas game context (implied team total & blowout spread) from out/nba_lines.jsonl
improves NBA player prop projections walk-forward.

Charter (locked before scoring):
  - Data: nba_pb_2025..2027.parquet + out/nba_lines.jsonl (DraftKings opening/closing spread & total).
  - Baseline: nba.py walk-forward projections (shot build ON, fitted on 2024-25).
  - Fit split: 2025-26 games before Jan 1, 2026 (where nba_lines.jsonl coverage begins).
  - Test split (scored once): 2025-26 from Jan 1, 2026 onward, and 2026-27.
  - Features tested:
      1) Implied team total multiplier: blend team expected points T_pts toward Vegas implied team score.
      2) Blowout minutes adjustment: scale projected minutes for starters (mn >= 28) vs bench (mn < 20)
         as a linear function of |spread| above 6 points, before rebalancing to 240.
  - Primary metric: MAE on pts, reb, ast, fg3 (mn >= 15), plus paired game-day bootstrap (2,000 draws).
Run from /home/claude/props/src or lab: python3 nba_vegas_bt.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
import nba

BASE = nba.BASE
LINES_PATH = "/home/claude/props/out/nba_lines.jsonl"


def load_lines(which="o"):
    """{game id: (home spread line, total)} from the DraftKings numbers ESPN keeps on each game. which="o" is the opening
    line (known before the desk prices a game), "c" the closing line (not known at midday: using it is a look-ahead)."""
    out = {}
    if not os.path.exists(LINES_PATH):
        raise FileNotFoundError(f"Missing {LINES_PATH}. Run nba_lines.py first.")
    for ln in open(LINES_PATH):
        if not ln.strip():
            continue
        r = json.loads(ln)
        if not r.get("pc"):
            continue
        v = ((r["pc"][0].get("oc") or {}).get(which)) or []
        if len(v) < 2 or v[0] is None or v[1] is None:
            continue
        out[str(r["id"])] = (float(v[0]), float(v[1]))
    return out


def project_vegas(pr, tr, M, w_tot=0.0, b_star=0.0, b_bench=0.0):
    d = pr.merge(tr, on=["game_id", "team"], suffixes=("", "_t"))
    # Blowout minutes adjustment before 240 rebalance
    ex_sp = np.maximum(d["abs_spread"].fillna(0.0) - 6.0, 0.0)
    m_adj = d.m.copy()
    if b_star != 0.0:
        m_adj = np.where(d.m >= 28.0, m_adj * (1.0 + b_star * ex_sp), m_adj)
    if b_bench != 0.0:
        m_adj = np.where(d.m < 20.0, m_adj * (1.0 + b_bench * ex_sp), m_adj)
    d["m_eff"] = np.clip(m_adj, 1.0, 42.0)

    g = d.groupby(["game_id", "team"])
    tot = g.m_eff.transform("sum")
    w = d.m_eff * np.maximum(38.0 - d.m_eff, 0.5)
    up = d.m_eff + (240.0 - tot) * w / w.groupby([d.game_id, d.team]).transform("sum")
    d["mn"] = np.minimum(d.m_eff + M["bm"] * (np.where(tot < 240, up, d.m_eff * 240.0 / tot) - d.m_eff), 40.0)

    # Blend T_pts toward Vegas implied team points where available
    T_pts = np.where(d["imp_pts"].notna(), (1.0 - w_tot) * d["T_pts"] + w_tot * d["imp_pts"], d["T_pts"])
    for k in BASE:
        raw = d.mn * d["r_" + k]
        tk = T_pts if k == "pts" else d["T_" + k]
        d["mu_" + k] = raw * (tk / raw.groupby([d.game_id, d.team]).transform("sum")) ** M["bs"][k] * M["cal"].get(k, 1.0)
        if "lin" in M:
            d["mu_" + k] = np.maximum(M["lin"][k][0] + M["lin"][k][1] * d["mu_" + k], 0.05)
    return d


def boot_diff(e0, e1, gds, n_boot=2000, seed=7):
    rng = np.random.default_rng(seed)
    g = pd.DataFrame({"d": e1 - e0, "gd": gds}).groupby("gd").d.agg(["sum", "count"])
    s_arr, c_arr = g["sum"].values, g["count"].values
    bs = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(s_arr), len(s_arr))
        bs.append(s_arr[idx].sum() / c_arr[idx].sum())
    bs = np.array(bs)
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), float((bs < 0).mean())


if __name__ == "__main__":
    WHICH = sys.argv[1] if len(sys.argv) > 1 else "o"
    lines = load_lines(WHICH)
    print("lines used:", "opening (fair test)" if WHICH == "o" else "closing (look-ahead, for comparison only)", len(lines), "games")
    d = nba.load()
    pr, tr, _ = nba.walk(d)
    ha_map = d.drop_duplicates(["game_id", "team"]).set_index(["game_id", "team"])["home_away"].to_dict()
    imp_pts, abs_sp = [], []
    for r in tr.itertuples():
        ln = lines.get(str(r.game_id)); ha = ha_map.get((r.game_id, r.team))
        if not ln or ha not in ("home", "away"):
            imp_pts.append(np.nan); abs_sp.append(np.nan); continue
        hl, ou = ln      # home spread line: negative when the home side is favoured
        imp_pts.append((ou - hl) / 2.0 if ha == "home" else (ou + hl) / 2.0)
        abs_sp.append(abs(hl))
    tr["imp_pts"] = imp_pts
    tr["abs_spread"] = abs_sp
    print("team-games with a line:", int(tr.imp_pts.notna().sum()), "of", len(tr), "| mean implied points", round(float(tr.imp_pts.mean()), 1), "| mean model T_pts", round(float(tr.T_pts.mean()), 1))

    # Fit base nba.py parameters on 2024-25 after warmup
    first = pr[pr.season == 2025].gd.min()
    warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
    is_tr = warm & (pr.season == 2025)
    M = {"bm": 0.8, "bs": {k: 0.5 for k in BASE}, "cal": {}}
    best = min(((np.abs(nba.project(pr[is_tr], tr, dict(M, bm=bm)).y_min - nba.project(pr[is_tr], tr, dict(M, bm=bm)).mn).mean(), bm) for bm in (0.0, 0.5, 0.8, 1.0)))
    M["bm"] = best[1]
    for k in BASE:
        M["bs"][k] = min(((np.abs(dd.loc[dd.mn >= 15, k] - dd.loc[dd.mn >= 15, "mu_" + k]).mean(), bs)
                          for bs in (0.0, 0.25, 0.5, 0.75, 1.0)
                          for dd in [nba.project(pr[is_tr], tr, dict(M, bs={**M["bs"], k: bs}))]))[1]
    dd = nba.project(pr[is_tr], tr, M); mm = dd.mn >= 15
    M["cal"] = {k: float(dd.loc[mm, k].sum() / dd.loc[mm, "mu_" + k].sum()) for k in BASE}
    dd = nba.project(pr[is_tr], tr, M); mm = dd.mn >= 15
    M["lin"] = {k: [float(v) for v in np.polyfit(dd.loc[mm, "mu_" + k], dd.loc[mm, k], 1)[::-1]] for k in BASE}

    # Tune Vegas weights on early 2025-26 (< 2026-01-01), score out-of-sample on >= 2026-01-01 & 2026-27
    fit_v = (pr.season == 2026) & (pr.gd < "2026-01-01")
    te_a = (pr.season == 2026) & (pr.gd >= "2026-01-01")
    te_b = (pr.season == 2027)

    best_cfg = None
    for w_tot in (0.0, 0.25, 0.5, 0.75, 1.0):
        for b_star in (0.0, -0.005, -0.01, -0.015):
            for b_bench in (0.0, 0.01, 0.02):
                df = project_vegas(pr[fit_v], tr, M, w_tot, b_star, b_bench)
                df = df[(df.mn >= 15) & df.imp_pts.notna()]
                if df.empty:
                    continue
                err = np.abs(df.pts - df.mu_pts).mean()
                if best_cfg is None or err < best_cfg[0]:
                    best_cfg = (err, w_tot, b_star, b_bench)
    _, w_tot, b_star, b_bench = best_cfg
    print(f"Chosen on 2025-26 pre-Jan 1: w_tot={w_tot}, b_star={b_star}, b_bench={b_bench}")

    for lab, mask in (("TEST 2025-26 (Jan+)", te_a), ("TEST 2026-27", te_b)):
        b0 = project_vegas(pr[mask], tr, M, 0.0, 0.0, 0.0)
        b1 = project_vegas(pr[mask], tr, M, w_tot, b_star, b_bench)
        ok = (b0.mn >= 15) & b0.imp_pts.notna()
        print(f"\n{lab} (n={int(ok.sum())} player-games with Vegas lines):")
        for k in ("min", "pts", "reb", "ast", "fg3"):
            ycol = "y_min" if k == "min" else k
            mcol = "mn" if k == "min" else "mu_" + k
            e0 = np.abs(b0.loc[ok, ycol] - b0.loc[ok, mcol]).values
            e1 = np.abs(b1.loc[ok, ycol] - b1.loc[ok, mcol]).values
            lo, hi, sh = boot_diff(e0, e1, b0.loc[ok, "gd"].values)
            print(f"  {k:<4} base {e0.mean():.4f} -> vegas {e1.mean():.4f} ({100*(e1.mean()/e0.mean()-1):+.2f}%, 95% CI {lo:+.4f}..{hi:+.4f}, better {sh:.0%})")

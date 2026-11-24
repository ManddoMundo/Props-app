# Research tool (weekly review 2026-11-24). Run from /home/claude/props/lab: python3 hl_bt.py <rebounds half-life> <assists half-life>. Writes err_*.pkl beside it.
"""Lab (weekly review 2026-11-24, research only): a separate rate memory for rebounds and assists.
Charter fixed before scoring: the half-life for each of reb and ast is chosen on 2024-25 (the fit season, after the 21-day
warm-up, players projected 15+ minutes, average miss); every other setting is the live one. Then scored once on 2025-26 and
2026-27 against the live 15-game memory. Adopt only if better in both test seasons for the stat it changes."""
import sys; sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
import nba as N
HL = dict(reb=float(sys.argv[1]) if len(sys.argv) > 1 else 15.0, ast=float(sys.argv[2]) if len(sys.argv) > 2 else 15.0)
DEC = {k: 0.5 ** (1 / v) for k, v in HL.items()}
class S2(N.State):
    def player_feat(self, pid, pos):
        f = super().player_feat(pid, pos); s = self.pl[pid]
        for k in DEC:
            f["r_" + k] = (s[k + "_x"] + N.PM0 * self.pri[pos][k]) / (s[k + "_mn"] + N.PM0)
        return f
    def update(self, season, t, o, rows):
        for r in rows:
            s = self.pl[r["pid"]]
            if self.ps.get(r["pid"], season) != season:
                for k in DEC: s[k + "_x"] *= N.CARRY; s[k + "_mn"] *= N.CARRY
            for k, dk in DEC.items():
                s[k + "_x"] = s[k + "_x"] * dk + r[k]; s[k + "_mn"] = s[k + "_mn"] * dk + r["min"]
        super().update(season, t, o, rows)
N.State = S2
d = N.load(); pr, tr, S = N.walk(d)
first = pr[pr.season == 2025].gd.min(); warm = pr.gd > str(pd.Timestamp(first) + pd.Timedelta(days=21))[:10]
M = {"bm": 0.8, "bs": {"pts": 0.5, "reb": 0.5, "ast": 0.5, "fg3": 0.5}, "cal": {}}
# same tuning as nba.main (bm, bs per stat on the fit season), then finish on the fit season and score
is_tr = warm & (pr.season == 2025)
best = None
for bm in (0.0, 0.5, 0.8, 1.0):
    M["bm"] = bm; dd = N.project(pr[is_tr], tr, M); e = np.abs(dd.y_min - dd.mn).mean()
    if best is None or e < best[0]: best = (e, bm)
M["bm"] = best[1]
for k in N.BASE:
    best = None
    for bs in (0.0, 0.25, 0.5, 0.75, 1.0):
        M["bs"][k] = bs; dd = N.project(pr[is_tr], tr, M); mm = dd.mn >= 15; e = np.abs(dd.loc[mm, k] - dd.loc[mm, "mu_" + k]).mean()
        if best is None or e < best[0]: best = (e, bs)
    M["bs"][k] = best[1]
m = dict(bm=M["bm"], bs=dict(M["bs"]), cal={})
dd = N.project(pr[is_tr], tr, m); mm = dd.mn >= 15
m["cal"] = {k: float(dd.loc[mm, k].sum() / dd.loc[mm, "mu_" + k].sum()) for k in N.BASE}
dd = N.project(pr[is_tr], tr, m); mm = dd.mn >= 15
m["lin"] = {k: [float(v) for v in np.polyfit(dd.loc[mm, "mu_" + k], dd.loc[mm, k], 1)[::-1]] for k in N.BASE}
out = [f"HL reb {HL['reb']:g} ast {HL['ast']:g}"]
for lab, mask in (("fit 2024-25", is_tr), ("test 2025-26", pr.season == 2026), ("test 2026-27", pr.season == 2027)):
    te = N.project(pr[mask], tr, m); mm = te.mn >= 15
    out.append(lab + " " + " ".join(f"{k} {np.abs(te.loc[mm, k] - te.loc[mm, 'mu_' + k]).mean():.5f}/{(te.loc[mm, k] - te.loc[mm, 'mu_' + k]).mean():+.3f}" for k in ("reb", "ast")))
    te.loc[mm, ["game_id", "pid", "season", "reb", "mu_reb", "ast", "mu_ast"]].to_pickle(f"err_{lab.split()[1]}_{HL['reb']:g}_{HL['ast']:g}.pkl")
print(" | ".join(out))

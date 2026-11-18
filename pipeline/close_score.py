# Research tool (v3.21 closing-line test). Run from /home/claude/props/lab with the decrypted history files in /home/claude/hist/txt (history.yml pulls them).
"""Scores the closing-line test (charter in close_bt.py)."""
import sys, math
sys.path.insert(0, "/home/claude/props/src")
import numpy as np, pandas as pd
import close_bt as C

R = pd.read_pickle("close_rows.pkl")
ll = lambda p, y: float(-(y * np.log(np.clip(p, .001, .999)) + (1 - y) * np.log(1 - np.clip(p, .001, .999))).mean())
br = lambda p, y: float(((p - y) ** 2).mean())

# market view and the desk blend, slate by slate as daily.py does it
R["p_mkt"] = [C.pov(r.lg, r.mkt, r.mm, r.line) if r.mm is not None and not pd.isna(r.mm) else np.nan for r in R.itertuples()]
R["p_mod"] = [C.pov(r.lg, r.mkt, r.mu, r.line) for r in R.itertuples()]
cen = {}
for (lg, date, mkt), z in R[R.mm.notna()].groupby(["lg", "date", "mkt"]):
    g = z[z.nb >= C.CFG["min_books"]]; g = g if len(g) else z; n = len(g); r = g.mm.sum() / g.mu.sum()
    cen[(lg, date, mkt)] = float(np.clip((n * r + C.CFG["cal_c_n0"]) / (n + C.CFG["cal_c_n0"]), .85, 1.15))
R["c"] = [cen.get((r.lg, r.date, r.mkt), 1.0) for r in R.itertuples()]
for tag, wfun in (("live", lambda lg, m: C.CAL.get(f"{lg}|{m}", {}).get("w", .25)), ("prior", lambda lg, m: .25)):
    R["w_" + tag] = [wfun(r.lg, r.mkt) for r in R.itertuples()]
    R["muf_" + tag] = [r.mu if pd.isna(r.mm) else r.mm + getattr(r, "w_" + tag) * (r.c * r.mu - r.mm) for r in R.itertuples()]
    R["p_desk_" + tag] = [C.pov(r.lg, r.mkt, getattr(r, "muf_" + tag), r.line) for r in R.itertuples()]
R["p_modc"] = [C.pov(r.lg, r.mkt, r.c * r.mu, r.line) for r in R.itertuples()]
R.to_pickle("close_scored.pkl")

S = R[R.p_mkt.notna()]
print(f"\nQ1. Who prices the over best at Hard Rock's closing line. Log loss (lower is better), {len(S)} props with 2+ books")
rows = []
for (lg, mkt), z in list(S.groupby(["lg", "mkt"])) + [(("ALL", "all"), S)]:
    rows.append(dict(lg=lg, mkt=mkt, n=len(z), over_rate=z.over.mean(), hardrock=ll(z.p_hr, z.over), books=ll(z.p_mkt, z.over),
                     model=ll(z.p_mod, z.over), model_centred=ll(z.p_modc, z.over), desk=ll(z.p_desk_live, z.over),
                     bias_model=(z.mu - z.line).mean(), bias_actual=(z.y - z.line).mean()))
T = pd.DataFrame(rows); pd.set_option("display.width", 250); print(T.round(4).to_string(index=False))

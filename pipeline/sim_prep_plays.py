"""v3.21 research tool, run from /home/claude/props/lab with nflverse play-by-play in lab/pbp (play_by_play_2023/2024.parquet
from github.com/nflverse/nflverse-data releases). Writes two files the pipeline ships: nfl_yards_lib.json (simcore: real catch and
carry yards) and nfl_play_lib.json (the replay).

Real-play library for the NFL replay, from nflverse play-by-play 2023-24 regular season.
State = down x yards-to-go bin. For each state: share of designed runs among runs and passes, and quantiles of the yards
gained on runs, catches; where runs go (left/middle/right x end/tackle/guard) and where passes go (short/deep x
left/middle/right) by yards bin; drive start yard lines after a kick or punt; 4th-down calls by field position."""
import pandas as pd, numpy as np, json
cols = ["season_type", "play_type", "down", "ydstogo", "yardline_100", "complete_pass", "yards_gained", "qb_kneel", "qb_spike", "qb_scramble",
        "two_point_attempt", "run_location", "run_gap", "pass_length", "pass_location", "sack", "fixed_drive", "game_id", "posteam", "drive_start_transition", "penalty"]
d = pd.concat([pd.read_parquet(f"pbp/pbp_{y}.parquet", columns=cols) for y in (2023, 2024)])
d = d[(d.season_type == "REG") & (d.two_point_attempt == 0)]
def tb(t): return np.select([t <= 2, t <= 6, t <= 10], [0, 1, 2], 3)
x = d[d.play_type.isin(["run", "pass"]) & (d.qb_kneel == 0) & (d.qb_spike == 0) & d.down.notna() & (d.penalty == 0)].copy()
x["run"] = (x.play_type == "run") & (x.qb_scramble == 0); x["st"] = ((x.down.astype(int) - 1) * 4 + tb(x.ydstogo)).astype(int)
x["inc"] = (x.play_type == "pass") & (x.complete_pass == 0) & (x.sack == 0)
q = np.linspace(0.025, 0.975, 20)
lib = {"run_share": [], "inc_share": [], "run_q": [], "catch_q": []}
for s in range(16):
    z = x[x.st == s]; lib["run_share"].append(round(z.run.mean(), 3)); p = z[~z.run]; lib["inc_share"].append(round(p.inc.mean(), 3))
    lib["run_q"].append(np.quantile(z[z.run].yards_gained, q).round(0).astype(int).tolist())
    lib["catch_q"].append(np.quantile(p[p.complete_pass == 1].yards_gained, q).round(0).astype(int).tolist())
r = x[x.run & x.run_location.notna()].copy(); r["lab"] = np.where(r.run_location == "middle", "up the middle", r.run_location + " " + r.run_gap.fillna("tackle"))
rb = pd.cut(r.yards_gained, [-99, 0, 3, 9, 19, 999], labels=False)
lib["run_dir"] = {"labels": sorted(r.lab.unique().tolist())}
lib["run_dir"]["w"] = [[round(float((r.lab[rb == b] == L).mean()), 3) for L in lib["run_dir"]["labels"]] for b in range(5)]
p = x[(x.play_type == "pass") & x.pass_location.notna() & x.pass_length.notna()].copy(); p["lab"] = p.pass_length + " " + p.pass_location
pc = p[p.complete_pass == 1]; pb = pd.cut(pc.yards_gained, [-99, 4, 9, 19, 999], labels=False)
lib["pass_dir"] = {"labels": sorted(p.lab.unique().tolist())}
lib["pass_dir"]["w"] = [[round(float((pc.lab[pb == b] == L).mean()), 3) for L in lib["pass_dir"]["labels"]] for b in range(4)]
pi = p[p.inc]; lib["pass_dir"]["inc"] = [round(float((pi.lab == L).mean()), 3) for L in lib["pass_dir"]["labels"]]
# drive starts: line of scrimmage on the first play of each drive that began with a kickoff or a punt
f = d[d.play_type.isin(["run", "pass", "punt", "field_goal"]) & d.down.notna()].groupby(["game_id", "fixed_drive"]).first()
f = f[f.drive_start_transition.isin(["KICKOFF", "PUNT"])]
lib["start_q"] = np.quantile(100 - f.yardline_100, np.linspace(0.01, 0.99, 40)).round(0).astype(int).tolist()
# 4th down: share that go for it, by own-yard-line bin (los 0-40, 40-60, 60-70, 70-100), on 4th and 1-2
f4 = d[(d.down == 4) & d.play_type.isin(["run", "pass", "punt", "field_goal"])].copy(); f4["los"] = 100 - f4.yardline_100
f4["go"] = f4.play_type.isin(["run", "pass"]); f4["b"] = pd.cut(f4.los, [0, 40, 60, 70, 100], labels=False)
lib["go4"] = [[round(float(f4[(f4.b == b) & (tb(f4.ydstogo) == t)].go.mean()), 3) for t in range(4)] for b in range(4)]
json.dump(lib, open("nfl_play_lib.json", "w"), separators=(",", ":"))
print(len(json.dumps(lib, separators=(",", ":"))), "bytes"); print("run share by state", lib["run_share"]); print("starts", lib["start_q"]); print("go4", lib["go4"])
print(lib["run_dir"]["labels"], lib["pass_dir"]["labels"])

# ---- the yards library for simcore (v3.21): 200 quantiles of yards per catch by position and per carry, 2023-24
P = pd.read_parquet("nfl_proj.parquet")[["player_id", "pos"]].drop_duplicates("player_id").set_index("player_id").pos
cols2 = ["season_type", "play_type", "complete_pass", "receiving_yards", "rushing_yards", "qb_kneel", "qb_scramble", "two_point_attempt", "receiver_player_id", "rusher_player_id"]
d2 = pd.concat([pd.read_parquet(f"pbp/pbp_{y}.parquet", columns=cols2) for y in (2023, 2024)]); d2 = d2[(d2.season_type == "REG") & (d2.two_point_attempt == 0)]
qq = np.linspace(0.0025, 0.9975, 200); yl = {}
c = d2[d2.complete_pass == 1].dropna(subset=["receiving_yards"]).copy(); c["pos"] = c.receiver_player_id.map(P)
for g, pos in (("WR", ["WR"]), ("TE", ["TE"]), ("RB", ["RB", "FB"])):
    yl["catch_" + g] = np.round(np.quantile(c[c.pos.isin(pos)].receiving_yards.values, qq), 1).tolist()
r = d2[(d2.play_type == "run") & (d2.qb_kneel == 0)].dropna(subset=["rushing_yards"]).copy(); r["pos"] = r.rusher_player_id.map(P)
yl["carry_RB"] = np.round(np.quantile(r[r.pos.isin(["RB", "FB", "WR"]) & (r.qb_scramble == 0)].rushing_yards.values, qq), 1).tolist()
yl["carry_QB"] = np.round(np.quantile(r[r.pos.isin(["QB"])].rushing_yards.values, qq), 1).tolist()
json.dump(yl, open("nfl_yards_lib.json", "w"))

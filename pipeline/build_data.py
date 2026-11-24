"""Merge both leagues into the one data blob the page embeds."""
import datetime, json, os
O = "/home/claude/props/out/"
nfl = json.load(open(O + "nfl.json"))
nba = json.load(open(O + "nba.json"))
nfl["sides"] = [dict(team=t, **{k: v for k, v in s.items()}) for t, s in nfl.pop("teams").items()]
REN = {"completions": "cmp", "attempts": "att", "passing_yards": "pyd", "passing_tds": "ptd",
       "carries": "car", "rushing_yards": "ryd", "rushing_tds": "rtd",
       "receptions": "rec", "targets": "tgt", "receiving_yards": "recyd", "receiving_tds": "rectd"}
for p in nfl["players"]:
    p["logs"] = {REN.get(k, k): v for k, v in p["logs"].items()}

def slim(bt):
    out = {}
    for k, v in bt.items():
        out[k] = {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk not in ("pit_deciles",)}
        if "reliability" in v:
            out[k]["reliability"] = [{a: (round(b, 3) if isinstance(b, float) else b) for a, b in r.items()} for r in v["reliability"]]
        if "mae_model_vs_l5" in v:
            out[k]["mae_model_vs_l5"] = [round(x, 3) for x in v["mae_model_vs_l5"]]
    return out

for d in (nfl, nba):
    d["backtest"] = slim(d["backtest"])
built = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
json.dump({"NFL": nfl, "NBA": nba, "built": built}, open(O + "data.json", "w"), separators=(",", ":"))
print(os.path.getsize(O + "data.json"))
